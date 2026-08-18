# Planificación y Costos

Documento de planificación del sistema de recomendación batch (Taobao → LocalStack): estimación financiera (FinOps) respaldada en AWS Pricing Calculator, mediciones reales del pipeline y cronograma de desarrollo por fases.

## Tabla de contenidos

1. [Costos: Estimación Financiera y FinOps](#1-costos-estimación-financiera-y-finops)
2. [Mediciones reales del pipeline](#2-mediciones-reales-del-pipeline)
3. [Cronograma y Etapas de Desarrollo](#3-cronograma-y-etapas-de-desarrollo)

---

## 1. Costos: Estimación Financiera y FinOps

Estimación respaldada en la **AWS Pricing Calculator** (región `us-east-1`, On-Demand, sin instancias Reservadas ni Savings Plans). Los valores reproducen la configuración real del IaC (`terraform/modules/*`) y las decisiones de dimensionamiento acordadas durante la sesión de FinOps. El detalle completo está en [AWS Pricing Calculator — Taobao Estimate](https://calculator.aws/#/estimate?id=37289b14eb845c08e797e5a69e3952289384f984).

> **Total estimado: $133.58/mes ≈ $1,602.96/año.**

El costo se separa en dos naturalezas:

- **Componentes siempre encendidos (24/7):** el grueso del presupuesto. Orquestador Airflow, ASG de la API, RDS, ALB y NAT Gateway facturan continuamente, independientemente de que el batch corra pocos minutos al día.
- **Cómputo batch efímero:** los scripts (`data_bootstrap` → `pipeline_features` → `pipeline_training` → `pipeline_inference`) consumen CPU/RAM por minutos, sobre las mismas instancias 24/7. No suman línea de facturación propia: su costo marginal es despreciable.

### 1.1 Resumen ejecutivo

| Servicio | Configuración | Costo/mes |
|---|---|---|
| Amazon EC2 — orquestador Airflow | `t3.medium` ×1, On-Demand 24/7 | $30.37 |
| Amazon EC2 — API (Auto Scaling Group) | `t3.micro` ×2 (min 2 / max 4) | $15.18 |
| Amazon EBS | 3 volúmenes × 30 GB gp3 (sin snapshots) | $7.20 |
| Amazon S3 — `taobao-datalake` | 6 GB Standard + requests | $0.14 |
| Amazon S3 — `taobao-mlflow-artifacts` | 1 GB Standard + requests | $0.02 |
| Amazon S3 — `taobao-airflow-dags` | requests (sync cron) | $0.00 |
| Amazon RDS for PostgreSQL | `db.t3.micro`, 20 GB, Multi-AZ | $30.88 |
| Application Load Balancer | 1 ALB público (LCU < 1) | $16.90 |
| Public IPv4 Address | 1 EIP asociada al NAT (gratis) | $0.00 |
| NAT Gateway | 1 estándar, ~1 GB/mes procesado | $32.89 |
| **Total** | | **$133.58** |

### 1.2 Desglose por servicio

#### EC2 — Orquestador Airflow ($30.37/mes)

| Parámetro | Valor |
|---|---|
| Recurso IaC | `aws_instance.airflow_orchestrator` (módulo `compute`) |
| Tipo | `t3.medium` (2 vCPU / 4 GiB) |
| Instancias | 1 |
| Workload | **Constant usage** (24/7, 730 h/mes) |
| Pricing | On-Demand, tenancy shared, Linux, monitoring deshabilitado |
| Red | Subred privada, sin IP pública (salida por NAT + VPC Endpoint S3) |
| Data Transfer | Inbound/outbound/intra-region = 0 |

**Racional:** el scheduler + webserver de Airflow (`LocalExecutor`) corren de forma continua; el batch (~7 min/día de `data_bootstrap` + `pipeline_features` + `pipeline_inference`) es un pico diario sobre esa línea base. El spike del martes (entrenamiento) no cambia la modalidad de uso constante.

#### EC2 — API (Auto Scaling Group, $15.18/mes)

| Parámetro | Valor |
|---|---|
| Recurso IaC | `aws_autoscaling_group` (módulo `alb_asg`) |
| Tipo | `t3.micro` (1 vCPU / 1 GiB) |
| Instancias | 2 base (`min_size=2`, `max_size=4`, `desired_capacity=2`) |
| Workload | Consistent (24/7, 1.460 h/mes) |
| Pricing | On-Demand |

#### EBS ($7.20/mes)

| Parámetro | Valor |
|---|---|
| Volúmenes | 3 root (1 orquestador + 2 API) |
| Tamaño | 30 GB c/u → 90 GB |
| Tipo | gp3 (baseline 3.000 IOPS / 125 MB/s incluidos) |
| Snapshots | **Sin snapshots** (no definidos en el IaC) |

#### S3 ($0.16/mes en total)

Todos los buckets en **S3 Standard**, sin lifecycle ni S3 Select (DuckDB lee Parquet directo vía `httpfs`). Data transfer out = 0 (acceso interno a través del VPC Endpoint Gateway, gratuito).

| Bucket | Storage | PUT/COPY/POST/LIST | GET/otros |
|---|---|---|---|
| `taobao-datalake` | 6 GB | 1.000/mes | 3.000/mes |
| `taobao-mlflow-artifacts` | 1 GB | 200/mes | 1.000/mes |
| `taobao-airflow-dags` | ~0 GB | 9.000/mes | 100/mes |

**Trazabilidad con las mediciones (ver §2):** el datalake mide 1.56 GB reales; se presupuestan 6 GB como margen de crecimiento (~4×). Los artifacts de MLflow miden 1.4 MB; se redondean a 1 GB. El bucket de DAGs está dominado por LIST (el orquestador sincroniza vía `s3 sync` cada 5 min ≈ 8.640/mes).

**Proyección de crecimiento:** 9 días de datos → 1.56 GB implican ~60 GB/año. El presupuesto de 6 GB cubre el estado actual con margen, pero el bucket debe re-estimarse al anualizar (y considerar transicionar datos históricos a una clase de menor costo).

#### RDS for PostgreSQL ($30.88/mes)

| Parámetro | Valor |
|---|---|
| Motor | PostgreSQL 15 |
| Clase | `db.t3.micro` |
| Deployment | **Multi-AZ** (1 nodo primario + 1 standby) |
| Storage | 20 GB gp2 (provisionado; medido ~0.46 GB) |
| RDS Proxy | No (conexiones directas `psycopg2`/`asyncpg`) |
| Database Insights | No |
| Extended Support | No (PostgreSQL 15 dentro del soporte estándar) |
| Backups automáticos | 7 días (incluidos hasta 100% del storage) |

**Dimensionamiento del storage:** `inference_results` mide 444 MB con 950.927 usuarios y crece lineal con la base (ver §2). El storage provisionado de 20 GB tolera ~40× la base actual sin re-dimensionar.

> **Nota — supuesto declarado de HA:** el presupuesto asume Multi-AZ como objetivo de alta disponibilidad (coherente con la narrativa FinOps). El IaC actual (`terraform/modules/rds/main.tf`) **no** setea `multi_az`, por lo que `tofu apply` despliega single-AZ. En AWS real se materializa con `tofu apply -var="rds_enabled=true"` tras habilitar `multi_az` en el módulo. Se documenta como supuesto, no como contradicción.

#### Application Load Balancer ($16.90/mes)

| Parámetro | Valor |
|---|---|
| ALBs | 1 (público, `application`, HTTP 80 → 8000, health check `/health`) |
| LCU | < 1 (tráfico ínfimo) |
| Dimensiones | ~12 req/s, ~0.05 GB/h, ~2 conexiones nuevas/s |

**Racional de la carga:** el techo de requests lo fija `inference_results` (950.927 usuarios). Asumiendo 1 recomendación por usuario por día ≈ 11 req/s promedio; aun sirviendo al 100% de los usuarios una vez por día, el consumo queda muy por debajo de 1 LCU (límites: 25 conn/s, 1 GB/h). Domina la tarifa fija por hora (~$0.0225/h).

#### Public IPv4 Address ($0.00/mes)

| Parámetro | Valor |
|---|---|
| Elastic IP | 1 (asociada al NAT Gateway) |
| Costo | Gratis mientras esté asociada al NAT |
| Idle | 0 (EC2 sin IP pública; el ALB no factura IP por separado) |

#### NAT Gateway ($32.89/mes)

| Parámetro | Valor |
|---|---|
| Gateways | 1 **estándar** en 1 AZ |
| Data procesada | ~1 GB/mes |
| Tarifa | $0.045/h + $0.045/GB |

**Racional del ~1 GB/mes:** el tráfico hacia S3 usa el VPC Endpoint (Gateway, gratuito) y no transita por el NAT; RDS y MLflow son internos a la VPC. Solo pasa por el NAT el aprovisionamiento inicial (apt, `docker pull apache/airflow`, `uv sync`) y los updates periódicos del SO. Estado estable ≈ 0 GB.

### 1.3 Análisis FinOps

| # | Componente | Costo/mes | % del total | Naturaleza |
|---|---|---|---|---|
| 1 | NAT Gateway | $32.89 | 24.6% | 24/7 |
| 2 | RDS (Multi-AZ) | $30.88 | 23.1% | 24/7 |
| 3 | EC2 orquestador | $30.37 | 22.7% | 24/7 |
| 4 | ALB | $16.90 | 12.7% | 24/7 |
| 5 | EC2 API (ASG) | $15.18 | 11.4% | 24/7 |
| 6 | EBS | $7.20 | 5.4% | 24/7 |
| 7 | S3 | $0.16 | 0.1% | almacenamiento |
| 8 | Public IPv4 | $0.00 | 0.0% | — |

**Conclusiones del análisis:**

1. **Los tres rubros mayores (NAT, RDS, EC2) concentran ~70% del costo** y son todos componentes 24/7. El cómputo batch es marginal: no aparece como línea de facturación propia porque corre sobre la instancia orquestadora ya encendida.
2. **El NAT Gateway es el mayor rubro de red** ($32.89) pese a que casi todo el tráfico lo evita. La mitigación clave es el VPC Endpoint S3 (Gateway, gratuito): sin él, los ~1.56 GB diarios de Parquet circularían por el NAT multiplicando el GB procesado.
3. **El almacenamiento es despreciable** (S3 + EBS ≈ $7.36, ~5.5%), gracias a la compresión de Parquet y a que el modelo XGBoost (~89 KB) y la base MLflow (~11 MB) son ínfimos.
4. **Multi-AZ es una decisión de disponibilidad, no de carga:** duplica el costo de instancia del RDS (~$15 → ~$31) con 0.46 GB de datos. Es un supuesto declarado de HA (ver nota en §1.2), no una necesidad de rendimiento.
5. **EIP gratis y snapshots omitidos** son decisiones deliberadas: la EIP va asociada al NAT (gratis) y el IaC no define snapshots EBS.

---

## 2. Mediciones reales del pipeline

Medidas sobre el dataset completo (100M filas) en LocalStack con datos reales. Los volúmenes alimentan el dimensionamiento del presupuesto (§1): cada cifra medible se mapea a su línea del AWS Calculator.

### Tiempos de ejecución (medidos)

| Etapa | Dataset completo | Dataset toy (fixtures) |
|-------|------------------|------------------------|
| `data_bootstrap.py` | ~1-2 min (CSV 3.5 GB → Parquet) | segundos |
| `pipeline_features.py` | ~2-3 min | ~1 s |
| `pipeline_training.py` | ~15-30 s (7.69M filas) | ~2 s |
| `pipeline_inference.py` | ~1-2 min (11.5M candidatos) | segundos |

> Nota: los tiempos varían según hardware; DuckDB procesa el CSV completo en ~12 s (solo lectura).

### Tamaños por capa (datos reales)

| Capa | Ubicación | Tamaño | Detalle |
|------|-----------|--------|---------|
| **Raw** | `s3://taobao-datalake/raw/` | **1.14 GB** | 9 particiones `event_date=`, 100M filas, 969.353 usuarios |
| **Features** | `s3://taobao-datalake/processed/` | **418 MB** | 4 splits (Parquet comprimido) |
| &nbsp;&nbsp;→ train | | 101.5 MB | 7.69M filas (3.08M pos + 4.61M neg) |
| &nbsp;&nbsp;→ val | | 33.8 MB | 2.71M filas |
| &nbsp;&nbsp;→ test | | 42.1 MB | 3.44M filas |
| &nbsp;&nbsp;→ infer | | 240.7 MB | 11.48M candidatos (sin label) |
| **Modelo** | `s3://taobao-mlflow-artifacts/` | **~89 KB** | `model.ubj` XGBoost (200 árboles, depth 4) |
| &nbsp;&nbsp;→ store total | | 1.4 MB | 22 modelos históricos + metadata |
| **RDS (servicio)** | PostgreSQL `inference_results` | **444 MB** | 950.927 filas Top-K (con índice) |
| &nbsp;&nbsp;→ base `taobao` total | | 452 MB | |
| &nbsp;&nbsp;→ base `mlflow` | | 11.4 MB | backend store MLflow |

### Total desplegado

| Componente | Tamaño |
|------------|--------|
| S3 (raw + processed) | 1.56 GB |
| MLflow artifacts | 1.4 MB |
| PostgreSQL (taobao + mlflow) | 0.46 GB |
| **TOTAL** | **~2.02 GB** |

Referencia: el CSV original en disco pesa 3.5 GB (fuente, no desplegado).

### Trazabilidad medición → presupuesto

| Medición (LocalStack) | Línea del AWS Calculator |
|---|---|
| Datalake 1.56 GB | S3 `taobao-datalake` presupuestado en **6 GB** (margen ~4×) |
| MLflow artifacts 1.4 MB | S3 `taobao-mlflow-artifacts` redondeado a **1 GB** |
| PostgreSQL 0.46 GB | RDS `allocated_storage = 20 GB` (provisionado) |
| 950.927 filas `inference_results` | Techo de requests del ALB (≈ 950K req/día → ~11 req/s) |

### Conclusiones sobre costos/computación

1. **El muestreo negativo domina las filas pero no el tamaño:** los 4.6M negativos de train son ~60% de sus filas, pero el Parquet comprime a ~30 B/fila → `processed/` total 418 MB, solo ~1/3 del raw.
2. **El `inference_results` es el mayor costo relacional** (444 MB para 950K filas Top-K), mayor que las matrices de features.
3. **El modelo es despreciable** (~89 KB).
4. **Escalabilidad:** todo el pipeline con datos reales cabe en ~2 GB, coherente con un presupuesto S3 de 6 GB y un RDS de 20 GB. Los costos 24/7 (NAT, EC2, RDS Multi-AZ) no dependen de estos volúmenes: el almacenamiento es la parte más barata del presupuesto.

---

## 3. Cronograma y Etapas de Desarrollo

El desarrollo se estructura en fases secuenciales que garantizan la validación lógica y la reproducibilidad. Los _commits_ del repositorio siguen el estándar de _Conventional Commits_ en español.

- **Fases 1-5:** prototipo sobre LocalStack (desarrollo, validación lógica, emulación de AWS).
- **Fases 6-8:** montado y despliegue de producción en AWS real (materialización de los recursos gated y puesta en operación).

### Fase 1: Redes e Infraestructura como Código

- **Objetivo:** Aprovisionar el perímetro de seguridad y los recursos persistentes.
- **Tareas:** Codificación en Terraform de la VPC multi-AZ, _Internet Gateway_, tablas de enrutamiento y _Security Groups_ bajo el principio de privilegio mínimo (lista blanca). Despliegue de _buckets_ S3. (En LocalStack los recursos RDS/ALB/ASG quedan gated; en AWS real se materializan en la Fase 6.)

### Fase 2: Simulación de Datos y Bootstrap

- **Objetivo:** Desarrollar el _script_ determinista (`data_bootstrap.py`) que actúe como simulador transaccional.
- **Tareas:** Descarga del _dataset_ de Taobao, particionamiento físico cronológico del `timestamp`, conversión tabular a formato Parquet y carga paralela (vía `boto3`) a LocalStack S3 simulando la ingesta diaria.

### Fase 3: Pipeline Analítico y MLOps

- **Objetivo:** Automatizar la extracción de características y el ciclo de vida del modelo.
- **Tareas:** Desarrollo de _scripts_ de transformación ELT/ETL para calcular tensores de frecuencia, dominancia de comportamiento y suavizado de Laplace. Despliegue del contenedor de MLflow y ejecución del entrenamiento (XGBoost) registrando los artefactos.

### Fase 4: Capa de Exposición (Serving)

- **Objetivo:** Desacoplar la inferencia del entrenamiento para garantizar baja latencia.
- **Tareas:** Creación del esquema en PostgreSQL para almacenar resultados precomputados. Contenerización de la API HTTP. Configuración del Application Load Balancer y el Auto Scaling Group apuntando a las instancias EC2 en la subred privada.

### Fase 5: Cómputo Orquestado (Sprint 2)

- **Objetivo:** Migrar la capa de cómputo batch al paradigma IaaS orquestado por Apache Airflow, sustituyendo la ejecución manual secuencial de los scripts.
- **Tareas:**
  - Red con **NAT Gateway** (EIP en subred pública) + **VPC Endpoint S3** (Gateway) sobre la route table privada, para que las instancias privadas accedan a S3 sin transitar por el NAT.
  - Security Group `sg_airflow` (renombrado de `sg_batch_ec2`) con ingress interno 8080/5000 desde `vpc_cidr`; `sg_rds` solo autoriza `sg_airflow` + `sg_api_ec2` (5432).
  - Secretos de la base en **SSM Parameter Store** (`/taobao/prod/rds_password`, `SecureString`) con policy `ssm:GetParameter` + `kms:Decrypt`, sin credenciales en texto plano.
  - Instancia orquestadora `aws_instance` `taobao-airflow` en subred privada con perfil IAM batch; `user_data = templatefile(init_airflow.sh.tpl)` instala Docker, sincroniza el bucket `taobao-airflow-dags` a `/opt/airflow/dags` (cron cada 5 min) y levanta `apache/airflow:2.9.0` con `LocalExecutor`.
  - DAG `taobao_dag.py` que orquesta los 4 scripts analíticos vía `BashOperator`, inyectando el contexto (`BUCKET`, `MLFLOW_TRACKING_URI`, `PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE`, `LOCALSTACK_ENDPOINT`) sin fallbacks `localhost`.
  - Verificación local de la orquestación con `docker-compose.airflow.yml` (contenedor `apache/airflow:2.9.0` + `.airflowignore`), dado que en LocalStack community la instancia EC2 es simbólica (mock VM que no procesa `user_data`).

### Fase 6: IaC de Producción en AWS

- **Objetivo:** Materializar en AWS real los recursos que LocalStack community mantiene gated.
- **Tareas:**
  - `tofu apply -var="rds_enabled=true" -var="alb_asg_enabled=true"` sobre el mismo código declarativo.
  - Creación del `aws_db_instance` PostgreSQL 15 (`db.t3.micro`, 20 GB) en subredes privadas; habilitar **Multi-AZ** (supuesto de HA del presupuesto, ver §1.2) — requiere setear `multi_az = true` en `rds/main.tf` antes del apply.
  - Creación del ALB público, target group (HTTP 8000, health check `/health`), listener, launch template (`init_api.sh.tpl`) y Auto Scaling Group (min 2 / max 4) en subredes privadas.
  - Verificación de los outputs (`rds_endpoint`, `alb_dns_name`) y de la conectividad SG → RDS.

### Fase 7: Cómputo Orquestado en EC2 Real

- **Objetivo:** Poner en operación el orquestador Airflow sobre la instancia EC2 `t3.medium` real.
- **Tareas:**
  - La instancia procesa `user_data` (a diferencia del mock de LocalStack): instala Docker, resuelve la contraseña DB vía SSM y levanta `apache/airflow:2.9.0` con `LocalExecutor`.
  - Sincronización del bucket `taobao-airflow-dags` → `/opt/airflow/dags` (cron cada 5 min) y carga de las Airflow Variables (`datalake_bucket`, `mlflow_db_uri`, `rds_host`, `rds_user`, `rds_password`, `localstack_endpoint`).
  - Ejecución del DAG `taobao_dag.py` contra S3 y RDS reales, reemplazando el endpoint de LocalStack por los servicios de AWS.

### Fase 8: Serving en Producción y FinOps

- **Objetivo:** Exponer la API en producción y validar el presupuesto.
- **Tareas:**
  - Despliegue de la imagen `taobao-api` vía launch template; el ASG la escala (min 2 / max 4) detrás del ALB.
  - Pruebas de carga sobre `GET /recommendations/{user_id}` (esperado ~11 req/s, < 1 LCU).
  - Monitoreo de costos contra el presupuesto de **$133.58/mes** (§1): seguimiento de NAT (GB procesado), RDS (storage vs 20 GB), S3 (storage vs 6 GB) y LCU del ALB.
  - Cierre FinOps: comparar la estimación del AWS Pricing Calculator con el consumo real (Cost Explorer), documentando desvíos y oportunidades (por ejemplo, transicionar datos históricos de S3 a clases de menor costo si el datalake anual supera los 6 GB).
