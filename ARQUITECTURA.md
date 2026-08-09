# Arquitectura del Sistema

Documento de diseño conceptual del sistema de recomendación batch (Taobao → LocalStack). Describe el problema, la topología por capas, el cronograma de desarrollo y la estimación de costos.

## Tabla de contenidos

1. [Definición del Problema y Alcance](#1-definición-del-problema-y-alcance)
2. [Diseño de Arquitectura y Tecnologías](#2-diseño-de-arquitectura-y-tecnologías)
3. [Cronograma y Etapas de Desarrollo](#3-cronograma-y-etapas-de-desarrollo)
4. [Costos: Estimación Financiera y FinOps](#4-costos-estimación-financiera-y-finops)
5. [Decisiones de implementación](#5-decisiones-de-implementación)

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

### 2.3 Capa de Procesamiento y Entrenamiento (Batch Computing)

- **Servicios:** Amazon EC2, EBS, IAM.
- **Racional:** Instancias EC2 efímeras, aprovisionadas con _Instance Profiles_ (IAM) para acceder a S3 sin credenciales estáticas. Ejecutan _scripts_ de Python para computar la ingeniería de características (discretización temporal, RFM, tasas de intención) y entrenar el modelo predictivo, separando la matriz histórica (días 1-7) del conjunto de validación y simulación diaria.
- **Nota de estado:** en LocalStack esta capa no está materializada (ver [COMPUTO.md](COMPUTO.md)).

### 2.4 Capa de Gobernanza y MLOps

- **Servicios:** Amazon EC2, Amazon RDS (PostgreSQL), Amazon S3.
- **Racional:** Despliegue de un servidor MLflow en una instancia ligera. Utiliza RDS como _backend store_ para la trazabilidad de hiperparámetros y métricas, y S3 como _artifact store_ para los binarios de los modelos.

### 2.5 Capa de Servicio e Inferencia Reactiva (Serving Layer)

- **Servicios:** Amazon VPC, Application Load Balancer (ELB), Auto Scaling Group (EC2), Amazon RDS.
- **Racional:** El proceso _batch_ exporta las predicciones calculadas hacia una base de datos RDS (PostgreSQL) estructurada como almacén clave-valor ($O(1)$ de latencia). Un ELB público enruta el tráfico web hacia un grupo de autoescalado de instancias EC2 en subredes privadas, las cuales ejecutan una API ligera (FastAPI en Docker) para consultar RDS y retornar las inferencias en tiempo real.

## 3. Cronograma y Etapas de Desarrollo

El desarrollo se estructura en fases secuenciales que garantizan la validación lógica y la reproducibilidad. Los _commits_ del repositorio siguen el estándar de _Conventional Commits_ en español.

### Fase 1: Redes e Infraestructura como Código

- **Objetivo:** Aprovisionar el perímetro de seguridad y los recursos persistentes.
- **Tareas:** Codificación en Terraform de la VPC multi-AZ, _Internet Gateway_, tablas de enrutamiento y _Security Groups_ bajo el principio de privilegio mínimo (lista blanca). Despliegue de _buckets_ S3 y clúster RDS Multi-AZ.

### Fase 2: Simulación de Datos y Bootstrap

- **Objetivo:** Desarrollar el _script_ determinista (`data_bootstrap.py`) que actúe como simulador transaccional.
- **Tareas:** Descarga del _dataset_ de Taobao, particionamiento físico cronológico del `timestamp`, conversión tabular a formato Parquet y carga paralela (vía `boto3`) a LocalStack S3 simulando la ingesta diaria.

### Fase 3: Pipeline Analítico y MLOps

- **Objetivo:** Automatizar la extracción de características y el ciclo de vida del modelo.
- **Tareas:** Desarrollo de _scripts_ de transformación ELT/ETL para calcular tensores de frecuencia, dominancia de comportamiento y suavizado de Laplace. Despliegue del contenedor de MLflow y ejecución del entrenamiento (XGBoost) registrando los artefactos.

### Fase 4: Capa de Exposición (Serving)

- **Objetivo:** Desacoplar la inferencia del entrenamiento para garantizar baja latencia.
- **Tareas:** Creación del esquema en PostgreSQL para almacenar resultados precomputados. Contenerización de la API HTTP. Configuración del Application Load Balancer y el Auto Scaling Group apuntando a las instancias EC2 en la subred privada.

## 4. Costos: Estimación Financiera y FinOps

La arquitectura desplegada en LocalStack será respaldada por una simulación económica rigurosa en la **AWS Pricing Calculator**, documentando los costos operativos reales en la nube.

- **Costos de Cómputo (EC2):** Se diferenciará el gasto de las instancias del _Auto Scaling Group_ (disponibilidad 24/7) frente al uso efímero de las instancias de procesamiento _batch_ (facturadas por horas/minutos de ejecución).
- **Costos de Almacenamiento (S3 y EBS):** Estimación volumétrica del _Data Lake_ (optimizada por la compresión de Parquet) y el almacenamiento en bloque adherido a las instancias.
- **Costos Transaccionales (RDS):** Cálculo del aprovisionamiento de la base de datos relacional (configuración Multi-AZ para HA) y, de manera crítica, el costo subyacente del almacenamiento de respaldos automáticos (_Automated Backups_).
- **Costos de Red (_Transfer Out_):** Estimación del tráfico saliente hacia internet a través del ELB y mitigación del gasto interno mediante el uso de _VPC Endpoints_ para el acceso a S3 sin transitar por un NAT Gateway.

## 5. Decisiones de implementación

- **Split temporal anti-leakage:** burn-in (días 1-3), train (4-6), val (7), test (8), infer (9). Ver [DEPLOYMENT.md](DEPLOYMENT.md).
- **`event_date` en `Asia/Shanghai` (UTC+8)**, nunca UTC, para no correr las particiones un día.
- **Muestreo negativo** (target = `buy|cart|fav`) cruzando usuarios con ítems populares no interactuados.
- **Recursos gated en LocalStack:** RDS, ELBv2, ASG y Launch Template son features Pro del emulador; se declaran en IaC pero se activan solo con flags (`rds_enabled`, `alb_asg_enabled`) para AWS real. Ver [COMPUTO.md](COMPUTO.md).
- **Sidecar PostgreSQL** como motor real de las bases (LocalStack solo emula la API de RDS).
