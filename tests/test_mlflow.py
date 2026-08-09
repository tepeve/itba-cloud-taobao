import requests
import pytest

pytestmark = pytest.mark.integration

ARTIFACT_BUCKET = "taobao-mlflow-artifacts"


def test_mlflow_health_200(mlflow_ready):
    resp = requests.get(f"{mlflow_ready}/health", timeout=5)
    assert resp.status_code == 200


def test_mlflow_create_experiment_logs_metadata_and_artifact(
    mlflow_ready, mlflow_s3_env, mlflow_pg_conn, s3_client, tmp_path
):
    import mlflow

    mlflow.set_tracking_uri(mlflow_ready)
    experiment_name = "test-dummy-experiment"
    experiment = mlflow.set_experiment(experiment_name)

    with mlflow.start_run():
        mlflow.log_metric("dummy_metric", 42.0)
        artifact = tmp_path / "artifact.txt"
        artifact.write_text("contenido del artefacto")
        mlflow.log_artifact(str(artifact))

    with mlflow_pg_conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM experiments WHERE name = %s", (experiment_name,)
        )
        assert cur.fetchone()[0] > 0

    objects = s3_client.list_objects_v2(Bucket=ARTIFACT_BUCKET)
    keys = [o["Key"] for o in objects.get("Contents", [])]
    assert keys, "No hay artefactos registrados en el bucket mlflow"
    assert any("artifact.txt" in k for k in keys)


def test_mlflow_run_persisted_in_backend_store(mlflow_ready, mlflow_s3_env, mlflow_pg_conn):
    import mlflow

    mlflow.set_tracking_uri(mlflow_ready)
    experiment_name = "test-runs-persist"
    mlflow.set_experiment(experiment_name)

    with mlflow.start_run(run_name="run-uno"):
        mlflow.log_param("alpha", 0.5)

    with mlflow_pg_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM runs")
        assert cur.fetchone()[0] > 0
        cur.execute(
            "SELECT COUNT(*) FROM params WHERE value = '0.5'"
        )
        assert cur.fetchone()[0] > 0