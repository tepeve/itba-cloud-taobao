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
    sg_ids = {g["GroupId"] for g in airflow_instance.get("SecurityGroups", [])}
    if not sg_ids:
        pytest.skip("LocalStack mock no materializa SecurityGroups en describe_instances")
    assert sg_airflow["GroupId"] in sg_ids


def test_airflow_instance_has_iam_profile(airflow_instance):
    if "IamInstanceProfile" not in airflow_instance:
        pytest.skip("LocalStack mock no materializa IamInstanceProfile en describe_instances")
    assert "Arn" in airflow_instance["IamInstanceProfile"]


def test_airflow_instance_user_data_references_dags_bucket(airflow_instance):
    raw = airflow_instance.get("UserData", "")
    if not raw:
        pytest.skip("LocalStack mock no materializa UserData en describe_instances")
    decoded = base64.b64decode(raw).decode("utf-8")
    assert "taobao-airflow-dags" in decoded
