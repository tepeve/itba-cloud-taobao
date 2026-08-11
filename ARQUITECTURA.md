# Arquitectura del Sistema

Documento de diseño conceptual del sistema de recomendación batch (Taobao → LocalStack). Describe el problema, la topología por capas y las decisiones de implementación. El cronograma de desarrollo, la estimación de costos y las mediciones del pipeline se documentan en [PLANIFICACIÓN_Y_COSTOS.md](PLANIFICACIÓN_Y_COSTOS.md).

## Tabla de contenidos

1. [Definición del Problema y Alcance](#1-definición-del-problema-y-alcance)
2. [Diseño de Arquitectura y Tecnologías](#2-diseño-de-arquitectura-y-tecnologías)
3. [Decisiones de implementación](#3-decisiones-de-implementación)

---

## 1. Definición del Problema y Alcance

El objetivo es diseñar una arquitectura en la nube inmutable y reproducible (emulada en LocalStack) para optimizar el _funnel_ de conversión de un e-commerce. La solución implementa un _pipeline_ analítico _batch_ que procesa eventos estocásticos de navegación para calcular la probabilidad de interacción usuario-ítem. El alcance se enmarca en la migración de un "componente conocido": el subsistema de inferencia predictiva.

## 2. Diseño de Arquitectura y Tecnologías

La topología se segmenta en cuatro capas lógicas con responsabilidades aisladas, garantizando alta disponibilidad, seguridad pasiva y desacoplamiento.

### 2.1 Stack Tecnológico Base

- **Infraestructura como Código (IaC):** OpenTofu / Terraform.
- **Lenguajes y Motores:** Python (Pandas/DuckDB para procesamiento en memoria), SQL (PostgreSQL).
- **Entorno de Emulación:** LocalStack administrado vía Docker Compose.

### 2.2 Capa de Ingesta y Almacenamiento Estructurado (Data Lake)

- **Servicio:** Amazon S3
- **Racional:** Actúa como la única fuente de verdad. El dataset crudo de Taobao (interacciones de usuarios con artículos y categorías) ingresa fragmentado cronológicamente y convertido a formato **Parquet**. Se estructura en _buckets_ privados con los prefijos lógicos `/raw`, `/processed` y `/models`.
- **Origen del dataset:** `UserBehavior.csv` se descarga de [Kaggle (marwa80/userbehavior)](https://www.kaggle.com/datasets/marwa80/userbehavior/data) y se aloja en `data/raw/` (ver [DEPLOYMENT.md](DEPLOYMENT.md)).

### 2.3 Capa de Procesamiento y Entrenamiento (Batch Computing)

- **Servicios:** Amazon EC2, EBS, IAM.
- **Racional:** Instancias EC2 efímeras, aprovisionadas con _Instance Profiles_ (IAM) para acceder a S3 sin credenciales estáticas. Ejecutan _scripts_ de Python para computar la ingeniería de características (discretización temporal, RFM, tasas de intención) y entrenar el modelo predictivo, separando la matriz histórica (días 1-7) del conjunto de validación y simulación diaria.
- **Nota de estado:** esta capa quedó materializada en el **Sprint 2** como IaaS orquestado por Airflow: una instancia orquestadora `taobao-airflow` (`aws_instance`) en subred privada ejecuta el DAG `taobao_dag.py`, sustituyendo la ejecución manual secuencial de los scripts (ver [2.3.1](#231-cómputo-orquestado-sprint-2)). En LocalStack la instancia es simbólica (mock VM): representa el plano de control declarativo; el cómputo real corre en el host.

#### 2.3.1 Cómputo orquestado (Sprint 2)

- **Orquestador:** `aws_instance` `taobao-airflow` (`t3.medium`, subred privada, `sg_airflow`, perfil IAM batch) con `user_data = templatefile(init_airflow.sh.tpl)`: instala Docker, sincroniza el bucket `taobao-airflow-dags` a `/opt/airflow/dags` (cron cada 5 min), resuelve la contraseña DB vía SSM y levanta `apache/airflow:2.9.0` con `LocalExecutor`.
- **Red:** NAT Gateway (EIP en subred pública) + VPC Endpoint S3 (Gateway) sobre la route table privada, para que las instancias privadas accedan a S3 sin transitar por el NAT. Security Group `sg_airflow` (renombrado de `sg_batch_ec2`) con ingress interno 8080/5000 desde `vpc_cidr`.
- **Secretos:** SSM Parameter `/taobao/prod/rds_password` (`SecureString`) con policy `ssm:GetParameter` + `kms:Decrypt`; sin credenciales en texto plano.
- **DAG `taobao_dag.py`:** `BashOperator` con `env_vars` (`BUCKET`, `MLFLOW_TRACKING_URI`, `PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE`, `LOCALSTACK_ENDPOINT`) y topología `t_bootstrap >> t_features >> t_training >> t_inference`. Los scripts analíticos leen estas variables **sin fallbacks `localhost`** (el contexto lo inyecta Airflow).
- **Caveat LocalStack:** community no procesa `user_data` ni arranca Airflow en la instancia; la verificación local de la orquestación se realiza con `docker-compose.airflow.yml` + `.airflowignore`.

#### 2.3.2 Estado de materialización en LocalStack

| Componente | ¿Materializado en LocalStack? | Dónde corre realmente |
|---|---|---|
| Instancia EC2 orquestadora (Airflow) | **Sí** (`aws_instance`, mock VM) | Declarada en IaC; `describe_instances` la muestra `running` |
| Instancias de servicio (FastAPI) | No — **gated** (`alb_asg_enabled=false`) | Definido en IaC; en local se sirve vía `uvicorn`/`TestClient` |
| Launch Template (API) | No — **gated** | Definido en IaC (`templatefile` de `init_api.sh.tpl`) |
| Auto Scaling Group | No — **gated** | Definido en IaC |
| Application Load Balancer | No — **gated** (ELBv2 es Pro) | Definido en IaC |

Restricciones del emulador **community** (`localstack/localstack:3.5.0`):

| Servicio | Soporte en community | Uso en el proyecto |
|----------|----------------------|--------------------|
| EC2 (VPC, subredes, SG, IAM, `aws_instance`) | **Sí** | Red/SG/IAM/orquestador materializados |
| NAT Gateway, VPC Endpoint (Gateway) | **Sí** (CRUD) | Materializados |
| SSM (Parameter Store) | **Sí** (Hobby) | Secretos materializados |
| ELBv2, Auto Scaling, Launch Template | **No** (Pro) | Gated (`alb_asg_enabled`) |
| RDS | **No** (Pro) | Gated + sidecar postgres |

El inventario detallado de recursos materializados y gated está en [INFRAESTRUCTURA.md](INFRAESTRUCTURA.md). Para materializar los recursos gated en AWS real: `tofu apply -var="rds_enabled=true" -var="alb_asg_enabled=true"`.

### 2.4 Capa de Gobernanza y MLOps

- **Servicios:** Amazon EC2, Amazon RDS (PostgreSQL), Amazon S3.
- **Racional:** Despliegue de un servidor MLflow en una instancia ligera. Utiliza RDS como _backend store_ para la trazabilidad de hiperparámetros y métricas, y S3 como _artifact store_ para los binarios de los modelos.

### 2.5 Capa de Servicio e Inferencia Reactiva (Serving Layer)

- **Servicios:** Amazon VPC, Application Load Balancer (ELB), Auto Scaling Group (EC2), Amazon RDS.
- **Racional:** El proceso _batch_ exporta las predicciones calculadas hacia una base de datos RDS (PostgreSQL) estructurada como almacén clave-valor ($O(1)$ de latencia). Un ELB público enruta el tráfico web hacia un grupo de autoescalado de instancias EC2 en subredes privadas, las cuales ejecutan una API ligera (FastAPI en Docker) para consultar RDS y retornar las inferencias en tiempo real. En LocalStack esta capa es **gated** (ver [2.3.2](#232-estado-de-materialización-en-localstack)).

## 3. Decisiones de implementación

- **Split temporal anti-leakage:** burn-in (días 1-3), train (4-6), val (7), test (8), infer (9). Ver [DEPLOYMENT.md](DEPLOYMENT.md).
- **`event_date` en `Asia/Shanghai` (UTC+8)**, nunca UTC, para no correr las particiones un día.
- **Muestreo negativo** (target = `buy|cart|fav`) cruzando usuarios con ítems populares no interactuados.
- **Recursos gated en LocalStack:** RDS, ELBv2, ASG y Launch Template son features Pro del emulador; se declaran en IaC pero se activan solo con flags (`rds_enabled`, `alb_asg_enabled`) para AWS real. Ver [DEPLOYMENT.md](DEPLOYMENT.md) e [INFRAESTRUCTURA.md](INFRAESTRUCTURA.md).
- **Sidecar PostgreSQL** como motor real de las bases (LocalStack solo emula la API de RDS).
