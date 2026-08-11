import pytest

pytestmark = pytest.mark.integration


def test_role_exists(batch_role):
    assert batch_role["RoleName"] == "taobao-batch-role"
    assert batch_role["Arn"].startswith("arn:aws:iam::")


def test_role_trust_ec2(batch_role):
    document = batch_role["AssumeRolePolicyDocument"]
    statements = document["Statement"]
    assert any(
        s["Effect"] == "Allow"
        and s.get("Principal", {}).get("Service") == "ec2.amazonaws.com"
        and s.get("Action") == "sts:AssumeRole"
        for s in statements
    )


def test_policy_exists(s3_rw_policy):
    assert s3_rw_policy["Statement"]


def test_policy_s3_actions(s3_rw_policy):
    actions = s3_rw_policy["Statement"][0]["Action"]
    for required in ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]:
        assert required in actions


def test_policy_bucket_resources(s3_rw_policy):
    resources = s3_rw_policy["Statement"][0]["Resource"]
    for bucket in ["taobao-datalake", "taobao-mlflow-artifacts"]:
        assert f"arn:aws:s3:::{bucket}" in resources
        assert f"arn:aws:s3:::{bucket}/*" in resources


def test_instance_profile_exists(instance_profile):
    assert instance_profile["InstanceProfileName"] == "taobao-batch-instance-profile"


def test_instance_profile_linked_to_role(instance_profile, batch_role):
    roles = instance_profile["Roles"]
    assert any(r["RoleName"] == batch_role["RoleName"] for r in roles)


def test_ssm_parameter_exists(ssm_parameter):
    assert ssm_parameter["Name"] == "/taobao/prod/rds_password"
    assert ssm_parameter["Type"] == "SecureString"


def test_ssm_policy_allows_get_and_kms(ssm_read_policy):
    actions = ssm_read_policy["Statement"][0]["Action"]
    assert "ssm:GetParameter" in actions
    assert "kms:Decrypt" in actions


def test_s3_policy_includes_airflow_dags_bucket(s3_rw_policy):
    resources = s3_rw_policy["Statement"][0]["Resource"]
    assert "arn:aws:s3:::taobao-airflow-dags" in resources
    assert "arn:aws:s3:::taobao-airflow-dags/*" in resources
