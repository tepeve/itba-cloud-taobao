import base64

import pytest

pytestmark = pytest.mark.integration


def test_asg_exists(asg_available, autoscaling_client):
    if not asg_available:
        pytest.skip("servicio ASG no disponible en LocalStack community")
    resp = autoscaling_client.describe_auto_scaling_groups()
    groups = resp["AutoScalingGroups"]
    assert any("taobao" in g["AutoScalingGroupName"] for g in groups)


def test_asg_uses_private_subnets(asg_available, autoscaling_client, private_subnets):
    if not asg_available:
        pytest.skip("servicio ASG no disponible en LocalStack community")
    resp = autoscaling_client.describe_auto_scaling_groups()
    for g in resp["AutoScalingGroups"]:
        if "taobao" in g["AutoScalingGroupName"]:
            subnet_ids = set(g["VPCZoneIdentifier"].split(","))
            pvt_ids = {s["SubnetId"] for s in private_subnets}
            assert subnet_ids.issubset(pvt_ids)
            return
    pytest.fail("ASG taobao no encontrado")


def test_asg_has_target_groups(asg_available, autoscaling_client):
    if not asg_available:
        pytest.skip("servicio ASG no disponible en LocalStack community")
    resp = autoscaling_client.describe_auto_scaling_groups()
    for g in resp["AutoScalingGroups"]:
        if "taobao" in g["AutoScalingGroupName"]:
            assert g["TargetGroupARNs"]
            return
    pytest.fail("ASG taobao no encontrado")


def test_launch_template_has_user_data_with_dags_bucket(launch_template, ec2_client):
    version = launch_template["LatestVersionNumber"]
    resp = ec2_client.describe_launch_template_versions(
        LaunchTemplateId=launch_template["LaunchTemplateId"],
        Versions=[str(version)]
    )
    data = resp["LaunchTemplateVersions"][0]["LaunchTemplateData"]
    raw = data.get("UserData", "")
    decoded = base64.b64decode(raw).decode("utf-8")
    assert "taobao-airflow-dags" in decoded
