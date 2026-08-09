from pathlib import Path

import duckdb
import pytest

from data_bootstrap import BUCKET, S3_PREFIX, run_bootstrap

pytestmark = pytest.mark.integration

DENSE_CSV = "tests/fixtures/dense.csv"
TEST_PARQUET_DIR = "data/processed/parquet_test"
EXPECTED_DATES = {"2017-11-25", "2017-11-26"}


@pytest.fixture(scope="module")
def bootstrap_result(localstack_endpoint):
    return run_bootstrap(
        csv_path=DENSE_CSV,
        out_dir=TEST_PARQUET_DIR,
        bucket=BUCKET,
        prefix=S3_PREFIX,
        endpoint=localstack_endpoint,
        workers=4,
        min_interactions=10,
    )


def _prefix_keys_contents(s3_client, prefix):
    resp = s3_client.list_objects_v2(Bucket=BUCKET, Prefix=prefix)
    return [o["Key"] for o in resp.get("Contents", [])]


def test_bootstrap_filters_users_with_few_interactions(bootstrap_result):
    assert bootstrap_result["qualified_users"] == 2


def test_bootstrap_writes_one_parquet_per_partition(bootstrap_result):
    assert bootstrap_result["parquet_files"] == len(EXPECTED_DATES)
    assert bootstrap_result["uploads"] == bootstrap_result["parquet_files"]


def test_bootstrap_writes_hive_partitions(s3_client, bootstrap_result):
    keys = _prefix_keys_contents(s3_client, f"{S3_PREFIX}/event_date=")
    assert keys
    for key in keys:
        assert "/event_date=" in key
        assert key.endswith(".parquet")


def test_bootstrap_partition_dates_match_expected(s3_client, bootstrap_result):
    keys = _prefix_keys_contents(s3_client, f"{S3_PREFIX}/event_date=")
    dates = {k.split("event_date=")[1].split("/")[0] for k in keys}
    assert dates == EXPECTED_DATES


def test_bootstrap_local_parquet_dir_created(bootstrap_result):
    base = Path(TEST_PARQUET_DIR)
    assert base.exists()
    assert list(base.rglob("*.parquet"))


def test_bootstrap_parquet_has_core_columns(bootstrap_result):
    files = list(Path(TEST_PARQUET_DIR).rglob("*.parquet"))
    assert files
    con = duckdb.connect()
    describe = con.execute(f"DESCRIBE SELECT * FROM '{files[0]}'").fetchall()
    col_names = {row[0] for row in describe}
    assert {"user_id", "item_id", "category_id", "behavior_type", "timestamp"} <= col_names


def test_bootstrap_parquet_contains_only_qualified_users(bootstrap_result):
    files = list(Path(TEST_PARQUET_DIR).rglob("*.parquet"))
    con = duckdb.connect()
    frames = []
    for f in files:
        frames.append(f"SELECT user_id FROM '{f}'")
    unioned = " UNION ALL ".join(frames)
    user_ids = {r[0] for r in con.execute(unioned).fetchall()}
    assert user_ids == {1, 3}
    assert 2 not in user_ids