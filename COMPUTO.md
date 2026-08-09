# Capa de Cómputo — Estado y Plan de Implementación

## Resumen ejecutivo

La arquitectura del proyecto define 4 capas lógicas. La **persistencia** (S3, red, Security Groups, IAM), el **bootstrap de datos** y el **pipeline analítico** están implementados y verificados en LocalStack. Sin embargo, **la capa de cómputo (EC2/Lambda) aún no está materializada**: los scripts del pipeline (`data_bootstrap.py`, `pipeline_features.py`, `pipeline_training.py`, `pipeline_inference.py`) corren en el host local (WSL) y no existe ninguna instancia de cómputo emulada en LocalStack.

Este documento registra ese estado, las razones técnicas y los enfoques propuestos para implementarla en futuras iteraciones.

## Estado actual (verificado)

| Componente de cómputo | ¿Materializado en LocalStack? | Dónde corre realmente |
|---|---|---|
| Instancia EC2 batch | **No** | Host WSL (scripts Python con DuckDB/XGBoost) |
| Instancia EC2 API | **No** | Host WSL (`uvicorn`) |
| Lambda function | **No** (servicio no habilitado en `SERVICES`) | — |
| Launch Template (API) | No — **gated** (`alb_asg_enabled=false`) | Definido en IaC, no creado |
| Auto Scaling Group | No — **gated** | Definido en IaC, no creado |
| Application Load Balancer | No — **gated** | Definido en IaC, no creado |

### Qué sí existe (relacionado con cómputo)

- `aws_iam_instance_profile` (`taobao-batch-instance-profile`) — Iteración 1. Empaqueta el rol `taobao-batch-role` que una instancia EC2 batch asumiría para acceder a S3. **Materializado** en LocalStack.
- `aws_launch_template` + `aws_autoscaling_group` + `aws_lb` — Iteración 6, módulo `alb_asg`. **Definidos pero gated** porque ELBv2 y Auto Scaling son features **Pro** de LocalStack (no implementadas en community).
- `aws_db_instance` (módulo `rds`) — **gated** por la misma razón (RDS es Pro).

## Por qué no hay cómputo emulado (restricciones del emulador)

LocalStack **community** (la edición usada, `localstack/localstack:3.5.0`) tiene soporte parcial:

| Servicio | Soporte en community | Uso en el proyecto |
|----------|----------------------|--------------------|
| EC2 (VPC, subredes, SG, IAM, `aws_instance`) | **Sí** | Red/SG/IAM materializados |
| ELBv2, Auto Scaling, Launch Template | **No** (Pro) | Gated |
| RDS | **No** (Pro) | Gated + sidecar postgres |
| Lambda | Sí (básico), pero no habilitado en `SERVICES` | No usado |
| DynamoDB | Sí, pero no habilitado en `SERVICES` | No usado (PostgreSQL es el key-value store) |

La decisión del proyecto fue: **las bases y el cómputo real corren como servicios locales** (contenedor `taobao_postgres` + scripts en el host), mientras LocalStack emula el plano de control (API de AWS). Los recursos "gated" (`rds_enabled`, `alb_asg_enabled`) quedan declarados en IaC, correctos para AWS real, pero no se crean en LocalStack.

## Enfoques de implementación propuestos (futuras iteraciones)

### Enfoque A — Instancia EC2 batch materializable (recomendado)

LocalStack community **sí soporta `aws_instance`** (verificado: `describe_images` devuelve AMIs). Se podría crear un módulo `terraform/modules/ec2` con:

- `aws_instance` batch (AMI `amzn2`, `t3.micro`) en subred privada, con `iam_instance_profile = taobao-batch-instance-profile`, `vpc_security_group_ids = [sg_batch_ec2]`.
- `user_data` que ejecute el pipeline (o un script que apunte a los jobs batch).

**Ventajas:** visible y verificable en `tofu apply` y tests (`describe_instances`); sin flags Pro. Es el cómputo batch del enunciado ("instancias EC2 efímeras con Instance Profiles").

**Limitaciones:** LocalStack no ejecuta realmente el software dentro de la instancia; la instancia es simbólica (estado `running`), y `user_data` no se procesa. El cómputo real seguiría corriendo en el host; la instancia representaría el plano de control.

### Enfoque B — Instancia EC2 para la API (servicio)

Similar al A, pero para la capa de servicio: una `aws_instance` (o el Launch Template ya definido) que represente la instancia que sirve FastAPI. En AWS real se materializaría vía ASG + ALB (ya declarado en `alb_asg`).

### Enfoque C — Lambda para procesamiento batch

Habilitar `lambda` en `SERVICES` (`docker-compose.yml`) y agregar una `aws_lambda_function` que ejecute un job de procesamiento. LocalStack community soporta Lambda básica (requiere reiniciar el contenedor con `SERVICES` actualizado). Más fiel al "serverless" pero cambia el diseño actual (que es batch por EC2, no serverless).

### Enfoque D — Documentar como está (mínimo)

Reconocer explícitamente que el cómputo es local por emulación y que en AWS real se materializaría con EC2/ASG (ya declarado). No requiere código nuevo. Es la opción adoptada hasta la fecha.

## Recomendación

Para el examen, el **Enfoque A** es el más valioso: materializar al menos una `aws_instance` batch en LocalStack (soporte real) para que exista una unidad de cómputo verificable, manteniendo el resto gated para AWS real. Si se prioriza el alcance, combinar A (batch) + reutilizar el `alb_asg` gated (API) documentando su activación con `-var="alb_asg_enabled=true"`.

## Cómo se activarían los recursos gated en AWS real

```bash
# En AWS real (no LocalStack): materializa RDS, ALB, Target Group, Launch Template y ASG
wsl -d Ubuntu -- bash -lc 'cd ~/itba/repo/taobao/terraform && tofu apply -var="rds_enabled=true" -var="alb_asg_enabled=true"'
```

En ese despliegue, el cómputo quedaría:
- **Batch**: instancias EC2 efímeras con `taobao-batch-instance-profile` (por implementar, Enfoque A).
- **API**: ASG (min 2 / max 4) en subredes privadas, detrás del ALB público (ya definido).
