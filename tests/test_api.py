import os

import pytest
from fastapi.testclient import TestClient

from api.main import app

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def client(pg_host):
    os.environ["PGHOST"] = pg_host
    os.environ.setdefault("PGPORT", "5432")
    os.environ.setdefault("PGUSER", "taobao")
    os.environ.setdefault("PGPASSWORD", "taobao123")
    os.environ.setdefault("PGDATABASE", "taobao")
    with TestClient(app) as c:
        yield c


def test_recommendations_200_schema(client):
    resp = client.get("/recommendations/1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == 1
    assert isinstance(body["recommended_items"], list)
    assert body["recommended_items"]
    for item in body["recommended_items"]:
        assert isinstance(item["item_id"], int)
        assert isinstance(item["score"], float)


def test_recommendations_404(client):
    resp = client.get("/recommendations/999999999")
    assert resp.status_code == 404


def test_recommendations_all_users_200(client):
    for user_id in [1, 2, 3]:
        resp = client.get(f"/recommendations/{user_id}")
        assert resp.status_code == 200