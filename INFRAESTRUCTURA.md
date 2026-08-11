# Infraestructura del Pipeline — Inventario de Servicios

Documento de referencia para análisis de escalabilidad. Detalla todos los componentes de infraestructura que se instancian a lo largo del pipeline de recomendación (Taobao → LocalStack), distinguiendo cuáles **permanecen encendidos de forma continua** de los que son **efímeros** (se instancian por etapa y terminan).

## Resumen ejecutivo

| Tipo | ¿Encendido continuo? | Componentes |
|------|----------------------|-------------|
| Contenedores Docker | **Sí** | LocalStack, PostgreSQL, MLflow |
| Recursos IaC (S3/red/IAM) | **Sí** (persistentes) | Buckets, VPC, subredes, SG, IAM |
| Recursos IaC gated (RDS/ALB/ASG) | **No materializados en LocalStack** | Definidos para AWS real |
| Scripts Python | **No** (efímeros) | bootstrap, features, training, inference |
| Procesos dentro de scripts | **No** (efímeros) | DuckDB, pool de conexiones |

---

## 1. Contenedores Docker (siempre encendidos)

Definidos en `docker-compose.yml`. Se levantan con `docker compose up -d --build` y **permanecen corriendo continuamente**.

| Contenedor | Imagen | Puerto | Rol | ¿Continuo? |
|------------|--------|--------|-----|------------|
| `localstack_main` | `localstack/localstack:3.5.0` | `4566` | Emulador AWS (S3, EC2, IAM, etc.) | **Sí** |
| `taobao_postgres` | `postgres:15` | `5432` | Sidecar PostgreSQL (bases `taobao` + `mlflow`) | **Sí** |
| `taobao_mlflow` | custom (`docker/mlflow/Dockerfile`) | `5000` | Servidor MLflow (UI + API) | **Sí** |
| `taobao_mlflow_db_init` | custom | — | One-shot: crea la base `mlflow` | **No** (termina tras crear la DB) |

**Nota de escalabilidad:** los 3 contenedores "siempre encendidos" son el piso fijo de consumo. `localstack_main` y `taobao_mlflow` son stateless (pueden escalar horizontalmente con réplicas de Docker Compose o un orquestador); `taobao_postgres` es stateful (su escalado requiere clustering PostgreSQL/HA, no réplicas simples).

---

## 2. Recursos IaC materializados en LocalStack (persistentes)

Creados por `tofu apply` (módulos de `terraform/`). Persisten mientras exista el contenedor `localstack_main` con `PERSISTENCE=1`.

### 2.1 Capa de almacenamiento (S3) — módulo `s3`

| Recurso | Nombre | Persistente |
|---------|--------|-------------|
| Bucket | `taobao-datalake` | Sí — almacén de datos raw (`raw/`) y procesados (`processed/`) |
| Public Access Block | `taobao-datalake` | Sí |
| Bucket | `taobao-mlflow-artifacts` | Sí — artifact store de MLflow |
| Public Access Block | `taobao-mlflow-artifacts` | Sí |
| Bucket | `taobao-airflow-dags` | Sí — repo de DAGs y scripts sincronizado por el orquestador Airflow |
| Public Access Block | `taobao-airflow-dags` | Sí |

### 2.2 Capa de red — módulo `networking`

| Recurso | Cantidad | Detalle |
|---------|----------|---------|
| VPC | 1 | `taobao-vpc` (`10.0.0.0/16`, DNS habilitado) |
| Internet Gateway | 1 | `taobao-igw` |
| Elastic IP | 1 | `taobao-nat-eip` |
| NAT Gateway | 1 | `taobao-nat` (subred pública, salida a internet para privadas) |
| VPC Endpoint S3 | 1 | Gateway (`com.amazonaws.us-east-1.s3`) sobre la RT privada |
| Subred pública | 2 | `us-east-1a` (`10.0.1.0/24`), `us-east-1b` (`10.0.2.0/24`) |
| Subred privada | 2 | `us-east-1a` (`10.0.10.0/24`), `us-east-1b` (`10.0.11.0/24`) |
| Route Table pública | 1 | `taobao-pub-rt` (0.0.0.0/0 → IGW) |
| Route Table privada | 1 | `taobao-priv-rt` (0.0.0.0/0 → NAT + endpoint S3) |
| Asociaciones de subred | 4 | 2 públicas + 2 privadas |

### 2.3 Seguridad — módulo `security_groups`

| Recurso | Reglas | Persistente |
|---------|--------|-------------|
| `sg_alb` | Ingress 80 desde `0.0.0.0/0` | Sí |
| `sg_api_ec2` | Ingress 8000 solo desde `sg_alb` | Sí |
| `sg_airflow` (ex `sg_batch_ec2`) | Ingress interno 8080 y 5000 desde `vpc_cidr`; egress total | Sí |
| `sg_rds` | Ingress 5432 solo desde `sg_airflow` + `sg_api_ec2` | Sí |

### 2.4 Identidad — módulo `iam`

| Recurso | Nombre | Persistente |
|---------|--------|-------------|
| Rol IAM | `taobao-batch-role` (trust EC2) | Sí |
| Policy | `taobao-s3-rw-policy` (S3 RW sobre los 3 buckets) | Sí |
| Policy | `taobao-ssm-read-policy` (`ssm:GetParameter` + `kms:Decrypt`) | Sí |
| Attachment | rol ↔ policy S3 | Sí |
| Attachment | rol ↔ policy SSM | Sí |
| Instance Profile | `taobao-batch-instance-profile` | Sí |
| SSM Parameter | `/taobao/prod/rds_password` (`SecureString`) | Sí |

### 2.5 Cómputo — módulo `compute`

| Recurso | Nombre | Persistente |
|---------|--------|-------------|
| Instancia EC2 | `taobao-airflow` (`t3.medium`, subred privada, `sg_airflow`, profile batch) | Sí — simbólica en LocalStack (mock VM), `user_data` = `init_airflow.sh.tpl` |

---

## 3. Recursos IaC gated — definidos, NO materializados en LocalStack

LocalStack **community** no implementa los servicios RDS, ELBv2 ni Auto Scaling (features Pro). Los módulos existen y son correctos para AWS real, pero **no se crean** en LocalStack salvo que se aplique sin override.

> El default declarativo de `alb_asg_enabled` es `true` (IaC para AWS real). En LocalStack el apply se corre con **`-var alb_asg_enabled=false`** porque `aws_lb` (ELBv2) falla en community. El módulo `rds` mantiene `rds_enabled=false` por defecto.

| Módulo | Recurso | Flag | ¿Materializado en LocalStack? | ¿Continuo en AWS real? |
|--------|---------|------|------------------------------|------------------------|
| `rds` | `aws_db_subnet_group` | `rds_enabled` | No | Sí |
| `rds` | `aws_db_instance` (PostgreSQL 15, `db.t3.micro`) | `rds_enabled` | No | **Sí** (24/7) |
| `alb_asg` | `aws_lb` (ALB público) | `alb_asg_enabled` | No | **Sí** (24/7) |
| `alb_asg` | `aws_lb_target_group` | `alb_asg_enabled` | No | Sí |
| `alb_asg` | `aws_lb_listener` | `alb_asg_enabled` | No | Sí |
| `alb_asg` | `aws_launch_template` (user_data = `templatefile` de `init_api.sh.tpl`, IAM profile batch) | `alb_asg_enabled` | No | Sí |
| `alb_asg` | `aws_autoscaling_group` (subredes privadas, min 2 / max 4) | `alb_asg_enabled` | No | **Sí** (escala según demanda) |

> **En LocalStack**, el motor real de la base es el contenedor `taobao_postgres` (no el `aws_db_instance`). La API se sirve localmente vía `uvicorn`/`TestClient` (no vía ALB). Estos recursos "gated" son el puente declarativo para un despliegue real en AWS.

---

## 4. Scripts del pipeline (efímeros — se instancian y terminan)

Ejecutados con `uv run python <script>` desde WSL. **No permanecen corriendo**; instancian procesos temporales que terminan al finalizar.

| Script | Etapa | Servicios que toca | Procesos temporales | Persistente después? |
|--------|-------|--------------------|---------------------|----------------------|
| `init_db.py` | Inicialización DB | PostgreSQL (`taobao`) | Conexión `psycopg2` | Sí — crea tabla `inference_results` |
| `init_mlflow_db.py` | Inicialización DB | PostgreSQL (`taobao`) | Conexión `psycopg2` | Sí — crea base `mlflow` |
| `data_bootstrap.py` | Ingesta | LocalStack S3 (`taobao-datalake/raw/`) | Motor DuckDB + pool `ThreadPoolExecutor` (boto3) | Sí — parquets raw |
| `pipeline_features.py` | Feature store | LocalStack S3 (`raw/` → `processed/`) | Motor DuckDB (`httpfs`) | Sí — matrices procesadas |
| `pipeline_training.py` | Modelado | S3 (`processed/`) + MLflow (`:5000`) + S3 (`mlflow-artifacts`) | XGBoost, cliente MLflow | Sí — run + modelo en MLflow |
| `pipeline_inference.py` | Inferencia | MLflow (carga modelo) + S3 (`processed/`) + PostgreSQL (`inference_results`) | XGBoost, `psycopg2` | Sí — filas Top-K en RDS |
| `taobao_dag.py` | Orquestación | Orquesta los 4 scripts vía Airflow (`BashOperator` + `env_vars`) | Airflow DAG (scheduler) | Sí — DAG activo en Airflow |
| `api/main.py` | Servicio | PostgreSQL (`inference_results`) | **uvicorn + asyncpg pool** | **Sí — servidor HTTP continuo** |

### Componentes efímeros dentro de los scripts

| Proceso | Dónde | Vida útil | Consumo notable |
|---------|-------|-----------|-----------------|
| Motor DuckDB | bootstrap / features | Solo la etapa | Memoria durante el procesamiento |
| ThreadPoolExecutor (boto3) | bootstrap | Solo la subida | Red hacia LocalStack |
| Modelo XGBoost en memoria | training / inference | Solo la ejecución | CPU/RAM durante fit y predict |
| Pool asyncpg | API | **Toda la vida del servidor** | Conexiones persistentes a PostgreSQL |

---

## 5. Matriz de servicios por etapa (qué instancia cada etapa)

| Etapa | Docker (continuo) | S3 buckets | PostgreSQL | MLflow | Procesos efímeros |
|-------|-------------------|-----------|------------|--------|-------------------|
| Arranque (`compose up`) | localstack, postgres, mlflow, mlflow-db-init | — | crea `mlflow` | arranca | mlflow-db-init |
| `tofu apply` | localstack | crea 2 buckets, red, SG, IAM | — | — | — |
| `init_db.py` | postgres | — | crea `inference_results` | — | conexión psycopg2 |
| `data_bootstrap.py` | localstack | escribe `raw/` | — | — | DuckDB + threads |
| `pipeline_features.py` | localstack | `raw/` → `processed/` | — | — | DuckDB |
| `pipeline_training.py` | localstack + mlflow | lee `processed/`, escribe `mlflow-artifacts` | — | registra run | XGBoost |
| `pipeline_inference.py` | localstack + mlflow + postgres | lee `processed/`, `mlflow-artifacts` | escribe `inference_results` | carga modelo | XGBoost + psycopg2 |
| `taobao_dag.py` (Airflow) | orquestador EC2 + localstack + mlflow + postgres | lee/escribe buckets | escribe `inference_results` | registra run | ejecuta bootstrap → features → training → inference |
| `uvicorn api` | postgres | — | lee `inference_results` | — | asyncpg pool (continuo) |

---

## 6. Análisis de escalabilidad

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

---

## 7. Comandos de referencia rápida

| Acción | Comando |
|--------|---------|
| Ver servicios continuos | `docker compose ps` |
| Ver recursos materializados | `tofu output` (en `terraform/`) |
| Ver buckets en LocalStack | `aws --endpoint-url=http://localhost:4566 s3 ls` (o boto3) |
| Ver estado de `inference_results` | consulta SQL a `taobao_postgres` |
| Ver runs/modelos en MLflow | UI en `http://localhost:5000` |
| Activar RDS/ALB/ASG (AWS real) | `tofu apply -var="rds_enabled=true" -var="alb_asg_enabled=true"` |
| Apply en LocalStack (ALB/ASG gated) | `tofu apply -var="alb_asg_enabled=false"` |
