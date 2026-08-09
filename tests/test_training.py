import pytest

from pipeline_training import run_training

pytestmark = pytest.mark.integration

ARTIFACT_BUCKET = "taobao-mlflow-artifacts"
EXPERIMENT_NAME = "taobao_recommender"


@pytest.fixture(scope="module")
def training_result(localstack_endpoint, mlflow_ready, mlflow_s3_env):
    return run_training(
        endpoint=localstack_endpoint,
        mlflow_uri=mlflow_ready,
    )


def _mlflow_run(mlflow_ready, run_id):
    import mlflow

    mlflow.set_tracking_uri(mlflow_ready)
    return mlflow.get_run(run_id)


def test_training_creates_mlflow_run(mlflow_ready, training_result):
    import mlflow

    mlflow.set_tracking_uri(mlflow_ready)
    run = mlflow.get_run(training_result["run_id"])
    assert run is not None
    assert run.info.experiment_id


def test_training_run_in_experiment_persisted_in_pg(mlflow_pg_conn, training_result):
    with mlflow_pg_conn.cursor() as cur:
        cur.execute(
            "SELECT e.experiment_id FROM experiments e WHERE e.name = %s",
            (EXPERIMENT_NAME,),
        )
        row = cur.fetchone()
        assert row
        cur.execute(
            "SELECT COUNT(*) FROM runs WHERE experiment_id = %s AND run_uuid = %s",
            (row[0], training_result["run_id"]),
        )
        assert cur.fetchone()[0] == 1


def test_training_logs_test_metrics(mlflow_pg_conn, training_result):
    with mlflow_pg_conn.cursor() as cur:
        cur.execute(
            "SELECT key, value FROM latest_metrics WHERE run_uuid = %s",
            (training_result["run_id"],),
        )
        metrics = {k: v for k, v in cur.fetchall()}
    for key in [
        "test_auc_roc",
        "test_logloss",
        "test_precision",
        "test_recall",
        "test_f1",
        "test_accuracy",
    ]:
        assert key in metrics


def test_training_persists_model_artifact_in_s3(s3_client, mlflow_ready, training_result):
    objects = s3_client.list_objects_v2(Bucket=ARTIFACT_BUCKET)
    keys = [o["Key"] for o in objects.get("Contents", [])]
    assert keys, "No hay artefactos en el bucket mlflow"
    assert any(training_result["run_id"] in k for k in keys)


def test_training_artifact_has_xgboost_flavor(s3_client):
    objects = s3_client.list_objects_v2(Bucket=ARTIFACT_BUCKET)
    keys = [o["Key"] for o in objects.get("Contents", [])]
    mlmodel_keys = [k for k in keys if k.endswith("/artifacts/MLmodel")]
    assert mlmodel_keys, "No se encontro MLmodel en los artefactos"
    obj = s3_client.get_object(Bucket=ARTIFACT_BUCKET, Key=mlmodel_keys[-1])
    content = obj["Body"].read().decode()
    assert "xgboost" in content