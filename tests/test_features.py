import pytest

from data_bootstrap import run_bootstrap
from pipeline_features import (
    TRAIN_DAYS,
    VAL_DAYS,
    TEST_DAYS,
    INFER_DAYS,
    run_pipeline,
)

pytestmark = pytest.mark.integration

BUCKET = "taobao-datalake"
TEST_RAW = "raw_test_features"
TEST_PROC = "processed_test_features"
FIXTURE = "tests/fixtures/features_9day.csv"


@pytest.fixture(scope="module")
def pipeline_result(localstack_endpoint):
    run_bootstrap(
        csv_path=FIXTURE,
        out_dir="data/processed/parquet_features_test",
        bucket=BUCKET,
        prefix=TEST_RAW,
        endpoint=localstack_endpoint,
        workers=4,
        min_interactions=10,
    )
    return run_pipeline(
        bucket=BUCKET,
        raw_prefix=TEST_RAW,
        processed_prefix=TEST_PROC,
        endpoint=localstack_endpoint,
    )


def _keys(s3_client, prefix):
    resp = s3_client.list_objects_v2(Bucket=BUCKET, Prefix=prefix)
    return [o["Key"] for o in resp.get("Contents", [])]


def test_pipeline_writes_processed_partitions(s3_client, pipeline_result):
    keys = _keys(s3_client, f"{TEST_PROC}/")
    assert keys
    splits = {k.split("split=")[1].split("/")[0] for k in keys if "split=" in k}
    assert {"train", "val", "test", "infer"} <= splits


def test_train_val_test_infer_dates_disjoint(s3_client, pipeline_result):
    import duckdb

    con = duckdb.connect()
    con.execute("INSTALL httpfs")
    con.execute("LOAD httpfs")
    con.execute("SET s3_endpoint='172.21.16.1:4566'")
    con.execute("SET s3_access_key_id='test'")
    con.execute("SET s3_secret_access_key='test'")
    con.execute("SET s3_region='us-east-1'")
    con.execute("SET s3_url_style='path'")
    con.execute("SET s3_use_ssl=false")
    rows = con.execute(
        "SELECT split, array_agg(DISTINCT event_date) "
        f"FROM read_parquet('s3://{BUCKET}/{TEST_PROC}/**/*.parquet') "
        "GROUP BY split"
    ).fetchall()
    by_split = {r[0]: set(r[1]) for r in rows}
    assert by_split["train"] & by_split["val"] == set()
    assert by_split["train"] & by_split["test"] == set()
    assert by_split["train"] & by_split["infer"] == set()
    assert by_split["val"] & by_split["test"] == set()
    assert by_split["val"] & by_split["infer"] == set()
    assert by_split["test"] & by_split["infer"] == set()


def test_train_days_match_expected(s3_client, pipeline_result):
    import duckdb

    con = duckdb.connect()
    con.execute("INSTALL httpfs")
    con.execute("LOAD httpfs")
    con.execute("SET s3_endpoint='172.21.16.1:4566'")
    con.execute("SET s3_access_key_id='test'")
    con.execute("SET s3_secret_access_key='test'")
    con.execute("SET s3_region='us-east-1'")
    con.execute("SET s3_url_style='path'")
    con.execute("SET s3_use_ssl=false")
    days = con.execute(
        "SELECT DISTINCT day FROM read_parquet('s3://"
        f"{BUCKET}/{TEST_PROC}/split=train/*.parquet')"
    ).fetchall()
    assert {d[0] for d in days} == set(TRAIN_DAYS)


def test_val_test_infer_days_match_expected(s3_client, pipeline_result):
    import duckdb

    con = duckdb.connect()
    con.execute("INSTALL httpfs")
    con.execute("LOAD httpfs")
    con.execute("SET s3_endpoint='172.21.16.1:4566'")
    con.execute("SET s3_access_key_id='test'")
    con.execute("SET s3_secret_access_key='test'")
    con.execute("SET s3_region='us-east-1'")
    con.execute("SET s3_url_style='path'")
    con.execute("SET s3_use_ssl=false")
    val_days = {
        r[0]
        for r in con.execute(
            f"SELECT DISTINCT day FROM read_parquet('s3://{BUCKET}/{TEST_PROC}/split=val/*.parquet')"
        ).fetchall()
    }
    test_days = {
        r[0]
        for r in con.execute(
            f"SELECT DISTINCT day FROM read_parquet('s3://{BUCKET}/{TEST_PROC}/split=test/*.parquet')"
        ).fetchall()
    }
    infer_days = {
        r[0]
        for r in con.execute(
            f"SELECT DISTINCT day FROM read_parquet('s3://{BUCKET}/{TEST_PROC}/split=infer/*.parquet')"
        ).fetchall()
    }
    assert val_days == set(VAL_DAYS)
    assert test_days == set(TEST_DAYS)
    assert infer_days == set(INFER_DAYS)


def test_negatives_present_in_train_val_test(s3_client, pipeline_result):
    import duckdb

    con = duckdb.connect()
    con.execute("INSTALL httpfs")
    con.execute("LOAD httpfs")
    con.execute("SET s3_endpoint='172.21.16.1:4566'")
    con.execute("SET s3_access_key_id='test'")
    con.execute("SET s3_secret_access_key='test'")
    con.execute("SET s3_region='us-east-1'")
    con.execute("SET s3_url_style='path'")
    con.execute("SET s3_use_ssl=false")
    for split in ["train", "val", "test"]:
        count = con.execute(
            "SELECT COUNT(*) FROM read_parquet('s3://"
            f"{BUCKET}/{TEST_PROC}/split={split}/*.parquet') WHERE label = 0"
        ).fetchone()[0]
        assert count > 0


def test_positives_are_engagement(s3_client, pipeline_result):
    import duckdb

    con = duckdb.connect()
    con.execute("INSTALL httpfs")
    con.execute("LOAD httpfs")
    con.execute("SET s3_endpoint='172.21.16.1:4566'")
    con.execute("SET s3_access_key_id='test'")
    con.execute("SET s3_secret_access_key='test'")
    con.execute("SET s3_region='us-east-1'")
    con.execute("SET s3_url_style='path'")
    con.execute("SET s3_use_ssl=false")
    assert pipeline_result["train_pos"] > 0


def test_inference_has_no_label(s3_client, pipeline_result):
    import duckdb

    con = duckdb.connect()
    con.execute("INSTALL httpfs")
    con.execute("LOAD httpfs")
    con.execute("SET s3_endpoint='172.21.16.1:4566'")
    con.execute("SET s3_access_key_id='test'")
    con.execute("SET s3_secret_access_key='test'")
    con.execute("SET s3_region='us-east-1'")
    con.execute("SET s3_url_style='path'")
    con.execute("SET s3_use_ssl=false")
    labels = {
        r[0]
        for r in con.execute(
            f"SELECT DISTINCT label FROM read_parquet('s3://{BUCKET}/{TEST_PROC}/split=infer/*.parquet')"
        ).fetchall()
    }
    assert labels == {None}


def test_features_columns_present(s3_client, pipeline_result):
    import duckdb

    con = duckdb.connect()
    con.execute("INSTALL httpfs")
    con.execute("LOAD httpfs")
    con.execute("SET s3_endpoint='172.21.16.1:4566'")
    con.execute("SET s3_access_key_id='test'")
    con.execute("SET s3_secret_access_key='test'")
    con.execute("SET s3_region='us-east-1'")
    con.execute("SET s3_url_style='path'")
    con.execute("SET s3_use_ssl=false")
    describe = con.execute(
        "DESCRIBE SELECT * FROM read_parquet('s3://"
        f"{BUCKET}/{TEST_PROC}/split=train/*.parquet')"
    ).fetchall()
    cols = {r[0] for r in describe}
    expected = {
        "user_id",
        "item_id",
        "category_id",
        "label",
        "split",
        "user_item_freq",
        "user_cat_freq",
        "user_cat_eng",
        "intent_score",
        "item_popularity",
        "cat_popularity",
        "cat_target_enc",
        "lag_1",
        "lag_2",
    }
    assert expected <= cols