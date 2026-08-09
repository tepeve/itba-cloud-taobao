import pytest

pytestmark = pytest.mark.integration

DATALAKE = "taobao-datalake"


def test_datalake_bucket_exists(s3_client):
    s3_client.head_bucket(Bucket=DATALAKE)


def test_datalake_bucket_in_list(s3_client):
    names = [b["Name"] for b in s3_client.list_buckets()["Buckets"]]
    assert DATALAKE in names


def test_datalake_public_access_blocked(s3_client):
    pab = s3_client.get_public_access_block(Bucket=DATALAKE)
    block = pab["PublicAccessBlockConfiguration"]
    assert block["BlockPublicAcls"]
    assert block["BlockPublicPolicy"]
    assert block["IgnorePublicAcls"]
    assert block["RestrictPublicBuckets"]