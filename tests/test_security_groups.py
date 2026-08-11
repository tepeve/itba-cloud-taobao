import pytest

pytestmark = pytest.mark.integration


def _ingress_permissions(sg):
    return sg.get("IpPermissions", [])


def _egress_permissions(sg):
    return sg.get("IpPermissionsEgress", [])


def _rule_with_port(permissions, port):
    return [p for p in permissions if p.get("FromPort") == port and p.get("ToPort") == port]


def test_sg_alb_exists(sg_alb):
    assert sg_alb["GroupName"] == "taobao-alb-sg"


def test_sg_alb_ingress_80_from_anywhere(sg_alb):
    rules = _rule_with_port(_ingress_permissions(sg_alb), 80)
    assert rules
    ranges = rules[0].get("IpRanges", [])
    assert any(r["CidrIp"] == "0.0.0.0/0" for r in ranges)


def test_sg_alb_no_ingress_8000(sg_alb):
    rules = _rule_with_port(_ingress_permissions(sg_alb), 8000)
    assert not rules


def test_sg_api_ec2_ingress_8000_from_alb(sg_api_ec2, sg_alb):
    rules = _rule_with_port(_ingress_permissions(sg_api_ec2), 8000)
    assert rules
    pairs = rules[0].get("UserIdGroupPairs", [])
    assert any(p["GroupId"] == sg_alb["GroupId"] for p in pairs)


def test_sg_api_ec2_ingress_not_from_cidr(sg_api_ec2):
    rules = _rule_with_port(_ingress_permissions(sg_api_ec2), 8000)
    assert rules
    assert not rules[0].get("IpRanges")


def test_sg_airflow_ingress_internal_8080_5000(sg_airflow):
    rules = {p["FromPort"]: p for p in _ingress_permissions(sg_airflow)}
    assert 8080 in rules and 5000 in rules
    for port in (8080, 5000):
        ranges = rules[port].get("IpRanges", [])
        assert any(r["CidrIp"] == "10.0.0.0/16" for r in ranges)


def test_sg_airflow_egress_all(sg_airflow):
    egress = _egress_permissions(sg_airflow)
    assert any(p.get("IpProtocol") == "-1" for p in egress)


def test_sg_rds_ingress_5432_from_airflow_and_api(sg_rds, sg_api_ec2, sg_airflow):
    rules = _rule_with_port(_ingress_permissions(sg_rds), 5432)
    assert rules
    pairs = {p["GroupId"] for p in rules[0].get("UserIdGroupPairs", [])}
    assert pairs == {sg_api_ec2["GroupId"], sg_airflow["GroupId"]}


def test_sg_rds_no_other_ingress(sg_rds):
    rules = _rule_with_port(_ingress_permissions(sg_rds), 5432)
    assert len(rules) == len(_ingress_permissions(sg_rds))
