import os

import duckdb
import mlflow
import mlflow.xgboost
import psycopg2
import psycopg2.extras

from pipeline_features import _configure_s3
from pipeline_training import FEATURE_COLS, EXPERIMENT_NAME, _configure_mlflow_env, load_split

BUCKET = os.environ.get("BUCKET", "taobao-datalake")
PROCESSED_PREFIX = os.environ.get("PROCESSED_PREFIX", "processed")
ENDPOINT = os.environ.get("LOCALSTACK_ENDPOINT", "http://localhost:4566")
MLFLOW_TRACKING_URI = os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5000")
TOP_K = int(os.environ.get("TOP_K", "10"))

PGHOST = os.environ.get("PGHOST", "localhost")
PGPORT = int(os.environ.get("PGPORT", "5432"))
PGUSER = os.environ.get("PGUSER", "taobao")
PGPASSWORD = os.environ.get("PGPASSWORD", "taobao123")
PGDATABASE = os.environ.get("PGDATABASE", "taobao")

UPSERT_SQL = """
INSERT INTO inference_results (user_id, recommended_items)
VALUES %s
ON CONFLICT (user_id) DO UPDATE
SET recommended_items = EXCLUDED.recommended_items,
    updated_at = CURRENT_TIMESTAMP
"""


def load_latest_model(mlflow_uri):
    mlflow.set_tracking_uri(mlflow_uri)
    experiment = mlflow.get_experiment_by_name(EXPERIMENT_NAME)
    if experiment is None:
        raise RuntimeError(f"Experimento {EXPERIMENT_NAME} no encontrado")
    runs = mlflow.search_runs(
        [experiment.experiment_id],
        order_by=["attributes.start_time DESC"],
        max_results=10,
    )
    finished = runs[runs["status"] == "FINISHED"]
    if finished.empty:
        raise RuntimeError(f"No hay runs FINISHED en {EXPERIMENT_NAME}")
    run_id = finished.iloc[0]["run_id"]
    model = mlflow.xgboost.load_model(f"runs:/{run_id}/model")
    return model, run_id


def load_inference(bucket, processed_prefix, endpoint):
    con = duckdb.connect()
    try:
        df = load_split(con, bucket, processed_prefix, "infer", endpoint)
    finally:
        con.close()
    return df


def predict_top_k(model, infer_df, top_k=TOP_K):
    x = infer_df[FEATURE_COLS]
    proba = model.predict_proba(x)[:, 1]
    scored = infer_df[["user_id", "item_id"]].copy()
    scored["score"] = proba
    top = (
        scored.sort_values(["user_id", "score"], ascending=[True, False])
        .groupby("user_id")
        .head(top_k)
    )
    grouped = top.groupby("user_id")["item_id"].apply(list).to_dict()
    return grouped


def persist_results(results, host=PGHOST, port=PGPORT, user=PGUSER, password=PGPASSWORD, dbname=PGDATABASE):
    conn = psycopg2.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        dbname=dbname,
    )
    try:
        rows = [(uid, psycopg2.extras.Json(items)) for uid, items in results.items()]
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                UPSERT_SQL,
                rows,
                template="(%s, %s)",
                page_size=1000,
            )
        conn.commit()
    finally:
        conn.close()
    return len(rows)


def run_inference(
    bucket=BUCKET,
    processed_prefix=PROCESSED_PREFIX,
    endpoint=ENDPOINT,
    mlflow_uri=MLFLOW_TRACKING_URI,
    top_k=TOP_K,
):
    _configure_mlflow_env(endpoint)
    model, run_id = load_latest_model(mlflow_uri)
    infer_df = load_inference(bucket, processed_prefix, endpoint)
    results = predict_top_k(model, infer_df, top_k=top_k)
    persisted = persist_results(results)
    return {
        "run_id": run_id,
        "users": len(results),
        "persisted": persisted,
    }


def main():
    result = run_inference()
    print(
        f"run_id={result['run_id']} usuarios={result['users']} "
        f"filas_persistidas={result['persisted']}"
    )


if __name__ == "__main__":
    main()