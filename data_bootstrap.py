import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import boto3
import duckdb

RAW_CSV = os.environ.get("RAW_CSV", "data/raw/UserBehavior.csv")
PARQUET_DIR = os.environ.get("PARQUET_DIR", "data/processed/parquet")
DB_PATH = os.environ.get("DB_PATH", "data/tmp/bootstrap.duckdb")
BUCKET = "taobao-datalake"
S3_PREFIX = "raw"
MIN_INTERACTIONS = 10
TIMEZONE = "Asia/Shanghai"
DEFAULT_WORKERS = 4
COLUMN_SPEC = "columns={'user_id':'BIGINT','item_id':'BIGINT','category_id':'BIGINT','behavior_type':'VARCHAR','timestamp':'BIGINT'}"


def _read_csv(path):
    return f"read_csv('{path}', header=false, {COLUMN_SPEC})"


def get_s3_client(endpoint):
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


def filter_users(con, csv_path, min_interactions=MIN_INTERACTIONS):
    con.execute(
        f"CREATE TABLE qualified_users AS "
        f"SELECT user_id FROM {_read_csv(csv_path)} "
        f"GROUP BY user_id HAVING COUNT(*) >= {min_interactions}"
    )
    return con.execute("SELECT COUNT(*) FROM qualified_users").fetchone()[0]


def write_parquet(con, csv_path, out_dir):
    out_dir = Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    sql = (
        "COPY ("
        "  SELECT user_id, item_id, category_id, behavior_type, timestamp,"
        f"         strftime(to_timestamp(timestamp) AT TIME ZONE '{TIMEZONE}', '%Y-%m-%d') AS event_date"
        f"  FROM {_read_csv(csv_path)}"
        "  WHERE user_id IN (SELECT user_id FROM qualified_users)"
        f") TO '{out_dir.as_posix()}' (FORMAT PARQUET, PARTITION_BY event_date, OVERWRITE_OR_IGNORE TRUE)"
    )
    con.execute(sql)
    return len(list(out_dir.rglob("*.parquet")))


def _endpoint_with_defaults(endpoint):
    return endpoint or os.environ.get("LOCALSTACK_ENDPOINT", "http://localhost:4566")


def upload_all(endpoint, bucket, prefix, out_dir, workers=DEFAULT_WORKERS):
    base = Path(out_dir)
    files = list(base.rglob("*.parquet"))
    tasks = [(f, f"{prefix}/{f.relative_to(base).as_posix()}") for f in files]

    def worker(task):
        local_file, key = task
        s3 = get_s3_client(endpoint)
        s3.upload_file(str(local_file), bucket, key)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(worker, tasks))
    return len(tasks)


def run_bootstrap(
    csv_path=None,
    out_dir=None,
    bucket=BUCKET,
    prefix=S3_PREFIX,
    endpoint=None,
    workers=DEFAULT_WORKERS,
    min_interactions=MIN_INTERACTIONS,
):
    csv_path = csv_path or RAW_CSV
    out_dir = out_dir or PARQUET_DIR
    endpoint = _endpoint_with_defaults(endpoint)
    Path(out_dir).parent.mkdir(parents=True, exist_ok=True)
    db_path = Path(DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    con = duckdb.connect(str(db_path))
    try:
        qualified = filter_users(con, csv_path, min_interactions)
        parquet_files = write_parquet(con, csv_path, out_dir)
    finally:
        con.close()
    uploads = upload_all(endpoint, bucket, prefix, out_dir, workers)
    return {"qualified_users": qualified, "parquet_files": parquet_files, "uploads": uploads}


def main():
    result = run_bootstrap()
    print(
        f"Usuarios calificados: {result['qualified_users']} | "
        f"Parquet: {result['parquet_files']} | "
        f"Subidas a s3://{BUCKET}/{S3_PREFIX}/: {result['uploads']}"
    )


if __name__ == "__main__":
    main()