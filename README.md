
# Arquitectura Cloud para Sistema de Recomendación Batch

## I. Definición del Problema y Alcance

El objetivo es diseñar una arquitectura en la nube inmutable y reproducible (emulada en LocalStack) para optimizar el _funnel_ de conversión de un e-commerce. La solución implementa un _pipeline_ analítico _batch_ que procesa eventos estocásticos de navegación para calcular la probabilidad de interacción usuario-ítem. El alcance se enmarca en la migración de un "componente conocido": el subsistema de inferencia predictiva.

  
## II. Recursos: Diseño de Arquitectura y Tecnologías


La topología se segmenta en cuatro capas lógicas con responsabilidades aisladas, garantizando alta disponibilidad, seguridad pasiva y desacoplamiento.
### 1. Stack Tecnológico Base

- **Infraestructura como Código (IaC):** OpenTofu / Terraform.
- **Lenguajes y Motores:** Python (Pandas/DuckDB para procesamiento en memoria), SQL (PostgreSQL).
- **Entorno de Emulación:** LocalStack administrado vía Docker Compose.

### 2. Capa de Ingesta y Almacenamiento Estructurado (Data Lake)
- **Servicio:** Amazon S3
- **Racional:** Actúa como la única fuente de verdad. El _dataset_ crudo de Taobao (interacciones de usuarios con artículos y categorías) ingresará fragmentado cronológicamente y convertido a formato **Parquet**. Se estructurará en _buckets_ privados con los prefijos lógicos `/raw`, `/processed` y `/models`.

### 3. Capa de Procesamiento y Entrenamiento (Batch Computing)
- **Servicios:** Amazon EC2, EBS, IAM.
- **Racional:** Instancias EC2 efímeras, aprovisionadas con _Instance Profiles_ (IAM) para acceder a S3 sin credenciales estáticas. Ejecutarán _scripts_ de Python para computar la ingeniería de características (discretización temporal, RFM, tasas de intención) y entrenar el modelo predictivo, separando la matriz histórica (días 1-7) del conjunto de validación y simulación diaria.
### 4. Capa de Gobernanza y MLOps
- **Servicios:** Amazon EC2, Amazon RDS (PostgreSQL), Amazon S3.
- **Racional:** Despliegue de un servidor MLflow en una instancia ligera. Utiliza RDS como _backend store_ para la trazabilidad de hiperparámetros y métricas de los experimentos matemáticos, y S3 como _artifact store_ para los binarios de los modelos.
### 5. Capa de Servicio e Inferencia Reactiva (Serving Layer)
- **Servicios:** Amazon VPC, Application Load Balancer (ELB), Auto Scaling Group (EC2), Amazon RDS.
- **Racional:** El proceso _batch_ exporta las predicciones calculadas hacia una base de datos RDS (PostgreSQL) estructurada como almacén clave-valor ($O(1)$ de latencia). Un ELB público enruta el tráfico web hacia un grupo de autoescalado de instancias EC2 en subredes privadas, las cuales ejecutan una API ligera (ej. FastAPI en Docker) para consultar RDS y retornar las inferencias en tiempo real.


## III. Tiempo: Cronograma y Etapas de Desarrollo  

El desarrollo se estructura en fases secuenciales que garantizan la validación lógica y la reproducibilidad mediante integración continua. Los _commits_ del repositorio seguirán el estándar de _Conventional Commits_ en español.

### Fase 1: Redes e Infraestructura como Código

- **Objetivo:** Aprovisionar el perímetro de seguridad y los recursos persistentes.
- **Tareas:** Codificación en Terraform de la VPC multi-AZ, _Internet Gateway_, tablas de enrutamiento y _Security Groups_ bajo el principio de privilegio mínimo (lista blanca). Despliegue de _buckets_ S3 y clúster RDS Multi-AZ.
### Fase 2: Simulación de Datos y Bootstrap
- **Objetivo:** Desarrollar el _script_ determinista (`data_bootstrap.py`) que actúe como simulador transaccional.
- **Tareas:** Descarga del _dataset_ de Taobao, particionamiento físico cronológico del `timestamp`, conversión tabular a formato Parquet y carga paralela (vía `boto3`) a LocalStack S3 simulando la ingesta diaria.

### Fase 3: Pipeline Analítico y MLOps 

- **Objetivo:** Automatizar la extracción de características y el ciclo de vida del modelo.
- **Tareas:** Desarrollo de _scripts_ de transformación ELT/ETL para calcular tensores de frecuencia, dominancia de comportamiento y suavizado de Laplace. Despliegue del contenedor de MLflow y ejecución del entrenamiento (XGBoost/LightFM) registrando los artefactos.
    
### Fase 4: Capa de Exposición (Serving)
- **Objetivo:** Desacoplar la inferencia del entrenamiento para garantizar baja latencia.
- **Tareas:** Creación del esquema en PostgreSQL para almacenar resultados precomputados. Contenerización de la API HTTP. Configuración del Application Load Balancer y el Auto Scaling Group apuntando a las instancias EC2 en la subred privada.


## IV. Costos: Estimación Financiera y FinOps

La arquitectura desplegada en LocalStack será respaldada por una simulación económica rigurosa en la **AWS Pricing Calculator**, documentando los costos operativos reales en la nube.
- **Costos de Cómputo (EC2):** Se diferenciará el gasto de las instancias del _Auto Scaling Group_ (disponibilidad 24/7) frente al uso efímero de las instancias de procesamiento _batch_ (facturadas por horas/minutos de ejecución).
- **Costos de Almacenamiento (S3 y EBS):** Estimación volumétrica del _Data Lake_ (optimizada por la compresión de Parquet) y el almacenamiento en bloque adherido a las instancias.
- **Costos Transaccionales (RDS):** Cálculo del aprovisionamiento de la base de datos relacional (configuración Multi-AZ para HA) y, de manera crítica, el costo subyacente del almacenamiento de respaldos automáticos (_Automated Backups_).
- **Costos de Red (_Transfer Out_):** Estimación del tráfico saliente hacia internet a través del ELB y mitigación del gasto interno mediante el uso de _VPC Endpoints_ para el acceso a S3 sin transitar por un NAT Gateway.

## V. Ejecución: Bootstrap de Datos (Iteración 2)

El script `data_bootstrap.py` actúa como motor de ingesta del dataset Taobao: filtra usuarios con menos de 10 interacciones, deriva `event_date` en zona horaria `Asia/Shanghai` (UTC+8), particiona a Parquet por Hive (`event_date=YYYY-MM-DD/`) y sube a `s3://taobao-datalake/raw/` con `ThreadPoolExecutor`.

### Pipeline

1. **Infraestructura (OpenTofu → LocalStack):** crea el bucket `taobao-datalake`.
   ```bash
   wsl -d Ubuntu -- bash -lc 'cd ~/itba/repo/taobao/terraform && tofu init && tofu apply'
   ```
2. **Ingesta:** procesa el CSV y sube las particiones Parquet.
   ```bash
   wsl -d Ubuntu -- bash -lc 'cd ~/itba/repo/taobao && uv run python data_bootstrap.py'
   ```

### Datos de entrada

- `data/raw/UserBehavior.csv` — dataset completo (~3.7 GB, ~100M filas, sin header).
- `data/raw/UserBehavior_mini.csv` — muestra de 2004 filas para iteración rápida.

Las columnas esperadas (sin header): `user_id,item_id,category_id,behavior_type,timestamp` (epoch en segundos).

### Variables configurables (env)

| Variable | Default | Descripción |
|----------|---------|-------------|
| `RAW_CSV` | `data/raw/UserBehavior.csv` | Ruta del CSV crudo |
| `PARQUET_DIR` | `data/processed/parquet` | Directorio local de Parquet particionado |
| `DB_PATH` | `data/tmp/bootstrap.duckdb` | Archivo DuckDB temporal |
| `LOCALSTACK_ENDPOINT` | `http://localhost:4566` | Endpoint de LocalStack |

### Notas

- El bucket S3 **no se crea desde el script**; lo aprovisiona OpenTofu (`terraform/modules/s3`).
- El `timestamp` se interpreta como epoch UTC y se convierte a `Asia/Shanghai` para el `event_date`: `1511544070` → `2017-11-25 00:01 CST` (no UTC, que sería `2017-11-24`).
- El dataset abarca 25 nov – 3 dic 2017 en hora china; particionar en UTC corre las particiones un día.
- **Filtro temporal estricto**: el CSV crudo contiene ~469K filas con timestamps corruptos (negativos → 1902, futuros → 2037). El script descarta toda fila fuera del rango legítimo `timestamp BETWEEN 1511539200 AND 1512316799` (25 nov 00:00 – 3 dic 23:59 CST), generando exactamente 9 particiones en lugar de cientos espurias.
- Para correrlo contra la muestra rápida: `RAW_CSV=data/raw/UserBehavior_mini.csv uv run python data_bootstrap.py`. Aviso: el mini CSV no tiene usuarios con ≥10 interacciones (cada usuario aparece una vez); usar `tests/fixtures/dense.csv` o `tests/fixtures/out_of_range.csv` para validar el flujo.

### Tests

```bash
wsl -d Ubuntu -- bash -lc 'cd ~/itba/repo/taobao && uv run pytest tests/test_s3_bucket.py tests/test_bootstrap.py -v'
```

Ver `tests/README.md` para la suite completa.

## VI. Ejecución: Inicialización de RDS (Iteración 3)

La capa de persistencia relacional aprovisiona un PostgreSQL (motor de `aws_db_instance`) en las subredes privadas y un esquema de inferencias.

### Pipeline

1. **Contenedores:** LocalStack + el sidecar PostgreSQL (motor real conectable).
   ```powershell
   docker compose up -d
   ```
   El postgres sidecar (`taobao_postgres`) publica en `localhost:5432` con credenciales `taobao` / `taobao123` / db `taobao`. LocalStack emula la API RDS (metadata); el sidecar provee el engine que `psycopg2` conecta.

2. **Infraestructura (OpenTofu → LocalStack):** crea el `aws_db_subnet_group` en las subredes privadas y la `aws_db_instance` (`postgres` 15, `db.t3.micro`, `skip_final_snapshot`, no pública, `sg_rds`).
   ```bash
   wsl -d Ubuntu -- bash -lc 'cd ~/itba/repo/taobao/terraform && tofu init && tofu apply'
   ```

3. **Inicialización del esquema:** crea idempotentemente la tabla `inference_results`.
   ```bash
   wsl -d Ubuntu -- bash -lc 'cd ~/itba/repo/taobao && uv run python init_db.py'
   ```

### Esquema `inference_results`

| Columna | Tipo | Restricción |
|---------|------|-------------|
| `user_id` | `BIGINT` | `PRIMARY KEY` |
| `recommended_items` | `JSONB` | `NOT NULL` |
| `updated_at` | `TIMESTAMP` | `DEFAULT CURRENT_TIMESTAMP` |

### Variables de conexión (`init_db.py`)

| Variable | Default | Descripción |
|----------|---------|-------------|
| `PGHOST` | `localhost` | Host del sidecar postgres |
| `PGPORT` | `5432` | Puerto |
| `PGUSER` | `taobao` | Usuario |
| `PGPASSWORD` | `taobao123` | Contraseña |
| `PGDATABASE` | `taobao` | Base de datos |

### Notas

- El `sg_rds` ya aísla el puerto 5432 exclusivamente a `sg_api_ec2` y `sg_batch_ec2` (Iteración 1).
- **LocalStack community no implementa el servicio RDS** (feature Pro). Por eso el módulo `rds` está **gated** con `rds_enabled` (`false` por defecto en LocalStack): los recursos `aws_db_instance`/`aws_db_subnet_group` están definidos y son correctos para AWS real, pero no se crean en LocalStack. El engine real lo provee el sidecar `postgres:15` del `docker-compose.yml`; `init_db.py` conecta a ese sidecar.
- Para AWS real: `tofu apply -var="rds_enabled=true"`.
- La tabla se crea con `CREATE TABLE IF NOT EXISTS`, por lo que re-ejecutar `init_db.py` es seguro (idempotente).
- Los tests de metadata RDS (boto3) se **saltan** automáticamente si el servicio no está disponible; los tests de esquema vía `psycopg2` siempre corren contra el sidecar.

### Tests

```bash
wsl -d Ubuntu -- bash -lc 'cd ~/itba/repo/taobao && uv run pytest tests/test_rds.py -v'
```

## VII. Ejecución: Gobernanza MLOps (Iteración 4)

Despliega un servidor MLflow con backend store en PostgreSQL (base `mlflow`) y artifact store en S3 (`taobao-mlflow-artifacts`).

### Pipeline

1. **Infraestructura (OpenTofu → LocalStack):** crea el bucket `taobao-mlflow-artifacts` (con bloqueo de acceso público, igual que el Data Lake).
   ```bash
   wsl -d Ubuntu -- bash -lc 'cd ~/itba/repo/taobao/terraform && tofu init && tofu apply'
   ```
2. **Contenedores:** construye la imagen MLflow (custom), crea la DB `mlflow` y levanta el servidor.
   ```powershell
   docker compose up -d --build
   ```
   - `mlflow-db-init` (one-shot) crea la base `mlflow` en el sidecar postgres de forma idempotente (`init_mlflow_db.py`).
   - `mlflow` expone el puerto 5000, apunta su `backend-store-uri` a `postgresql+psycopg2://...@taobao_postgres:5432/mlflow` y su `default-artifact-root` a `s3://taobao-mlflow-artifacts`.
   - `MLFLOW_S3_ENDPOINT_URL=http://localstack_main:4566` enruta el tráfico S3 del contenedor hacia LocalStack (misma red Docker).

### Configuración

| Aspecto | Valor |
|---------|-------|
| Imagen | `docker/mlflow/Dockerfile` (python:3.12-slim + mlflow + psycopg2-binary + boto3) |
| UI / API | `http://localhost:5000` (health: `/health`) |
| Backend store | `postgresql+psycopg2://taobao:taobao123@taobao_postgres:5432/mlflow` |
| Artifact root | `s3://taobao-mlflow-artifacts` |
| S3 endpoint (contenedor) | `http://localstack_main:4566` |
| Credenciales AWS (emuladas) | `test` / `test` / `us-east-1` |

### Variables del cliente (`mlflow_s3_env`, tests)

Para que el cliente `mlflow` de los tests (corre en WSL) suba artefactos a LocalStack: `MLFLOW_S3_ENDPOINT_URL=http://<gateway>:4566` + creds `test`/`test`.

### Tests

```bash
wsl -d Ubuntu -- bash -lc 'cd ~/itba/repo/taobao && uv run pytest tests/test_mlflow.py -v'
```

Valida: health HTTP 200, creación de experimento con métrica + artefacto (metadata en PostgreSQL, artefacto en S3) y persistencia de runs en el backend store.

## VIII. Ejecución: Feature Store (Iteración 5)

`pipeline_features.py` lee las particiones crudas de `s3://taobao-datalake/raw/`, aplica una segregación temporal estricta para evitar _data leakage_ y persiste matrices de features en `s3://taobao-datalake/processed/`.

### Pipeline

1. **Infraestructura y datos:** requeridos `taobao-datalake` (Iter 2) y las particiones raw (bootstrap).
   ```bash
   wsl -d Ubuntu -- bash -lc 'cd ~/itba/repo/taobao/terraform && tofu apply'
   wsl -d Ubuntu -- bash -lc 'cd ~/itba/repo/taobao && uv run python data_bootstrap.py'
   ```
2. **Feature store:**
   ```bash
   wsl -d Ubuntu -- bash -lc 'cd ~/itba/repo/taobao && uv run python pipeline_features.py'
   ```

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

### Variables configurables (env)

| Variable | Default | Descripción |
|----------|---------|-------------|
| `BUCKET` | `taobao-datalake` | Bucket del data lake |
| `RAW_PREFIX` | `raw` | Prefijo de lectura |
| `PROCESSED_PREFIX` | `processed` | Prefijo de escritura |
| `EPSILON` | `1e-6` | Factor infinitesimal para intent_score |
| `NEG_RATIO` | `4` | Negativos por (usuario, día) |
| `TOP_POPULAR` | `20` | Ítems populares para muestreo |
| `LOCALSTACK_ENDPOINT` | `http://localhost:4566` | Endpoint de LocalStack |

### Persistencia

Cada split se escribe como Parquet particionado por Hive en `s3://taobao-datalake/processed/split={train|val|test|infer}/` (escritura directa de DuckDB `httpfs` contra LocalStack).

### Tests

```bash
wsl -d Ubuntu -- bash -lc 'cd ~/itba/repo/taobao && uv run pytest tests/test_features.py -v'
```

Valida: escritura de los 4 splits en S3, **disyunción estricta de fechas** entre conjuntos, días esperados por split, presencia de negativos (label 0) en train/val/test, ausencia de label en infer y columnas de features.

## IX. Ejecución: Modelado XGBoost y MLOps (Iteración 5B)

`pipeline_training.py` lee las matrices precomputadas de `s3://taobao-datalake/processed/`, entrena un `XGBClassifier` con early stopping sobre validación y registra el ciclo de vida en MLflow.

### Pipeline

1. **Dependencias:** requiere `xgboost` (`uv sync` tras agregarlo a `pyproject.toml`).
2. **Matrices:** `processed/` debe contener `split=train|val|test` (generadas por `pipeline_features.py`). El split `infer` **no se lee**.
3. **Entrenamiento + registro:**
   ```bash
   wsl -d Ubuntu -- bash -lc 'cd ~/itba/repo/taobao && uv run python pipeline_training.py'
   ```

### Modelado

- `XGBClassifier(n_estimators=200, max_depth=4, learning_rate=0.1, eval_metric="logloss", early_stopping_rounds=10)`.
- `eval_set=[(X_val, y_val)]` — early stopping y monitoreo de pérdida sobre el día 7.
- Features (9): `user_item_freq, user_cat_freq, user_cat_eng, intent_score, item_popularity, cat_popularity, cat_target_enc, lag_1, lag_2`. Target: `label`.

### Evaluación offline (día 8)

`predict_proba(X_test)` → 6 métricas, registradas en MLflow como `test_*`:
- `test_auc_roc` — `roc_auc_score`.
- `test_logloss` — `log_loss`.
- `test_precision`, `test_recall`, `test_f1`, `test_accuracy` — sobre la predicción binaria `y_pred = (y_prob >= 0.5)` (umbral fijo 0.5, con `zero_division=0`).

> Nota: en `pipeline_inference.py` (día 9) no se miden estas métricas: el tensor de inferencia tiene `label = NULL` (simulación de producción sin ground truth), por lo que no es posible computar métricas de clasificación binaria allí.

### Gobernanza MLflow

- Tracking URI: `http://localhost:5000` (env `MLFLOW_TRACKING_URI`).
- Experimento: `taobao_recommender`.
- `mlflow.xgboost.autolog(log_models=True)` registra topología, hiperparámetros y métricas; además se hace `mlflow.xgboost.log_model(model, "model")` explícito.
- Artifact store: `s3://taobao-mlflow-artifacts` (via `MLFLOW_S3_ENDPOINT_URL` apuntando a LocalStack).

### Variables configurables (env)

| Variable | Default | Descripción |
|----------|---------|-------------|
| `BUCKET` | `taobao-datalake` | Bucket del data lake |
| `PROCESSED_PREFIX` | `processed` | Prefijo de las matrices |
| `LOCALSTACK_ENDPOINT` | `http://localhost:4566` | Endpoint de LocalStack |
| `MLFLOW_TRACKING_URI` | `http://localhost:5000` | URI del servidor MLflow |

### Tests

```bash
wsl -d Ubuntu -- bash -lc 'cd ~/itba/repo/taobao && uv run pytest tests/test_training.py -v'
```

Valida: existencia del run en el experimento (persistido en PostgreSQL), métricas `test_auc_roc`/`test_logloss` registradas, artefacto físico en `s3://taobao-mlflow-artifacts` y el flavor xgboost del modelo. No carga el modelo en memoria.

## X. Ejecución: Inferencia Batch y Persistencia (Iteración 5C)

`pipeline_inference.py` carga el modelo desde MLflow, genera las recomendaciones para el Día 9 y persiste el Top-K por usuario en PostgreSQL para su consulta por la API.

### Pipeline

1. **Prerrequisitos:** un run `FINISHED` en el experimento `taobao_recommender` (generado por `pipeline_training.py`) y el tensor `split=infer` en `processed/` (generado por `pipeline_features.py`).
2. **Ejecución:**
   ```bash
   wsl -d Ubuntu -- bash -lc 'cd ~/itba/repo/taobao && uv run python pipeline_inference.py'
   ```

### Flujo

1. **Carga del modelo:** `mlflow.search_runs` identifica el último run `FINISHED` del experimento y `mlflow.xgboost.load_model("runs:/{run_id}/model")` recupera el artefacto (vía `MLFLOW_S3_ENDPOINT_URL` → LocalStack).
2. **Datos:** lee exclusivamente `s3://taobao-datalake/processed/split=infer/` (Día 9) con DuckDB `httpfs`.
3. **Top-K:** `predict_proba` → score de interacción por (usuario, ítem); agrupa por `user_id`, ordena descendente y toma los `TOP_K` (default 10).
4. **Persistencia:** upsert masivo (`psycopg2.extras.execute_values`) en `inference_results` con `ON CONFLICT (user_id) DO UPDATE`, actualizando `recommended_items` (lista JSONB de `item_id`) y `updated_at`.

### Variables configurables (env)

| Variable | Default | Descripción |
|----------|---------|-------------|
| `BUCKET` | `taobao-datalake` | Bucket del data lake |
| `PROCESSED_PREFIX` | `processed` | Prefijo de las matrices |
| `LOCALSTACK_ENDPOINT` | `http://localhost:4566` | Endpoint de LocalStack |
| `MLFLOW_TRACKING_URI` | `http://localhost:5000` | URI del servidor MLflow |
| `TOP_K` | `10` | Ítems recomendados por usuario |
| `PGHOST`/`PGPORT` | `localhost`/`5432` | Conexión al sidecar postgres |
| `PGUSER`/`PGPASSWORD`/`PGDATABASE` | `taobao`/`taobao123`/`taobao` | Credenciales |

### Tests

```bash
wsl -d Ubuntu -- bash -lc 'cd ~/itba/repo/taobao && uv run pytest tests/test_inference.py -v'
```

Valida: filas persistidas en `inference_results`, `recommended_items` como lista JSONB de objetos `{"item_id", "score"}`, máx. 10 ítems por usuario, ítems válidos del catálogo e idempotencia del upsert (re-ejecución no duplica filas).

## XI. Ejecución: Capa de Servicio (Iteración 6)

API REST (FastAPI) que sirve las inferencias precomputadas desde PostgreSQL.

### Aplicación

`api/main.py` expone `GET /recommendations/{user_id}`:
- Pool de conexiones asíncrono (`asyncpg`) al sidecar postgres; consulta por PK `user_id` ($O(1)$).
- Modelo Pydantic estricto `RecommendationResponse` → `List[RecommendationItem]` (`item_id: int`, `score: float`).
- HTTP 200 con el esquema válido, o HTTP 404 si el usuario no existe.

```bash
# Ejecutar localmente (WSL)
wsl -d Ubuntu -- bash -lc 'cd ~/itba/repo/taobao && uv run uvicorn api.main:app --host 0.0.0.0 --port 8000'

# Probar
curl http://localhost:8000/recommendations/1
```

Contenedor: `api/Dockerfile` (multietapa: build con `uv sync`, runtime `uvicorn`).

### Infraestructura (ALB + ASG)

Módulo `terraform/modules/alb_asg` define:
- `aws_lb` (ALB público, `sg_alb`, subredes públicas).
- `aws_lb_target_group` (HTTP 8000, health check `/health`).
- `aws_lb_listener` (80 → target group).
- `aws_launch_template` (user_data que lanza el contenedor API, `sg_api_ec2`).
- `aws_autoscaling_group` (subredes privadas, min 2 / max 4).

**LocalStack community no implementa ELBv2 ni Auto Scaling** (features Pro, igual que RDS). Por eso el módulo está **gated** con `alb_asg_enabled` (`false` por defecto en LocalStack): los recursos están definidos y son correctos para AWS real, pero no se crean localmente. Para AWS real: `tofu apply -var="alb_asg_enabled=true"`.

```bash
wsl -d Ubuntu -- bash -lc 'cd ~/itba/repo/taobao/terraform && tofu init && tofu apply'
```

### Tests

```bash
wsl -d Ubuntu -- bash -lc 'cd ~/itba/repo/taobao && uv run pytest tests/test_api.py -v'
```

Valida: HTTP 200 con esquema `RecommendationResponse` (item_id int, score float), HTTP 404 para usuario inexistente y 200 para todos los usuarios poblados.

## XII. Guía de despliegue

Ver **[DEPLOYMENT.md](DEPLOYMENT.md)** — documento completo con todos los comandos para desplegar los servicios y ejecutar los scripts, incluyendo el input/output de cada uno y el racional conceptual.

## XIII. Inventario de infraestructura

Ver **[INFRAESTRUCTURA.md](INFRAESTRUCTURA.md)** — inventario de todos los servicios que se instancian a lo largo del pipeline, distinguiendo los que permanecen encendidos de forma continua de los efímeros, con análisis de escalabilidad.