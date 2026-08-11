# Planificación y Costos

Documento de planificación del sistema de recomendación batch (Taobao → LocalStack): cronograma de desarrollo por fases, estimación financiera (FinOps) y mediciones reales del pipeline.

## Tabla de contenidos

1. [Cronograma y Etapas de Desarrollo](#1-cronograma-y-etapas-de-desarrollo)
2. [Costos: Estimación Financiera y FinOps](#2-costos-estimación-financiera-y-finops)
3. [Mediciones reales del pipeline](#3-mediciones-reales-del-pipeline)
4. [Análisis de escalabilidad](#4-análisis-de-escalabilidad)

---

## 1. Cronograma y Etapas de Desarrollo

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

### Fase 5: Cómputo Orquestado (Sprint 2)

- **Objetivo:** Migrar la capa de cómputo batch al paradigma IaaS orquestado por Apache Airflow, sustituyendo la ejecución manual secuencial de los scripts.
- **Tareas:**
  - Red con **NAT Gateway** (EIP en subred pública) + **VPC Endpoint S3** (Gateway) sobre la route table privada, para que las instancias privadas accedan a S3 sin transitar por el NAT.
  - Security Group `sg_airflow` (renombrado de `sg_batch_ec2`) con ingress interno 8080/5000 desde `vpc_cidr`; `sg_rds` solo autoriza `sg_airflow` + `sg_api_ec2` (5432).
  - Secretos de la base en **SSM Parameter Store** (`/taobao/prod/rds_password`, `SecureString`) con policy `ssm:GetParameter` + `kms:Decrypt`, sin credenciales en texto plano.
  - Instancia orquestadora `aws_instance` `taobao-airflow` en subred privada con perfil IAM batch; `user_data = templatefile(init_airflow.sh.tpl)` instala Docker, sincroniza el bucket `taobao-airflow-dags` a `/opt/airflow/dags` (cron cada 5 min) y levanta `apache/airflow:2.9.0` con `LocalExecutor`.
  - DAG `taobao_dag.py` que orquesta los 4 scripts analíticos vía `BashOperator`, inyectando el contexto (`BUCKET`, `MLFLOW_TRACKING_URI`, `PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE`, `LOCALSTACK_ENDPOINT`) sin fallbacks `localhost`.
  - Verificación local de la orquestación con `docker-compose.airflow.yml` (contenedor `apache/airflow:2.9.0` + `.airflowignore`), dado que en LocalStack community la instancia EC2 es simbólica (mock VM que no procesa `user_data`).

## 2. Costos: Estimación Financiera y FinOps

La arquitectura desplegada en LocalStack será respaldada por una simulación económica rigurosa en la **AWS Pricing Calculator**, documentando los costos operativos reales en la nube.

- **Costos de Cómputo (EC2):** Se diferenciará el gasto de las instancias del _Auto Scaling Group_ (disponibilidad 24/7) frente al uso efímero de las instancias de procesamiento _batch_ (facturadas por horas/minutos de ejecución).
- **Costos de Almacenamiento (S3 y EBS):** Estimación volumétrica del _Data Lake_ (optimizada por la compresión de Parquet) y el almacenamiento en bloque adherido a las instancias.
- **Costos Transaccionales (RDS):** Cálculo del aprovisionamiento de la base de datos relacional (configuración Multi-AZ para HA) y, de manera crítica, el costo subyacente del almacenamiento de respaldos automáticos (_Automated Backups_).
- **Costos de Red (_Transfer Out_):** Estimación del tráfico saliente hacia internet a través del ELB y mitigación del gasto interno mediante el uso de _VPC Endpoints_ para el acceso a S3 sin transitar por un NAT Gateway.

## 3. Mediciones reales del pipeline

Medidas sobre el dataset completo (100M filas) en LocalStack con datos reales.

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
| **Raw** | `s3://taobao-datalake/raw/` | **1.14 GB** | 9 particiones `event_date=`, 100M filas, 969,353 usuarios |
| **Features** | `s3://taobao-datalake/processed/` | **418 MB** | 4 splits (Parquet comprimido) |
| &nbsp;&nbsp;→ train | | 101.5 MB | 7.69M filas (3.08M pos + 4.61M neg) |
| &nbsp;&nbsp;→ val | | 33.8 MB | 2.71M filas |
| &nbsp;&nbsp;→ test | | 42.1 MB | 3.44M filas |
| &nbsp;&nbsp;→ infer | | 240.7 MB | 11.48M candidatos (sin label) |
| **Modelo** | `s3://taobao-mlflow-artifacts/` | **~89 KB** | `model.ubj` XGBoost (200 árboles, depth 4) |
| &nbsp;&nbsp;→ store total | | 1.4 MB | 22 modelos históricos + metadata |
| **RDS (servicio)** | PostgreSQL `inference_results` | **444 MB** | 950,927 filas Top-K (con índice) |
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

### Conclusiones sobre costos/computación

1. **El muestreo negativo domina las filas pero no el tamaño:** los 4.6M negativos de train son ~60% de sus filas, pero el Parquet comprime a ~30 B/fila → `processed/` total 418 MB, solo ~1/3 del raw.
2. **El `inference_results` es el mayor costo relacional** (444 MB para 950K filas Top-K), mayor que las matrices de features.
3. **El modelo es despreciable** (~89 KB).
4. **Escalabilidad:** todo el pipeline con datos reales cabe en ~2 GB, cómodo para LocalStack (disco local) y para AWS (S3 y RDS de bajo costo).

---

## 4. Análisis de escalabilidad

### Componentes siempre encendidos (costo fijo 24/7)

Estos son los que el usuario debe dimensionar en términos de costo/consumo continuo:

1. **LocalStack** (`localstack_main`) — la base del entorno emulado. No escala con la carga real; en producción se reemplaza por AWS real.
2. **PostgreSQL** (`taobao_postgres`) — **stateful**, el cuello de botella más probable. `inference_results` llegó a 950,927 filas / 444 MB con datos reales. Escalar requiere: índices adicionales, particionamiento por `user_id`, o cluster PostgreSQL/HA.
3. **MLflow** (`taobao_mlflow`) — stateless (backend en PG, artifacts en S3). Escala horizontalmente con réplicas detrás de un balanceador.
4. **Orquestador Airflow** (`taobao-airflow`, `aws_instance`) — en AWS real ejecuta scheduler + webserver + LocalExecutor; escala verticalmente (`t3.medium`). En LocalStack es simbólico (mock VM).
5. **API** (`uvicorn api/main.py`) — stateless. Escala horizontalmente (el ASG en AWS real lo hace: min 2 / max 4). Depende del pool asyncpg para no saturar PostgreSQL.

### Componentes efímeros (costo por ejecución, no continuo)

- DuckDB (bootstrap/features): picos de memoria durante el batch, libera al terminar.
- XGBoost (training/inference): picos de CPU/RAM. Con datos reales, train = 7.69M filas (~15-30 s); inference = 11.48M candidatos.
- ThreadPoolExecutor (bootstrap): red hacia S3.

### Puntos de escalabilidad clave

| Componente | Modo de escalado | Riesgo |
|------------|------------------|--------|
| PostgreSQL (`inference_results`) | Vertical (más RAM/CPU) o particionado | **Alto** — 444 MB con solo 950K usuarios; escala lineal con usuarios |
| Orquestador Airflow | Vertical (`t3.medium`) o executor distribuido | Medio — CPU/RAM del scheduler + workers |
| MLflow | Horizontal (réplicas) | Bajo — stateless |
| API | Horizontal (ASG min 2 / max 4) | Medio — pool asyncpg a PG |
| S3 (raw/processed) | N/A — elástico por diseño | Bajo — 1.56 GB actual |

### Estimación de crecimiento

Con los datos reales medidos:
- Cada usuario activo genera ~1 fila en `inference_results` (Top-K) → el tamaño crece **lineal** con la base de usuarios.
- `raw/` y `processed/` crecen con el volumen transaccional diario (9 días → 1.56 GB; un año → ~60 GB aprox.).
- El modelo (~89 KB) es despreciable y se regenera por batch.
