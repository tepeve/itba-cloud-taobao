import pytest

from pipeline_inference import run_inference

pytestmark = pytest.mark.integration

CATALOG_ITEMS = {100, 101, 102, 103, 104, 105, 106, 107, 108, 109}


@pytest.fixture(scope="module")
def inference_result(localstack_endpoint, mlflow_ready, mlflow_s3_env):
    return run_inference(
        endpoint=localstack_endpoint,
        mlflow_uri=mlflow_ready,
    )


def _inference_rows(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT user_id, recommended_items FROM inference_results ORDER BY user_id"
        )
        return cur.fetchall()


def test_inference_populates_inference_results(pg_conn, inference_result):
    rows = _inference_rows(pg_conn)
    assert rows
    assert inference_result["users"] == len(rows)


def test_recommended_items_is_list_of_objects(pg_conn, inference_result):
    rows = _inference_rows(pg_conn)
    assert rows
    for _, items in rows:
        assert isinstance(items, list)
        assert items
        for item in items:
            assert isinstance(item, dict)
            assert "item_id" in item
            assert "score" in item
            assert isinstance(item["item_id"], int)
            assert isinstance(item["score"], float)


def test_max_10_items_per_user(pg_conn, inference_result):
    rows = _inference_rows(pg_conn)
    for _, items in rows:
        assert len(items) <= 10


def test_recommended_items_are_valid_catalog_items(pg_conn, inference_result):
    rows = _inference_rows(pg_conn)
    for _, items in rows:
        assert {item["item_id"] for item in items} <= CATALOG_ITEMS


def test_upsert_updates_existing_user(localstack_endpoint, mlflow_ready, mlflow_s3_env, pg_conn):
    before = _inference_rows(pg_conn)
    run_inference(
        endpoint=localstack_endpoint,
        mlflow_uri=mlflow_ready,
    )
    after = _inference_rows(pg_conn)
    assert len(after) == len(before)
    assert {u for u, _ in after} == {u for u, _ in before}