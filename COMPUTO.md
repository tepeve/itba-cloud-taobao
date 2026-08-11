# Capa de Cómputo — Estado y Plan de Implementación

## Resumen ejecutivo

La capa de cómputo del pipeline está **materializada en LocalStack** bajo el paradigma IaaS orquestado por Airflow (Sprint 2, rama `dev-compute-airflow-vpc`). La persistencia (S3, red con NAT Gateway y VPC Endpoint S3, Security Groups, IAM), el bootstrap, el feature store, el modelado y la inferencia están implementados y verificados. El orquestador Apache Airflow se declara como instancia EC2 (`aws_instance`) y el DAG `taobao_dag.py` sustituye la ejecución manual secuencial de los scripts.

## Estado actual (verificado)

| Componente de cómputo | ¿Materializado en LocalStack? | Dónde corre realmente |
|---|---|---|
| Instancia EC2 orquestadora (Airflow) | **Sí** (`aws_instance`, mock VM) | Declarada en IaC; `describe_instances` la muestra `running` |
| Instancias de servicio (FastAPI) | No — **gated** (`alb_asg_enabled=false` en LocalStack) | Definido en IaC; en local se sirve vía `uvicorn`/`TestClient` |
| Launch Template (API) | No — **gated** | Definido en IaC (`templatefile` de `init_api.sh.tpl`) |
| Auto Scaling Group | No — **gated** | Definido en IaC |
| Application Load Balancer | No — **gated** (ELBv2 es Pro) | Definido en IaC |
| Lambda function | **No** (servicio no habilitado en `SERVICES`) | — |

### Qué existe en LocalStack (Sprint 2)

- `aws_instance` `taobao-airflow` (módulo `compute`) — instancia simbólica en subred privada con `sg_airflow`, `iam_instance_profile` batch y `user_data = templatefile(init_airflow.sh.tpl)`. **Materializada** (mock VM).
- `aws_eip` + `aws_nat_gateway` — salida a internet para las instancias privadas (descarga de dependencias durante `user_data`).
- `aws_vpc_endpoint` (Gateway S3) — tráfico DuckDB→S3 por la RT privada, evitando costos de NAT.
- `taobao-airflow-dags` bucket (módulo `s3`) — repo de DAGs/scripts sincronizado por la instancia Airflow.
- `aws_ssm_parameter` `/taobao/prod/rds_password` (`SecureString`) + policy `ssm:GetParameter`+`kms:Decrypt` — secretos declarativos, sin credenciales en texto plano.
- `aws_iam_instance_profile` (`taobao-batch-instance-profile`) — perfil común orquestador + instancias de servicio.

### Gated (definidos, no creados en LocalStack)

- `aws_lb` (ALB público), `aws_lb_target_group`, `aws_lb_listener`, `aws_launch_template`, `aws_autoscaling_group` — módulo `alb_asg`. ELBv2 y Auto Scaling son features **Pro** de LocalStack community (no implementadas).
- `aws_db_instance` (RDS) — **gated** por la misma razón (RDS es Pro). La base real es el sidecar `postgres:15` del compose.

## Restricciones del emulador

LocalStack **community** (`localstack/localstack:3.5.0`) tiene soporte parcial:

| Servicio | Soporte en community | Uso en el proyecto |
|----------|----------------------|--------------------|
| EC2 (VPC, subredes, SG, IAM, `aws_instance`) | **Sí** | Red/SG/IAM/orquestador materializados |
| NAT Gateway, VPC Endpoint (Gateway) | **Sí** (CRUD) | Materializados |
| SSM (Parameter Store) | **Sí** (Hobby) | Secretos materializados |
| ELBv2, Auto Scaling, Launch Template | **No** (Pro) | Gated (`alb_asg_enabled`) |
| RDS | **No** (Pro) | Gated + sidecar postgres |
| Lambda | Sí (básico), pero no habilitado en `SERVICES` | No usado |

El cómputo real del pipeline corre en el host WSL (DuckDB/XGBoost/uvicorn); LocalStack emula el plano de control (API de AWS). La instancia EC2 orquestadora es **simbólica**: en mock VM manager LocalStack no procesa `user_data` ni arranca Airflow — representa el plano de control declarativo. En AWS real, `user_data` instalaría Docker y levantaría el contenedor `apache/airflow:2.9.0` (LocalExecutor).

## Arquitectura de cómputo (Sprint 2)

- **Orquestador (Airflow):** `aws_instance` `taobao-airflow` en subred privada. `user_data` (`init_airflow.sh.tpl`): instala Docker, sincroniza DAGs desde `taobao-airflow-dags` (cron cada 5 min), resuelve la contraseña DB vía SSM y levanta `apache/airflow:2.9.0` con `LocalExecutor` apuntando al esquema `airflow` en RDS.
- **Capa de servicio (FastAPI):** Launch Template (`init_api.sh.tpl`): instala Docker, sincroniza `api/` desde `taobao-airflow-dags`, compila `taobao-api:latest` y ejecuta el contenedor con `--network host` y credenciales RDS inyectadas. En LocalStack el Launch Template/ASG/ALB quedan gated; en local la API se prueba con `TestClient`.
- **DAG `taobao_dag.py`:** `BashOperator` con `env=env_vars` (BUCKET, MLFLOW_TRACKING_URI, PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE, LOCALSTACK_ENDPOINT) y topología `t_bootstrap >> t_features >> t_training >> t_inference`. Los scripts analíticos leen estas variables **sin fallbacks `localhost`** (inyección única de contexto vía Airflow).

## Cómo se activarían los recursos gated en AWS real

```bash
# En AWS real (no LocalStack): materializa RDS, ALB, Target Group, Launch Template y ASG
wsl -d Ubuntu -- bash -lc 'cd ~/itba/repo/taobao/terraform && tofu apply -var="rds_enabled=true" -var="alb_asg_enabled=true"'
```

En ese despliegue, el cómputo quedaría:
- **Orquestador**: `aws_instance` Airflow con `taobao-batch-instance-profile` y `init_airflow.sh.tpl` (Docker + Airflow LocalExecutor).
- **API**: ASG (min 2 / max 4) en subredes privadas con Launch Template `init_api.sh.tpl`, detrás del ALB público (puerto 80 → 8000).

> En LocalStack, `tofu apply` se corre con **`-var alb_asg_enabled=false`** (y `rds_enabled=false` por defecto): el default declarativo de `alb_asg_enabled` es `true`, pero ELBv2/ASG no son materializables en community.
