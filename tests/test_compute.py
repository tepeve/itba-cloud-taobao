import base64

import pytest

pytestmark = pytest.mark.integration


def test_airflow_instance_exists(airflow_instance):
    assert airflow_instance["State"]["Name"] == "running"


def test_airflow_instance_in_private_subnet(airflow_instance, private_subnets):
    subnet_ids = {s["SubnetId"] for s in private_subnets}
    assert airflow_instance["SubnetId"] in subnet_ids
    assert "PublicIpAddress" not in airflow_instance


def test_airflow_instance_uses_sg_airflow(airflow_instance, sg_airflow):
    sg_ids = {g["GroupId"] for g in airflow_instance["SecurityGroups"]}
    assert sg_airflow["GroupId"] in sg_ids


def test_airflow_instance_has_iam_profile(airflow_instance):
    profile = airflow_instance["IamInstanceProfile"]
    assert "Arn" in profile
    assert "taobao" in profile["Arn"]


def test_airflow_instance_user_data_references_dags_bucket(airflow_instance):
    raw = airflow_instance.get("UserData", "")
    decoded = base64.b64decode(raw).decode("utf-8")
    assert "taobao-airflow-dags" in decoded
