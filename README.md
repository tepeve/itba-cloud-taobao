# Taobao Product Recommendation Pipeline

Pipeline batch de recomendación sobre el dataset de Taobao, emulado en LocalStack con OpenTofu. Optimiza el _funnel_ de conversión de un e-commerce calculando la probabilidad de interacción usuario-ítem a partir de eventos de navegación.

## Quickstart

```bash
# 1. Levantar servicios (LocalStack + PostgreSQL + MLflow) — PowerShell de Windows, desde la raíz del repo
docker compose up -d --build

# 2. Aprovisionar infraestructura en LocalStack — WSL, desde el directorio terraform/
#    (alb_asg_enabled=false: ELBv2/ASG son features Pro del emulador)
tofu init
tofu apply -var="alb_asg_enabled=false"

# 3. Ejecutar el pipeline completo (inicialización → datos → features → modelo → inferencia) — WSL, desde la raíz del repo
uv run python init_db.py && uv run python data_bootstrap.py && uv run python pipeline_features.py && uv run python pipeline_training.py && uv run python pipeline_inference.py
```

## Documentación

| Documento | Contenido |
|-----------|-----------|
| [ARQUITECTURA.md](ARQUITECTURA.md) | Diseño conceptual: problema, 4 capas, stack, decisiones de implementación |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Guía operativa: orden de despliegue, comandos, input/output y racional de cada script |
| [PLANIFICACIÓN_Y_COSTOS.md](PLANIFICACIÓN_Y_COSTOS.md) | Cronograma por fases, estimación financiera (FinOps) y mediciones reales del pipeline |
| [INFRAESTRUCTURA.md](INFRAESTRUCTURA.md) | Inventario de servicios (continuos vs. efímeros) y escalabilidad |
| [tests/README.md](tests/README.md) | Suite de tests de integración por iteración |

## Resumen del pipeline

```
CSV (3.5 GB, 100M filas)
  └─ data_bootstrap.py      → s3://taobao-datalake/raw/ (Parquet particionado por event_date)
       └─ pipeline_features.py → s3://taobao-datalake/processed/ (splits train/val/test/infer)
            └─ pipeline_training.py → MLflow (modelo XGBoost + 6 métricas)
                 └─ pipeline_inference.py → PostgreSQL inference_results (Top-K por usuario)
                      └─ API FastAPI  → GET /recommendations/{user_id}

Orquestación: taobao_dag.py (Airflow) → data_bootstrap >> pipeline_features >> pipeline_training >> pipeline_inference
```

## Estructura del repositorio

```
api/                  Capa de servicio (FastAPI + Dockerfile)
terraform/            IaC modular (networking, security_groups, iam, s3, rds, alb_asg, compute)
data_bootstrap.py     Ingesta: CSV → Parquet en S3
pipeline_features.py  Feature store (split temporal anti-leakage)
pipeline_training.py  Entrenamiento XGBoost + registro en MLflow
pipeline_inference.py Inferencia batch Top-K → PostgreSQL
taobao_dag.py         DAG de Airflow (orquesta bootstrap → features → training → inference)
init_db.py            Esquema inference_results
init_mlflow_db.py     Base de datos mlflow
docker/               Imagen MLflow custom
tests/                Suite de integración
```
