# AGENTS.md

TP Integrador (ITBA): pipeline batch de recomendación sobre el dataset Taobao, emulando AWS en LocalStack. El plan de arquitectura en 4 capas (S3 / EC2 batch / MLflow+RDS / ELB+ASG+RDS+FastAPI) está en `docs/ARQUITECTURA.md`; la guía operativa en `docs/DEPLOYMENT.md`. Fuentes de verdad externas (Obsidian): `Taobao - Prompt Maestro.md` y `Taobao - dataset inicial.md` en `C:\Users\Usuario\Documents\data\Apuntes\IngData\ITBA\TP Integrador\`.

## Estado actual (punto de retoma)

- Temporalidad Airflow implementada y pusheada (`feat(orquestación)...`): DAG diario/semanal a las 03:00 Asia/Shanghai.
- Fixes de pipeline pusheados (`fix(pipeline): duckdb en disco y timeout httpfs`): `pipeline_features.py` con DuckDB en disco + `http_timeout`, `test_features.py` con endpoint dinámico, `fetch_dataset.sh` con skip, `Makefile` con `make data` arreglado.
- **Pipeline E2E corrido y suite verde** (máquina 90 GB RAM): `make pipeline` completo OK (`data_bootstrap` → 969353 usuarios calificados, `pipeline_training` run XGBoost en MLflow, `pipeline_inference` → 950927 filas en `inference_results`; users 1/2/3 presentes). Suite: **79 passed, 14 skipped** (skips = RDS/ASG gated en LocalStack community).
- Fix de aislamiento (no commiteado aún): `tests/test_bootstrap.py` ahora usa prefix propio `raw_test_bootstrap` en vez del `raw` compartido. Antes, el `data_bootstrap` completo dejaba 9 particiones `event_date=` en `raw/` y rompía `test_bootstrap_partition_dates_match_expected` (esperaba solo 2). Mismo patrón que `test_features.py` (`raw_test_features`/`processed_test_features`).
- Para re-correr en local: `make pipeline` exige exportar antes `LOCALSTACK_ENDPOINT`, `MLFLOW_TRACKING_URI` y los 5 `PG*` (sin fallbacks; `PGPORT` hace `int()` y revienta si no está).

## Reglas estrictas (Prompt Maestro)

- Código **sin comentarios** ni docstrings explicativos, sin excepciones.
- Commits: **Conventional Commits en español** (historial actual ya sigue este formato).
- Todo AWS se emula en LocalStack: clientes `boto3` y providers de OpenTofu apuntan a `http://localhost:4566`. IAM con roles efímeros, sin access keys fijas.
- IaC estructurado en módulos lógicos y reutilizables.
- No committear sin pedido explícito.

## Orquestación Airflow (temporalidad)

Un solo DAG (`taobao_dag.py`, raíz del repo) sirve a dos despliegues, ambos canónicos:

- **Local** `docker-compose.airflow.yml`: imagen `apache/airflow:2.9.0-python3.12`, monta el repo como `/opt/airflow/dags`.
- **EC2** módulo `terraform/modules/compute` (`init_airflow.sh.tpl`): sincroniza el bucket `taobao-airflow-dags` cada 5 min vía cron.

Temporalidad objetivo (implementada en el DAG): ingesta (`data_bootstrap`) + features **diaria**, entrenamiento XGBoost→MLflow **semanal los martes**, inferencia **diaria**, todo a las **03:00 Asia/Shanghai**. El ancla del martes imita el dataset: la ventana de entrenamiento (días 4-6) arranca martes 28-nov-2017. Implementación: `schedule='0 3 * * *'` + `start_date=pendulum.datetime(..., tz='Asia/Shanghai')`; un `ShortCircuitOperator` (`_is_training_day`, `weekday()==1`) gatea `pipeline_training`; `pipeline_inference` usa `trigger_rule='none_failed_min_one_success'` con upstreams `[features, training]` → corre diario y los martes con el modelo recién entrenado, el resto de días con el último modelo `FINISHED` de MLflow (`load_latest_model`, pipeline_inference.py).

**Gotcha timezone:** Airflow 2.9 defaultea a UTC (ningún despliegue define `AIRFLOW__CORE__TIMEZONE` ni `TZ`); el dataset particiona en `Asia/Shanghai` (UTC+8). Por eso el timezone se fija **a nivel DAG** con `pendulum`, no en el contenedor: 03:00 Shanghai = 19:00 UTC. Un cron `0 3 * * *` sin `tz` dispararía 11:00 Shanghai. Si se cambia el horario, editar el `tz` del DAG (y ambos despliegues solo si se quiere alinear la TZ del contenedor).

El contexto lo inyecta el DAG vía `env_vars` (variables Airflow `datalake_bucket`, `mlflow_db_uri`, `rds_host`, `rds_user`, `rds_password`, `localstack_endpoint`).

## Entorno / ejecución (gotchas)

El shell del agente es **PowerShell 5.1 (Windows)**, con el repo montado vía `\\wsl.localhost\Ubuntu\home\tepeve\itba\repo\taobao` (WSL pwd `/home/tepeve/itba/repo/taobao`, rama `main`). Reparto de comandos:

- **PowerShell (Docker Desktop):** `docker compose up -d --build` (LocalStack/Postgres/MLflow corren como contenedores en Windows).
- **WSL** (`wsl.exe -e bash -lc '...'` o `bash.exe -lc 'cd /home/tepeve/itba/repo/taobao && ...'`): `tofu`, `make`, `uv run`, `bash fetch_dataset.sh`, `git`, `pytest`.
- **`git` desde PowerShell falla** con `dubious ownership` (git.exe de Windows sobre el UNC de WSL) → usar git dentro de WSL, o `git config --global --add safe.directory '%(prefix)///wsl.localhost/Ubuntu/home/tepeve/itba/repo/taobao'`.
- **`uv` existe en ambos lados**, pero el `.venv` es **Linux (Python 3.12)** → `uv run`/`pytest` solo dentro de WSL.

- **`tofu` no está en el PATH de Windows**: en WSL vive en `/snap/bin/tofu` (snap). No existe binario `terraform`.
- **`make data`** ahora llama `bash fetch_dataset.sh` (antes `uv run python`, estaba roto); el script saltea la descarga si `data/raw/UserBehavior.csv` ya existe.
- **`make pipeline`** encadena `init_db.py` → `data_bootstrap.py` → `pipeline_features.py` → `pipeline_training.py` → `pipeline_inference.py`. `main.py` (raíz) es stub (`print("Hello from taobao!")`), no entrypoint. La base `mlflow` la crea el one-shot `mlflow-db-init` del compose (`init_mlflow_db.py`), no `make pipeline`.
- Tests: todos marcados `integration` (pyproject) → requieren LocalStack `up` + `tofu apply` previo. Correr: `uv run pytest tests/ -v`; un solo test: `uv run pytest tests/test_iam.py::test_role_trust_ec2 -v`.
- **LocalStack pinned `localstack/localstack:3.5.0`** (`:latest` exige licencia, exit 55). `PERSISTENCE=1` es obligatorio en `docker-compose.yml` (sin él, `up --build` borra estado), **pero NO sobrevive a un kill duro**: si la VM de WSL se reinicia por OOM, `localstack-data/state/` queda vacío y hay que re-aplicar `tofu apply` + re-correr el pipeline (buckets, VPC, IAM, S3 se pierden). `SERVICES` debe incluir `ssm` o `tofu apply` falla con `Service 'ssm' is not enabled`.
- **LocalStack community NO implementa RDS, ELBv2 ni Auto Scaling** (features Pro). `terraform/modules/rds` y `alb_asg` son declarativos para AWS real; en LocalStack aplicar con **`-var alb_asg_enabled=false`**, o falla creando `aws_lb`. Base real = sidecar `postgres:15` del compose; API se prueba con `TestClient`, no vía ALB.
- **Scripts analíticos sin fallbacks `localhost`**: `os.environ.get()` para `LOCALSTACK_ENDPOINT`, `MLFLOW_TRACKING_URI`, `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD`, `PGDATABASE` **no tienen default** (y `PGPORT` hace `int()`, revienta si falta). El DAG los inyecta; en local sin DAG exportar a mano. Valores locales desde WSL: `LOCALSTACK_ENDPOINT=http://localhost:4566`, `MLFLOW_TRACKING_URI=http://localhost:5000`, `PGHOST=localhost`, `PGPORT=5432`, `PGUSER=taobao`, `PGPASSWORD=taobao123`, `PGDATABASE=taobao`. Endpoint desde WSL = `localhost` (`_wsl_gateway_*` de conftest solo activan con `os.name=="nt"`); desde contenedores = `host.docker.internal`.
- **DuckDB `httpfs`** lee/escribe Parquet directo en LocalStack S3 (`s3_endpoint`, `s3_url_style='path'`, `s3_use_ssl=false`). `_configure_s3` (pipeline_features.py) además setea `http_timeout=600000` + `http_retries=5`: el default de 30s de httpfs **falla** leyendo parquet grande (~120 MB/partición) desde LocalStack lento. Motor de `pipeline_features.py`/`data_bootstrap.py`.
- **DuckDB en disco es working set efímero, no cambia la arquitectura**: `pipeline_features.py` abre `data/tmp/features.duckdb` y `data_bootstrap.py` abre `data/tmp/bootstrap.duckdb` (spill a disco); S3 sigue siendo fuente/destino vía `read_parquet`/`COPY TO`. `DUCKDB_MEMORY_LIMIT` (env, opcional) fuerza spill en máquinas con poca RAM.
- **RAM**: `pipeline_features.py` materializa ~99M filas + ~15 tablas intermedias; una VM WSL2 de 3.4 GB hace OOM y **reinicia la VM** (mata la sesión). Con poca RAM setear `DUCKDB_MEMORY_LIMIT` y no correr `docker compose up -d --build` en paralelo al pipeline.
- Python 3.12 gestionado por uv (`.python-version`). No hay lint/typecheck/CI; `pre-commit` es dependencia sin `.pre-commit-config.yaml`.

## Reglas de negocio del pipeline

- **Bootstrap:** filtrar usuarios con <10 interacciones históricas; derivar `event_date` desde `timestamp`; subir Parquet a `s3://taobao-datalake/raw/event_date=...`.
- **Modelado:** burn-in días 1-3 (solo acumular historial); train días 4-6, val día 7, test día 8, infer día 9 con muestreo negativo sintético. Target encoding con suavizado de Laplace + lag operators. XGBoost optimizado para Top-K Retrieval, registrado en MLflow.
- **Sprint 2 IaaS:** red con NAT Gateway + VPC Endpoint S3 (Gateway) sobre RT privada; `sg_airflow` (ingress interno 8080/5000); `sg_rds` solo `sg_airflow` + `sg_api_ec2` (5432); instancia orquestador en subred privada; secretos DB en SSM (`/taobao/prod/rds_password`); bucket `taobao-airflow-dags`.

## Datos

- `data/raw/UserBehavior.csv`: 3.7 GB, ~100M filas, **sin header**, columnas `user_id,item_id,category_id,behavior_type,timestamp` (`behavior_type` ∈ `pv|buy|cart|fav`). Para iterar rápido: `UserBehavior_mini.csv` (2004 filas) o fixtures de `tests/fixtures/`.
- `*.csv` y `*.parquet` gitignored (excepción: `tests/fixtures/*.csv`).
- **Particionar por `event_date` en `Asia/Shanghai` (UTC+8), nunca UTC.** Ej. `1511544070` = `2017-11-25 00:01 CST` pero `2017-11-24 16:01 UTC`; derivar en UTC corre las particiones un día.
- El CSV completo tiene ~469K filas con timestamps corruptos (1902/2037); el bootstrap filtra `timestamp BETWEEN 1511539200 AND 1512316799`.
