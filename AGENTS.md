# AGENTS.md

TP Integrador (ITBA): pipeline batch de recomendación sobre el dataset Taobao, emulando AWS en LocalStack. El plan de arquitectura en 4 capas (S3 / EC2 batch / MLflow+RDS / ELB+ASG+RDS+FastAPI) está en `ARQUITECTURA.md`; la guía operativa en `DEPLOYMENT.md`. Fuentes de verdad externas (Obsidian): `Taobao - Prompt Maestro.md` y `Taobao - dataset inicial.md` en `C:\Users\Usuario\Documents\data\Apuntes\IngData\ITBA\TP Integrador\`.

## Reglas estrictas (Prompt Maestro)

- Código **sin comentarios** ni docstrings explicativos, sin excepciones.
- Commits: **Conventional Commits en español** (historial actual ya sigue este formato).
- Todo AWS se emula en LocalStack: clientes `boto3` y providers de OpenTofu apuntan a `http://localhost:4566`. IAM con roles efímeros, sin access keys fijas.
- IaC estructurado en módulos lógicos y reutilizables.

## Workflow por iteraciones

El proyecto avanza en 6 iteraciones (grafo acíclico). **No ejecutar todas a la vez ni avanzar a la siguiente sin confirmación explícita del usuario.** Estado actual: **todas las iteraciones completas** (IaC en `terraform/`, pipeline batch, tests de integración). Los scripts ejecutables son: `data_bootstrap.py`, `pipeline_features.py`, `pipeline_training.py`, `pipeline_inference.py`, `init_db.py`, `init_mlflow_db.py`, `api/main.py`.

Reglas de negocio clave por iteración:

- **Iter. 2 (bootstrap):** filtrar usuarios con <10 interacciones históricas; derivar `event_date` desde `timestamp`; subir Parquet a `s3://taobao-datalake/raw/event_date=...`.
- **Iter. 5 (modelado):** burn-in días 1-3 (solo acumular historial); matriz de entrenamiento días 4-6, val día 7, test día 8, infer día 9 con muestreo negativo sintético. Target encoding con suavizado de Laplace + lag operators. XGBoost optimizado para Top-K Retrieval, registrado en MLflow.

## Entorno / ejecución (gotchas)

El repo vive en **WSL2 (Ubuntu)** pero el shell del agente es **PowerShell de Windows**. El toolchain está dividido:

- **Python / uv / pytest → solo WSL.** El `.venv` es Linux (Python 3.12). Ejecutar: `wsl -d Ubuntu -- uv run pytest`, `wsl -d Ubuntu -- uv run python main.py`. `uv run` desde Windows NO funciona (el venv no es de Windows).
- **OpenTofu → solo WSL:** `wsl -d Ubuntu -- tofu ...`. No existe binario `terraform`.
- **Docker / Compose → solo Windows:** `docker compose ...` desde PowerShell. La integración WSL de Docker Desktop está deshabilitada, así que `docker` falla dentro de WSL. LocalStack se levanta como contenedor desde Windows (puerto `localhost:4566`).
- **LocalStack pinned a `localstack/localstack:3.5.0`**: `:latest` exige licencia (exit 55). No cambiarlo.
- **LocalStack community NO implementa RDS, ELBv2 ni Auto Scaling** (features Pro). Los módulos `terraform/modules/rds` y `alb_asg` están **gated** con `rds_enabled`/`alb_asg_enabled` (`false` por defecto); `tofu apply` no crea esos recursos en LocalStack. La base real es el sidecar `postgres:15` del compose; la API se prueba con `TestClient`, no vía ALB.
- **`PERSISTENCE=1` en LocalStack es obligatorio** en `docker-compose.yml`: sin él, `docker compose up --build` recrea el contenedor y borra todo el estado (buckets, VPC, IAM). Si se pierde el estado, re-correr `tofu apply` + `init_db.py` + el pipeline.
- **Endpoint desde WSL**: los scripts y `tofu` (corren en WSL) alcanzan LocalStack/MLflow/postgres del host Windows vía el **gateway WSL** (`ip route show default | awk '{print $3}'`), NO `localhost`. Los tests (`tests/conftest.py`) lo detectan automáticamente; los scripts usan env `LOCALSTACK_ENDPOINT`, `MLFLOW_TRACKING_URI`, `PGHOST`.
- **`wsl -d Ubuntu -- bash -lc '...'` con comillas/parentesis internos se rompe**: PowerShell re-empaqueta la línea. Workaround: escribir un `.sh` temporal en el repo y ejecutarlo (`wsl ... bash /path/script.sh`), o usar heredoc/`python -` por stdin.
- **Git desde Windows** sobre la ruta UNC falla con `fatal: detected dubious ownership`. Workaround: `git -c safe.directory='%(prefix)///wsl.localhost/Ubuntu/home/tepeve/itba/repo/taobao' ...`, o correr git dentro de WSL.
- **Commits con `-m` vía `wsl ... bash -lc "git commit -m \"...\""` se truncan**: el mensaje se corta en la primera comilla doble y queda solo el tipo (`feat:`, `test:`, `docs:`). Workaround: usar un archivo de mensaje (`git commit -F /tmp/msg.txt`).
- **DuckDB `httpfs`** lee y escribe Parquet directo en LocalStack S3 (`SET s3_endpoint='<gateway>:4566'`, `s3_url_style='path'`, `s3_use_ssl=false`). Es el motor de `pipeline_features.py`/`data_bootstrap.py`.
- Python del proyecto: 3.12 (gestionado por uv vía `.python-version`); el Python del host Windows es 3.14, ignorarlo.
- No hay lint/typecheck/CI configurados; `pre-commit` es dependencia pero no existe `.pre-commit-config.yaml`.

## Datos

- `data/raw/UserBehavior.csv`: 3.7 GB, ~100M filas, **sin header**, columnas `user_id,item_id,category_id,behavior_type,timestamp` (`behavior_type` ∈ `pv|buy|cart|fav`). Usar `data/raw/UserBehavior_mini.csv` (2004 filas) para iterar rápido, o las fixtures de `tests/fixtures/`.
- `*.csv` y `*.parquet` están gitignored (excepción: `tests/fixtures/*.csv`).
- **Particionar por `event_date` en `Asia/Shanghai` (UTC+8), nunca UTC.** Los timestamps son epoch y el dataset abarca 25 nov – 3 dic 2017 en hora china; ej. `1511544070` = `2017-11-25 00:01 CST` pero `2017-11-24 16:01 UTC`. Derivar la fecha en UTC corre las particiones un día.
- El CSV completo tiene ~469K filas con timestamps corruptos (1902/2037); el bootstrap filtra con `timestamp BETWEEN 1511539200 AND 1512316799`.
