# Guía de Despliegue y Operación

Documento de referencia con todos los comandos necesarios para desplegar los servicios y ejecutar los scripts del pipeline de recomendación (Taobao → LocalStack). Las mediciones reales de tiempos y tamaños del pipeline se documentan en [PLANIFICACIÓN_Y_COSTOS.md](PLANIFICACIÓN_Y_COSTOS.md).

## Tabla de contenidos

1. [Orden de despliegue](#1-orden-de-despliegue)
2. [Servicios (Docker Compose)](#2-servicios-docker-compose)
3. [Infraestructura (OpenTofu → LocalStack)](#3-infraestructura-opentofu--localstack)
4. [Scripts de inicialización](#4-scripts-de-inicialización)
5. [Pipeline de datos](#5-pipeline-de-datos)
6. [API de servicio](#6-api-de-servicio)
7. [Detalles técnicos del pipeline](#7-detalles-técnicos-del-pipeline)
8. [Tests](#8-tests)

---

## Tabla resumen de comandos

| Paso | Comando |
|---|---|
| Levantar servicios | `docker compose up -d --build` |
| Estado de servicios | `docker compose ps` | 
| Bajar servicios |  `docker compose down` |
| Infraestructura |  `tofu apply -var="alb_asg_enabled=false"` |
| Inicializar DB |  `uv run python init_db.py` |
| Bootstrap de datos |  `uv run python data_bootstrap.py` |
| Feature store | `uv run python pipeline_features.py` |
| Entrenamiento |  `uv run python pipeline_training.py` |
| Inferencia | `uv run python pipeline_inference.py` |
| API |  `uv run uvicorn api.main:app --port 8000` |
| Tests |  `uv run pytest tests/ -v` |

---

## 1. Orden de despliegue

El flujo completo, en orden de dependencia:

1. **Servicios**: `docker compose up -d --build` (LocalStack + PostgreSQL + MLflow).
2. **Infraestructura**: `tofu init && tofu apply -var="alb_asg_enabled=false"` (bucket, red con NAT/endpoint, SG, IAM, SSM, cómputo orquestador; ALB/ASG gated).
3. **Inicialización DB**: `uv run python init_db.py` (tabla `inference_results`).
4. **Orquestación (producción)**: el DAG `taobao_dag.py` en Airflow ejecuta los pasos 5-8 vía `BashOperator` (inyectando el contexto `env_vars`). En local se ejecutan manualmente:
5. **Bootstrap de datos**: `uv run python data_bootstrap.py` (CSV → Parquet en S3 `raw/`).
6. **Feature store**: `uv run python pipeline_features.py` (raw → matrices en `processed/`).
7. **Entrenamiento**: `uv run python pipeline_training.py` (XGBoost → MLflow).
8. **Inferencia**: `uv run python pipeline_inference.py` (modelo → Top-K en PostgreSQL).
9. **API**: `uv run uvicorn api.main:app --port 8000` (sirve las recomendaciones).

---

## 2. Servicios (Docker Compose)

### `docker compose up -d --build`

- **Input:** `docker-compose.yml` (define `localstack`, `postgres`, `mlflow-db-init`, `mlflow`).
- **Output:** 4 contenedores:
  - `localstack_main` — emulador AWS (puerto `4566`), con `PERSISTENCE=1`.
  - `taobao_postgres` — sidecar PostgreSQL 15 (puerto `5432`), credenciales `taobao`/`taobao123`, base `taobao`.
  - `taobao_mlflow_db_init` — one-shot que crea la base `mlflow` (ejecuta `init_mlflow_db.py`).
  - `taobao_mlflow` — servidor MLflow (puerto `5000`), backend store en PostgreSQL (base `mlflow`), artifact store en `s3://taobao-mlflow-artifacts` (LocalStack).
- **Racional:** levanta la infraestructura emulada (AWS) y los motores reales (PostgreSQL) que los scripts consumen. El build inicial compila la imagen MLflow custom (`docker/mlflow/Dockerfile`).

### `docker compose ps`

- **Input:** ninguno.
- **Output:** estado de los contenedores (Up/healthy, puertos).
- **Racional:** verifica que los servicios estén operativos antes de correr los pipelines.

### `docker compose down`

- **Input:** ninguno.
- **Output:** detiene y elimina los contenedores de la red `taobao_default`.
- **Racional:** apaga el entorno. Nota: los volúmenes `localstack-data/` y `postgres-data/` persisten (no se borran con `down`).

### `docker compose down -v`

- **Input:** ninguno.
- **Output:** elimina contenedores **y volúmenes** (pierde el estado de LocalStack y PostgreSQL).
- **Racional:** reset total del entorno. Requiere re-correr `tofu apply` e `init_db.py` después.

---

## 3. Infraestructura (OpenTofu → LocalStack)

### `tofu init`

- **Input:** los archivos `.tf` en `terraform/` (módulos `networking`, `security_groups`, `iam`, `s3`, `rds`, `alb_asg`).
- **Output:** `.terraform/` y `.terraform.lock.hcl` (provider `hashicorp/aws` descargado).
- **Racional:** descarga el provider y prepara el estado local.

### `tofu validate`

- **Input:** la configuración HCL.
- **Output:** `Success! The configuration is valid.`
- **Racional:** verificación estática de sintaxis y tipos, sin contacto con LocalStack.

### `tofu apply -auto-approve`

- **Input:** la configuración + `TF_VAR_localstack_endpoint` (endpoint por defecto: `http://localhost:4566`).
- **Output:** crea los recursos en LocalStack:
  - 1 VPC, 1 IGW, 1 EIP, 1 NAT Gateway, 1 VPC Endpoint S3, 4 subredes (2 públicas + 2 privadas), 2 route tables + asociaciones, ruta pública → IGW, ruta privada → NAT + endpoint S3.
  - 4 Security Groups (`sg_alb`, `sg_api_ec2`, `sg_airflow`, `sg_rds`).
  - Rol IAM `taobao-batch-role` + policy S3 + policy SSM + instance profile + SSM Parameter `/taobao/prod/rds_password`.
  - Buckets `taobao-datalake`, `taobao-mlflow-artifacts` y `taobao-airflow-dags` (con bloqueo de acceso público).
  - Instancia EC2 `taobao-airflow` (orquestador, mock VM) con `user_data` desde `init_airflow.sh.tpl`.
  - Imprime los outputs (IDs, ARNs).
- **Racional:** materializa la "Landing Zone" + cómputo orquestado en el emulador. Idempotente (re-aplicar no duplica).

### Recursos gated (`rds_enabled`, `alb_asg_enabled`)

LocalStack **community** no implementa los servicios RDS, ELBv2 y Auto Scaling (features Pro). Por eso los módulos `rds` y `alb_asg` están **gated**:

- `alb_asg_enabled` tiene default declarativo `true` (IaC para AWS real), pero en LocalStack se aplica con **`-var alb_asg_enabled=false`** — sin el override, `tofu apply` intenta crear `aws_lb` (ELBv2) y falla en community.
- `rds_enabled` mantiene default `false`; el motor real es el sidecar `postgres:15`.
- Para AWS real: `tofu apply -var="rds_enabled=true" -var="alb_asg_enabled=true"` (crea la instancia RDS, el ALB público, target group, launch template y Auto Scaling Group en subredes privadas).

### `tofu destroy`

- **Input:** la configuración.
- **Output:** elimina los recursos de LocalStack.
- **Racional:** derriba la infraestructura emulada (no afecta los contenedores).

---

## 4. Scripts de inicialización

### `uv run python init_db.py`

- **Input (env):**
  | Variable | Default |
  |---|---|
  | `PGHOST` | `localhost` |
  | `PGPORT` | `5432` |
  | `PGUSER` | `taobao` |
  | `PGPASSWORD` | `taobao123` |
  | `PGDATABASE` | `taobao` |
- **Output:** crea la tabla `inference_results` (si no existe):
  ```sql
  CREATE TABLE IF NOT EXISTS inference_results (
      user_id BIGINT PRIMARY KEY,
      recommended_items JSONB NOT NULL,
      updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
  )
  ```
- **Racional:** inicializa el esquema relacional del almacén de inferencias que la API consultará. Es **idempotente** (re-ejecución segura).

### `uv run python init_mlflow_db.py`

- **Input (env):** igual que `init_db.py` + `MLFLOW_DB` (default `mlflow`).
- **Output:** crea la base de datos `mlflow` en el sidecar PostgreSQL (si no existe).
- **Racional:** MLflow necesita una base dedicada para su backend store (tablas de experiments/runs/metrics). Se ejecuta automáticamente como servicio one-shot (`mlflow-db-init`) en `docker compose up`, pero puede correrse manualmente.

---

## 5. Pipeline de datos

### Origen del dataset

El dataset crudo (`UserBehavior.csv`, sin header, ~100M filas) se descarga de Kaggle:

```
https://www.kaggle.com/datasets/marwa80/userbehavior/data
```

Debe alojarse en `data/raw/UserBehavior.csv` para que `data_bootstrap.py` lo encuentre por defecto. Descarga alternativa vía CLI de Kaggle:

```bash
kaggle datasets download -d marwa80/userbehavior -p data/raw --unzip
```

### `uv run python data_bootstrap.py`

- **Input (env):**
  | Variable | Default | Descripción |
  |---|---|---|
  | `RAW_CSV` | `data/raw/UserBehavior.csv` | CSV crudo (sin header, ~100M filas) |
  | `PARQUET_DIR` | `data/processed/parquet` | Directorio local de Parquet |
  | `DB_PATH` | `data/tmp/bootstrap.duckdb` | DuckDB temporal |
  | `LOCALSTACK_ENDPOINT` | **obligatoria** (sin default) | Endpoint LocalStack |
  | `BUCKET` | `taobao-datalake` | Bucket destino |
- **Output:** particiones Hive en `s3://taobao-datalake/raw/event_date=YYYY-MM-DD/*.parquet`. Imprime:
  ```
  Usuarios calificados: N | Parquet: M | Subidas a s3://taobao-datalake/raw/: M
  ```
- **Racional:** ingesta del dataset: filtra usuarios con <10 interacciones, deriva `event_date` en `Asia/Shanghai` (UTC+8), filtra timestamps fuera del rango legítimo (25 nov – 3 dic 2017 CST) y sube Parquet particionado con `ThreadPoolExecutor`. DuckDB procesa el CSV de 3.7 GB sin OOM.
- **Uso rápido (fixture):**
  ```bash
  RAW_CSV=tests/fixtures/features_9day.csv uv run python data_bootstrap.py
  ```

### `uv run python pipeline_features.py`

- **Input (env):**
  | Variable | Default |
  |---|---|
  | `BUCKET` | `taobao-datalake` |
  | `RAW_PREFIX` | `raw` |
  | `PROCESSED_PREFIX` | `processed` |
  | `EPSILON` | `1e-6` |
  | `NEG_RATIO` | `4` |
  | `TOP_POPULAR` | `20` |
  | `LOCALSTACK_ENDPOINT` | **obligatoria** (sin default) |
- **Output:** matrices en `s3://taobao-datalake/processed/split={train|val|test|infer}/` con las features y el label. Imprime:
  ```
  train_pos=N train_neg=N val=N test=N infer=N
  ```
- **Racional:** construye el feature store con **segregación temporal estricta** (burn-in 1-3, train 4-6, val 7, test 8, infer 9) para evitar data leakage. Computa features con datos ≤ T-1 (frecuencias, `intent_score` con ε, target encoding con Laplace, popularidades, lag operators) y genera muestreo negativo cruzando usuarios con ítems populares no interactuados.

### `uv run python pipeline_training.py`

- **Input (env):**
  | Variable | Default |
  |---|---|
  | `BUCKET` | `taobao-datalake` |
  | `PROCESSED_PREFIX` | `processed` |
  | `LOCALSTACK_ENDPOINT` | **obligatoria** (sin default) |
  | `MLFLOW_TRACKING_URI` | **obligatoria** (sin default) |
- **Output:** un run `FINISHED` en el experimento `taobao_recommender` de MLflow con el modelo XGBoost, hiperparámetros y 6 métricas de test. Imprime:
  ```
  run_id=... test_auc_roc=... test_logloss=... test_precision=... test_recall=... test_f1=... test_accuracy=...
  ```
- **Racional:** lee train/val/test de S3 (no lee infer), entrena `XGBClassifier` con early stopping sobre validación (día 7), evalúa en test (día 8) con AUC-ROC, LogLoss, precision, recall, f1 y accuracy (umbral 0.5), y registra el ciclo de vida con `mlflow.xgboost.autolog` + `log_model`. El modelo queda disponible para inferencia.

### `uv run python pipeline_inference.py`

- **Input (env):**
  | Variable | Default |
  |---|---|
  | `BUCKET` | `taobao-datalake` |
  | `PROCESSED_PREFIX` | `processed` |
  | `LOCALSTACK_ENDPOINT` | **obligatoria** (sin default) |
  | `MLFLOW_TRACKING_URI` | **obligatoria** (sin default) |
  | `TOP_K` | `10` |
  | `PGHOST`/`PGPORT` | **obligatorias** (sin default) |
  | `PGUSER`/`PGPASSWORD`/`PGDATABASE` | **obligatorias** (sin default) |
- **Output:** filas en `inference_results` con el Top-K por usuario (`recommended_items` como lista JSONB de `{"item_id", "score"}`). Imprime:
  ```
  run_id=... usuarios=N filas_persistidas=N
  ```
- **Racional:** carga el último modelo `FINISHED` de MLflow (`runs:/{run_id}/model`), predice sobre el tensor del día 9 (`split=infer`), arma el ranking Top-K por usuario y persiste con un **upsert** (`ON CONFLICT (user_id) DO UPDATE`) vía `psycopg2.extras.execute_values`. Es el motor asíncrono que alimenta la API. No mide métricas de clasificación: el label del día 9 es `NULL` (simulación de producción sin ground truth).

---

## 6. API de servicio

### `uv run uvicorn api.main:app --host 0.0.0.0 --port 8000`

- **Input (env):**
  | Variable | Default |
  |---|---|
  | `PGHOST` | `localhost` |
  | `PGPORT` | `5432` |
  | `PGUSER` | `taobao` |
  | `PGPASSWORD` | `taobao123` |
  | `PGDATABASE` | `taobao` |
- **Output:** servidor HTTP FastAPI en el puerto `8000` con un pool asíncrono `asyncpg` a PostgreSQL.
- **Racional:** expone la capa de servicio. Internamente valida la respuesta con Pydantic (`RecommendationResponse` → `List[RecommendationItem]` con `item_id: int`, `score: float`).

### `GET /recommendations/{user_id}`

- **Input (URL):** `user_id` entero.
- **Output:**
  - **200** con el esquema estricto:
    ```json
    {"user_id": 1, "recommended_items": [{"item_id": 101, "score": 0.87}]}
    ```
  - **404** si el usuario no existe en `inference_results`.
- **Racional:** consulta la clave primaria `user_id` (latencia $O(1)$) y devuelve el Top-K precomputado.

### Probar la API

```bash
curl http://localhost:8000/recommendations/1
curl -i http://localhost:8000/recommendations/99999   # espera 404
```

### Contenedor

```bash
docker build -f api/Dockerfile -t taobao-api .
```

- **Input:** `api/Dockerfile` (multietapa: `uv sync` en build, `uvicorn` en runtime).
- **Output:** imagen `taobao-api` lista para correr en EC2 (via `aws_launch_template`/`aws_autoscaling_group` en AWS real).
- **Racional:** empaqueta la aplicación para el despliegue en la capa de servicio.

---

## 7. Detalles técnicos del pipeline

Detalle de las decisiones de implementación de cada etapa (consolidado de la documentación previa).

### Split temporal (anti-leakage)

El día se asigna por `DENSE_RANK` sobre `event_date` ordenado (día 1 = más antiguo):

| Conjunto | Días | Uso |
|----------|------|-----|
| Burn-in | 1-3 | Acumulación histórica (features) |
| Train | 4-6 | Matriz de entrenamiento (+ negativos) |
| Val | 7 | Validación (+ negativos) |
| Test | 8 | Hold-out (+ negativos) |
| Infer | 9 | Simulación de producción (sin label) |

### Features (toda métrica en T usa datos ≤ T-1)

Computadas con ventanas `ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING` (excluye el día actual), garantizando ausencia de leakage:

- `user_item_freq` — frecuencia absoluta usuario-ítem histórica.
- `user_cat_freq`, `user_cat_eng` — frecuencia e interacciones de engagement (buy/cart/fav) por categoría.
- `intent_score` — `(eng + ε) / (freq + ε)` con factor infinitesimal `ε` (default `1e-6`).
- `item_popularity`, `cat_popularity` — popularidad global histórica.
- `cat_target_enc` — _target encoding_ por categoría con suavizado de Laplace `(pos_past + 1) / (total_past + 2)`.
- `lag_1`, `lag_2` — _lag operators_ de la serie diaria usuario-categoría.

### Muestreo negativo

Para train/val/test se cruzan los usuarios con los `TOP_POPULAR` ítems (default 20) con los que **no** interactuaron en el día, generando `label=0`. Ratio `NEG_RATIO` (default 4) negativos por (usuario, día). El target positivo es `behavior_type IN (buy, cart, fav)`.

### Modelado XGBoost

- `XGBClassifier(n_estimators=200, max_depth=4, learning_rate=0.1, eval_metric="logloss", early_stopping_rounds=10)`.
- `eval_set=[(X_val, y_val)]` — early stopping y monitoreo de pérdida sobre el día 7.
- Features (9): `user_item_freq, user_cat_freq, user_cat_eng, intent_score, item_popularity, cat_popularity, cat_target_enc, lag_1, lag_2`. Target: `label`.
- Evaluación offline (día 8): 6 métricas `test_*` — `test_auc_roc`, `test_logloss`, `test_precision`, `test_recall`, `test_f1`, `test_accuracy` (sobre `y_pred = (y_prob >= 0.5)`, umbral fijo, `zero_division=0`).
- En `pipeline_inference.py` (día 9) **no** se miden métricas de clasificación: el label del tensor de inferencia es `NULL` (simulación de producción sin ground truth).

### Gobernanza MLflow

- Tracking URI: env `MLFLOW_TRACKING_URI` (inyectado por Airflow; en local se exporta explícitamente, sin fallback `localhost`).
- Experimento: `taobao_recommender`.
- `mlflow.xgboost.autolog(log_models=True)` registra topología, hiperparámetros y métricas; además se hace `mlflow.xgboost.log_model(model, "model")` explícito.
- Backend store: `postgresql+psycopg2://taobao:taobao123@taobao_postgres:5432/mlflow`.
- Artifact store: `s3://taobao-mlflow-artifacts` (vía `MLFLOW_S3_ENDPOINT_URL` apuntando a LocalStack).

### Capa de servicio (ALB + ASG)

El módulo `terraform/modules/alb_asg` define:

- `aws_lb` (ALB público, `sg_alb`, subredes públicas).
- `aws_lb_target_group` (HTTP 8000, health check `/health`).
- `aws_lb_listener` (80 → target group).
- `aws_launch_template` (`user_data = templatefile("init_api.sh.tpl", ...)`, IAM profile batch, subredes privadas).
- `aws_autoscaling_group` (subredes privadas, min 2 / max 4).

**LocalStack community no implementa ELBv2 ni Auto Scaling** (features Pro). El módulo está **gated**: default `alb_asg_enabled=true` (IaC AWS real) pero en LocalStack se aplica con `-var="alb_asg_enabled=false"`.

### Orquestación (Airflow DAG)

El DAG `taobao_dag.py` (raíz) sustituye la ejecución manual:

- `BashOperator` invocando `uv run python <script.py>` para `data_bootstrap`, `pipeline_features`, `pipeline_training`, `pipeline_inference`.
- Diccionario `env` inyectando el contexto: `BUCKET`, `MLFLOW_TRACKING_URI`, `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, `PGDATABASE`, `LOCALSTACK_ENDPOINT` (mapeados desde Airflow Variables `{{ var.value.* }}`).
- Topología declarada: `t_bootstrap >> t_features >> t_training >> t_inference`.
- Schedule diario (`timedelta(days=1)`), `catchup=False`, `start_date=datetime(2026, 1, 1)`.
- En la instancia orquestadora (`init_airflow.sh.tpl`), el bucket `taobao-airflow-dags` se sincroniza a `/opt/airflow/dags/` (cron cada 5 min) y el contenedor `apache/airflow:2.9.0` (LocalExecutor) lo ejecuta.
- En LocalStack la instancia orquestadora es simbólica (mock VM que no procesa `user_data`); la verificación local de la orquestación se hace con `docker-compose.airflow.yml` + `.airflowignore`.

---

## 8. Tests

Todos los tests son de integración (marcador `integration`) y requieren LocalStack + infraestructura aplicada.

| Comando | Alcance |
|---|---|
| `uv run pytest tests/ -v` | Suite completa |
| `uv run pytest tests/test_vpc.py` | Red (VPC, subredes, IGW, route tables) |
| `uv run pytest tests/test_security_groups.py` | Security Groups (lista blanca) |
| `uv run pytest tests/test_iam.py` | IAM (rol, policy S3, instance profile) |
| `uv run pytest tests/test_s3_bucket.py` | Bucket `taobao-datalake` + bloqueo público |
| `uv run pytest tests/test_bootstrap.py` | Bootstrap (filtrado, particiones, timestamps) |
| `uv run pytest tests/test_rds.py` | RDS (gated: metadata se salta) + esquema `inference_results` |
| `uv run pytest tests/test_mlflow.py` | MLflow (health, experimento, artefacto) |
| `uv run pytest tests/test_features.py` | Feature store (splits, disyunción temporal) |
| `uv run pytest tests/test_training.py` | Training (run, 6 métricas, artefacto xgboost) |
| `uv run pytest tests/test_inference.py` | Inferencia (Top-K persistido, upsert) |
| `uv run pytest tests/test_compute.py` | Cómputo (instancia orquestadora Airflow) |
| `uv run pytest tests/test_asg.py` | ASG/Launch Template (skipea en LocalStack community) |
| `uv run pytest tests/test_api.py` | API (200/404, esquema) |

**Prerrequisito para los tests:** LocalStack corriendo (`docker compose up -d`) e infraestructura aplicada (`tofu apply`). El endpoint se resuelve automáticamente (env `LOCALSTACK_ENDPOINT` o fallback `localhost:4566`).

---

