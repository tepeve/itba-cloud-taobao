import os

import duckdb
import mlflow
import mlflow.xgboost
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    log_loss,
    precision_score,
    recall_score,
    roc_auc_score,
)
from xgboost import XGBClassifier

from pipeline_features import _configure_s3

BUCKET = os.environ.get("BUCKET", "taobao-datalake")
PROCESSED_PREFIX = os.environ.get("PROCESSED_PREFIX", "processed")
ENDPOINT = os.environ.get("LOCALSTACK_ENDPOINT", "http://localhost:4566")
MLFLOW_TRACKING_URI = os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5000")
EXPERIMENT_NAME = "taobao_recommender"

FEATURE_COLS = [
    "user_item_freq",
    "user_cat_freq",
    "user_cat_eng",
    "intent_score",
    "item_popularity",
    "cat_popularity",
    "cat_target_enc",
    "lag_1",
    "lag_2",
]


def _processed_url(bucket, prefix, split):
    return f"s3://{bucket}/{prefix}/split={split}/*.parquet"


def load_split(con, bucket, prefix, split, endpoint):
    _configure_s3(con, endpoint)
    df = con.execute(
        f"SELECT * FROM read_parquet('{_processed_url(bucket, prefix, split)}')"
    ).fetchdf()
    return df


def _configure_mlflow_env(endpoint):
    os.environ["MLFLOW_S3_ENDPOINT_URL"] = f"http://{_s3_host(endpoint)}"
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")


def _s3_host(endpoint):
    return endpoint.replace("http://", "").replace("https://", "").rstrip("/")


def run_training(
    bucket=BUCKET,
    processed_prefix=PROCESSED_PREFIX,
    endpoint=ENDPOINT,
    mlflow_uri=MLFLOW_TRACKING_URI,
):
    _configure_mlflow_env(endpoint)
    con = duckdb.connect()
    try:
        train_df = load_split(con, bucket, processed_prefix, "train", endpoint)
        val_df = load_split(con, bucket, processed_prefix, "val", endpoint)
        test_df = load_split(con, bucket, processed_prefix, "test", endpoint)
    finally:
        con.close()

    X_train, y_train = train_df[FEATURE_COLS], train_df["label"]
    X_val, y_val = val_df[FEATURE_COLS], val_df["label"]
    X_test, y_test = test_df[FEATURE_COLS], test_df["label"]

    mlflow.set_tracking_uri(mlflow_uri)
    mlflow.set_experiment(EXPERIMENT_NAME)
    mlflow.xgboost.autolog(log_models=True)

    model = XGBClassifier(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.1,
        eval_metric="logloss",
        early_stopping_rounds=10,
        random_state=42,
    )

    with mlflow.start_run() as run:
        model.fit(
            X_train,
            y_train,
            eval_set=[(X_val, y_val)],
            verbose=False,
        )
        y_prob = model.predict_proba(X_test)[:, 1]
        y_pred = (y_prob >= 0.5).astype(int)
        test_auc = roc_auc_score(y_test, y_prob)
        test_logloss = log_loss(y_test, y_prob)
        test_precision = precision_score(y_test, y_pred, zero_division=0)
        test_recall = recall_score(y_test, y_pred, zero_division=0)
        test_f1 = f1_score(y_test, y_pred, zero_division=0)
        test_accuracy = accuracy_score(y_test, y_pred)
        mlflow.log_metrics({
            "test_auc_roc": test_auc,
            "test_logloss": test_logloss,
            "test_precision": test_precision,
            "test_recall": test_recall,
            "test_f1": test_f1,
            "test_accuracy": test_accuracy,
        })
        mlflow.xgboost.log_model(model, "model")
        run_id = run.info.run_id

    return {
        "run_id": run_id,
        "test_auc_roc": test_auc,
        "test_logloss": test_logloss,
        "test_precision": test_precision,
        "test_recall": test_recall,
        "test_f1": test_f1,
        "test_accuracy": test_accuracy,
        "n_train": len(X_train),
        "n_val": len(X_val),
        "n_test": len(X_test),
    }


def main():
    result = run_training()
    print(
        f"run_id={result['run_id']} "
        f"test_auc_roc={result['test_auc_roc']:.4f} "
        f"test_logloss={result['test_logloss']:.4f} "
        f"test_precision={result['test_precision']:.4f} "
        f"test_recall={result['test_recall']:.4f} "
        f"test_f1={result['test_f1']:.4f} "
        f"test_accuracy={result['test_accuracy']:.4f} "
        f"n_train={result['n_train']} n_val={result['n_val']} n_test={result['n_test']}"
    )


if __name__ == "__main__":
    main()