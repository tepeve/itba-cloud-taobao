# Taobao Product Recommendation Pipeline

Pipeline batch de recomendación sobre el dataset de Taobao, emulado en LocalStack con OpenTofu. Optimiza el _funnel_ de conversión de un e-commerce calculando la probabilidad de interacción usuario-ítem a partir de eventos de navegación.

## Quickstart

```bash
# 1. Levantar servicios (LocalStack + PostgreSQL + MLflow) — Windows PowerShell
docker compose up -d --build

# 2. Aprovisionar infraestructura en LocalStack — WSL
wsl -d Ubuntu -- bash -lc 'cd ~/itba/repo/taobao/terraform && tofu init && tofu apply'

# 3. Ejecutar el pipeline completo (inicialización → datos → features → modelo → inferencia) — WSL
wsl -d Ubuntu -- bash -lc 'cd ~/itba/repo/taobao && uv run python init_db.py && uv run python data_bootstrap.py && uv run python pipeline_features.py && uv run python pipeline_training.py && uv run python pipeline_inference.py'
```

## Documentación

| Documento | Contenido |
|-----------|-----------|
| [ARQUITECTURA.md](ARQUITECTURA.md) | Diseño conceptual: problema, 4 capas, stack, cronograma, costos |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Guía operativa: comandos, input/output, racional de cada script, mediciones reales |
| [INFRAESTRUCTURA.md](INFRAESTRUCTURA.md) | Inventario de servicios (continuos vs. efímeros) y escalabilidad |
| [COMPUTO.md](COMPUTO.md) | Estado de la capa de cómputo (EC2/Lambda pendiente) y enfoques propuestos |
| [tests/README.md](tests/README.md) | Suite de tests de integración por iteración |

## Resumen del pipeline

```
CSV (3.5 GB, 100M filas)
  └─ data_bootstrap.py      → s3://taobao-datalake/raw/ (Parquet particionado por event_date)
       └─ pipeline_features.py → s3://taobao-datalake/processed/ (splits train/val/test/infer)
            └─ pipeline_training.py → MLflow (modelo XGBoost + 6 métricas)
                 └─ pipeline_inference.py → PostgreSQL inference_results (Top-K por usuario)
                      └─ API FastAPI  → GET /recommendations/{user_id}
```

## Estructura del repositorio

```
api/                  Capa de servicio (FastAPI + Dockerfile)
terraform/            IaC modular (networking, security_groups, iam, s3, rds, alb_asg)
data_bootstrap.py     Ingesta: CSV → Parquet en S3
pipeline_features.py  Feature store (split temporal anti-leakage)
pipeline_training.py  Entrenamiento XGBoost + registro en MLflow
pipeline_inference.py Inferencia batch Top-K → PostgreSQL
init_db.py            Esquema inference_results
init_mlflow_db.py     Base de datos mlflow
docker/               Imagen MLflow custom
tests/                Suite de integración
```

## Convenciones

- Commits: **Conventional Commits en español**.
- Código **sin comentarios**.
- AWS emulado en LocalStack (`http://localhost:4566`); IAM con roles efímeros.
- `event_date` particionado en `Asia/Shanghai` (UTC+8), nunca UTC.
