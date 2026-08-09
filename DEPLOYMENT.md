# Guía de Despliegue y Operación

Documento de referencia con todos los comandos necesarios para desplegar los servicios y ejecutar los scripts del pipeline de recomendación (Taobao → LocalStack).

## Tabla de contenidos

1. [Consideraciones de entorno](#1-consideraciones-de-entorno)
2. [Orden de despliegue](#2-orden-de-despliegue)
3. [Servicios (Docker Compose)](#3-servicios-docker-compose)
4. [Infraestructura (OpenTofu → LocalStack)](#4-infraestructura-opentofu--localstack)
5. [Scripts de inicialización](#5-scripts-de-inicialización)
6. [Pipeline de datos](#6-pipeline-de-datos)
7. [API de servicio](#7-api-de-servicio)
8. [Detalles técnicos del pipeline](#8-detalles-técnicos-del-pipeline)
9. [Tests](#9-tests)
10. [Tabla resumen de comandos](#10-tabla-resumen-de-comandos)
11. [Mediciones reales del pipeline](#11-mediciones-reales-del-pipeline)

---

## 1. Consideraciones de entorno

El repositorio vive en **WSL2 (Ubuntu)** pero el shell de trabajo es **PowerShell de Windows**. Esto divide el toolchain:

| Herramienta | Dónde corre | Forma de invocación |
|---|---|---|
| `uv` / Python / pytest | WSL | `wsl -d Ubuntu -- bash -lc '...'` |
| OpenTofu (`tofu`) | WSL | `wsl -d Ubuntu -- tofu ...` |
| `docker` / `docker compose` | Windows | directo desde PowerShell |
| `git` | WSL | `wsl -d Ubuntu -- bash -lc '...'` |

El `.venv` es de Linux (Python 3.12). **No** ejecutar `uv` desde Windows.

**Endpoint de LocalStack desde WSL:** los scripts y `tofu` (corren en WSL) alcanzan LocalStack (contenedor en Windows) vía la IP del gateway WSL:

```bash
GW=$(ip route show default | awk '{print $3}')
export LOCALSTACK_ENDPOINT="http://${GW}:4566"
```

Los tests (`tests/conftest.py`) detectan el gateway automáticamente.

---

## 2. Orden de despliegue

El flujo completo, en orden de dependencia:

1. **Servicios**: `docker compose up -d --build` (LocalStack + PostgreSQL + MLflow).
2. **Infraestructura**: `tofu init && tofu apply` (bucket, red, SG, IAM, RDS gated, ALB/ASG gated).
3. **Inicialización DB**: `uv run python init_db.py` (tabla `inference_results`).
4. **Bootstrap de datos**: `uv run python data_bootstrap.py` (CSV → Parquet en S3 `raw/`).
5. **Feature store**: `uv run python pipeline_features.py` (raw → matrices en `processed/`).
6. **Entrenamiento**: `uv run python pipeline_training.py` (XGBoost → MLflow).
7. **Inferencia**: `uv run python pipeline_inference.py` (modelo → Top-K en PostgreSQL).
8. **API**: `uv run uvicorn api.main:app --port 8000` (sirve las recomendaciones).

---

## 3. Servicios (Docker Compose)

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

## 4. Infraestructura (OpenTofu → LocalStack)

### `tofu init`

- **Input:** los archivos `.tf` en `terraform/` (módulos `networking`, `security_groups`, `iam`, `s3`, `rds`, `alb_asg`).
- **Output:** `.terraform/` y `.terraform.lock.hcl` (provider `hashicorp/aws` descargado).
- **Racional:** descarga el provider y prepara el estado local.

### `tofu validate`

- **Input:** la configuración HCL.
- **Output:** `Success! The configuration is valid.`
- **Racional:** verificación estática de sintaxis y tipos, sin contacto con LocalStack.

### `tofu apply -auto-approve`

- **Input:** la configuración + `TF_VAR_localstack_endpoint` (ver sección 1). Endpoint por defecto: `http://localhost:4566`.
- **Output:** crea los recursos en LocalStack:
  - 1 VPC, 1 IGW, 4 subredes (2 públicas + 2 privadas), 2 route tables + asociaciones, 1 ruta pública → IGW.
  - 4 Security Groups (`sg_alb`, `sg_api_ec2`, `sg_batch_ec2`, `sg_rds`).
  - Rol IAM `taobao-batch-role` + policy S3 + instance profile.
  - Buckets `taobao-datalake` y `taobao-mlflow-artifacts` (con bloqueo de acceso público).
  - Imprime los outputs (IDs, ARNs).
- **Racional:** materializa la "Landing Zone" en el emulador. Idempotente (re-aplicar no duplica).

### Recursos gated (`rds_enabled`, `alb_asg_enabled`)

LocalStack **community** no implementa los servicios RDS, ELBv2 y Auto Scaling (features Pro). Por eso los módulos `rds` y `alb_asg` están **gated**:

- Por defecto (`false`): `tofu apply` converge sin crear esos recursos (válido para LocalStack).
- Para AWS real: `tofu apply -var="rds_enabled=true" -var="alb_asg_enabled=true"` (crea la instancia RDS, el ALB público, target group, launch template y Auto Scaling Group en subredes privadas).

### `tofu destroy`

- **Input:** la configuración.
- **Output:** elimina los recursos de LocalStack.
- **Racional:** derriba la infraestructura emulada (no afecta los contenedores).

---

## 5. Scripts de inicialización

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

## 6. Pipeline de datos

### `uv run python data_bootstrap.py`

- **Input (env):**
  | Variable | Default | Descripción |
  |---|---|---|
  | `RAW_CSV` | `data/raw/UserBehavior.csv` | CSV crudo (sin header, ~100M filas) |
  | `PARQUET_DIR` | `data/processed/parquet` | Directorio local de Parquet |
  | `DB_PATH` | `data/tmp/bootstrap.duckdb` | DuckDB temporal |
  | `LOCALSTACK_ENDPOINT` | `http://localhost:4566` | Endpoint LocalStack |
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
  | `LOCALSTACK_ENDPOINT` | `http://localhost:4566` |
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
  | `LOCALSTACK_ENDPOINT` | `http://localhost:4566` |
  | `MLFLOW_TRACKING_URI` | `http://localhost:5000` |
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
  | `LOCALSTACK_ENDPOINT` | `http://localhost:4566` |
  | `MLFLOW_TRACKING_URI` | `http://localhost:5000` |
  | `TOP_K` | `10` |
  | `PGHOST`/`PGPORT` | `localhost`/`5432` |
  | `PGUSER`/`PGPASSWORD`/`PGDATABASE` | `taobao`/`taobao123`/`taobao` |
- **Output:** filas en `inference_results` con el Top-K por usuario (`recommended_items` como lista JSONB de `{"item_id", "score"}`). Imprime:
  ```
  run_id=... usuarios=N filas_persistidas=N
  ```
- **Racional:** carga el último modelo `FINISHED` de MLflow (`runs:/{run_id}/model`), predice sobre el tensor del día 9 (`split=infer`), arma el ranking Top-K por usuario y persiste con un **upsert** (`ON CONFLICT (user_id) DO UPDATE`) vía `psycopg2.extras.execute_values`. Es el motor asíncrono que alimenta la API. No mide métricas de clasificación: el label del día 9 es `NULL` (simulación de producción sin ground truth).

---

## 7. API de servicio

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

## 8. Detalles técnicos del pipeline

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

- Tracking URI: `http://localhost:5000` (env `MLFLOW_TRACKING_URI`).
- Experimento: `taobao_recommender`.
- `mlflow.xgboost.autolog(log_models=True)` registra topología, hiperparámetros y métricas; además se hace `mlflow.xgboost.log_model(model, "model")` explícito.
- Backend store: `postgresql+psycopg2://taobao:taobao123@taobao_postgres:5432/mlflow`.
- Artifact store: `s3://taobao-mlflow-artifacts` (vía `MLFLOW_S3_ENDPOINT_URL` apuntando a LocalStack).

### Capa de servicio (ALB + ASG)

El módulo `terraform/modules/alb_asg` define:

- `aws_lb` (ALB público, `sg_alb`, subredes públicas).
- `aws_lb_target_group` (HTTP 8000, health check `/health`).
- `aws_lb_listener` (80 → target group).
- `aws_launch_template` (user_data que lanza el contenedor API, `sg_api_ec2`).
- `aws_autoscaling_group` (subredes privadas, min 2 / max 4).

**LocalStack community no implementa ELBv2 ni Auto Scaling** (features Pro). El módulo está **gated** con `alb_asg_enabled` (`false` por defecto en LocalStack). Para AWS real: `tofu apply -var="alb_asg_enabled=true"`.

---

## 9. Tests

Todos los tests son de integración (marcador `integration`) y requieren LocalStack + infraestructura aplicada.

| Comando | Alcance |
|---|---|
| `wsl -d Ubuntu -- bash -lc 'cd ~/itba/repo/taobao && uv run pytest tests/ -v'` | Suite completa |
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
| `uv run pytest tests/test_api.py` | API (200/404, esquema) |

**Prerrequisito para los tests:** LocalStack corriendo (`docker compose up -d`) e infraestructura aplicada (`tofu apply`). El endpoint se resuelve automáticamente (env `LOCALSTACK_ENDPOINT` → gateway WSL → `localhost:4566`).

---

## 10. Tabla resumen de comandos

| Paso | Comando (Windows) | Comando (WSL) |
|---|---|---|
| Levantar servicios | `docker compose up -d --build` | — |
| Estado de servicios | `docker compose ps` | — |
| Bajar servicios | `docker compose down` | — |
| Infraestructura | — | `wsl -d Ubuntu -- tofu apply` |
| Inicializar DB | — | `wsl -d Ubuntu -- uv run python init_db.py` |
| Bootstrap de datos | — | `wsl -d Ubuntu -- uv run python data_bootstrap.py` |
| Feature store | — | `wsl -d Ubuntu -- uv run python pipeline_features.py` |
| Entrenamiento | — | `wsl -d Ubuntu -- uv run python pipeline_training.py` |
| Inferencia | — | `wsl -d Ubuntu -- uv run python pipeline_inference.py` |
| API | — | `wsl -d Ubuntu -- uv run uvicorn api.main:app --port 8000` |
| Tests | — | `wsl -d Ubuntu -- uv run pytest tests/ -v` |

---

## 11. Mediciones reales del pipeline

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
