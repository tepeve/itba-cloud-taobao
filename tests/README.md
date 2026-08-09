# Tests

Suite de verificación del pipeline de recomendación (Taobao). Cubre los recursos de infraestructura desplegados en LocalStack mediante OpenTofu, con cobertura creciente por cada iteración del proyecto.

## Estado actual

**Iteración 1 (Fundación de Arquitectura):** 31 tests de integración que validan VPC/subredes/route tables, los 4 Security Groups por lista blanca y la cadena IAM (rol → policy → instance profile).

**Iteración 2 (Bootstrap de Datos):** tests para el bucket `taobao-datalake` (existencia + bloqueo público) y para `data_bootstrap.py` (particiones Hive `event_date=`, fechas dentro del rango del dataset, columnas del Parquet).

Iteraciones 3 a 6 agregarán su propia cobertura (RDS, MLflow, modelado, API) conforme se implementen.

## Requisitos previos

1. **LocalStack corriendo** (desde PowerShell de Windows, en la raíz del repo):
   ```powershell
   docker compose up -d
   ```
2. **Infraestructura aplicada** (la suite consulta los recursos reales vía boto3, no los archivos de configuración):
   ```bash
   wsl -d Ubuntu -- bash -lc 'cd ~/itba/repo/taobao/terraform && tofu apply'
   ```
3. **Entorno de Python**: `.venv` de Linux (Python 3.12) gestionado por uv.

## Cómo correr los tests

El repo vive en WSL2 pero el shell del agente es PowerShell de Windows. Los tests usan el venv **Linux**, así que siempre se ejecutan dentro de WSL:

```bash
wsl -d Ubuntu -- bash -lc 'cd ~/itba/repo/taobao && uv run pytest tests/ -v'
```

Comandos útiles:

| Objetivo | Comando |
|----------|---------|
| Correr toda la suite | `uv run pytest tests/ -v` |
| Solo tests de integración | `uv run pytest tests/ -v -m integration` |
| Un archivo | `uv run pytest tests/test_vpc.py -v` |
| Un test puntual | `uv run pytest tests/test_iam.py::test_role_trust_ec2 -v` |
| Sin colores (logs limpios) | `uv run pytest tests/ -v --color=no` |

## Cómo se conecta a LocalStack

El endpoint se resuelve automáticamente con este orden de prioridad:

1. Variable de entorno `LOCALSTACK_ENDPOINT` (si está definida).
2. Auto-detección del gateway WSL2 (`ip route`), que es la IP del host Windows vista desde WSL — necesaria porque `tofu`/pytest corren en WSL y LocalStack es un contenedor en Windows.
3. Fallback `http://localhost:4566`.

Para forzar un endpoint explícito:

```bash
wsl -d Ubuntu -- bash -lc 'cd ~/itba/repo/taobao && LOCALSTACK_ENDPOINT=http://172.21.16.1:4566 uv run pytest tests/ -v'
```

## Estructura

```
tests/
  conftest.py              Fixtures compartidas (scope=session)
  test_vpc.py              Red: VPC, IGW, subredes, route tables
  test_security_groups.py  SG: alb, api_ec2, batch_ec2, rds
  test_iam.py              IAM: rol, policy S3, instance profile
```

### Fixtures (`conftest.py`)

- `localstack_endpoint` — resolución del endpoint (env → gateway WSL → localhost).
- `ec2_client`, `iam_client` — clientes `boto3` apuntados a LocalStack.
- `vpc`, `subnets`, `public_subnets`, `private_subnets`, `igw`, `route_tables` — descubiertos por tags estables (`Name=taobao-*`, `Project=taobao`).
- `security_groups` + `sg_alb`, `sg_api_ec2`, `sg_batch_ec2`, `sg_rds` — indexados por `GroupName`.
- `batch_role`, `s3_rw_policy`, `instance_profile` — identidad por nombre.

Los fixtures usan `scope="session"` (una sola consulta por sesión) y **descubren recursos por tags/nombres**, nunca por IDs fijos: las IDs cambian en cada `tofu apply`.

### Marcadores

- `integration` — requiere LocalStack corriendo e infraestructura aplicada. Todos los tests actuales lo usan.
- `unit` — reservado para iteraciones futuras (lógica Python pura, sin LocalStack).

## Configuración de pytest

Definida en `pyproject.toml`:

```toml
[tool.pytest.ini_options]
markers = [
    "integration: tests that require LocalStack running and terraform applied",
]
testpaths = ["tests"]
```

## Cobertura por iteración

| Iteración | Archivo | Alcance |
|-----------|---------|---------|
| 1 | `test_vpc.py`, `test_security_groups.py`, `test_iam.py` | Landing Zone |
| 2 | `test_s3_bucket.py`, `test_bootstrap.py` | Bucket `taobao-datalake` + ingesta/particionado |
| 3 | `test_rds.py` *(pendiente)* | Esquema `inference_results`, conectividad |
| 4 | `test_mlflow.py` *(pendiente)* | Salud del servidor, backend store, artifacts |
| 5 | `test_pipeline.py` *(pendiente)* | Burn-in, matriz de entrenamiento, validación OOT |
| 6 | `test_api.py` *(pendiente)* | Endpoint FastAPI, consulta a RDS |

## Gotchas

- **Sin test que toque LocalStack**: falla con errores de conexión (`EndpointConnectionError`). Verificá primero `docker ps` y que el contenedor `localstack_main` esté `Up` y saludable.
- **Recursos no aplicados**: los asserts de fixtures fallan con "no encontrada" si `tofu apply` no se ejecutó tras levantar LocalStack.
- **WSL ≠ Windows**: `uv run pytest` desde PowerShell de Windows falla porque el `.venv` es de Linux. Ejecutar siempre dentro de WSL (ver sección de ejecución).
