import pytest

pytestmark = pytest.mark.integration


def _route_table_by_name(route_tables, name):
    return next(rt for rt in route_tables if rt["Tags"] and any(t["Key"] == "Name" and t["Value"] == name for t in rt["Tags"]))


def test_vpc_exists(vpc):
    assert vpc["VpcId"].startswith("vpc-")


def test_vpc_cidr(vpc):
    assert vpc["CidrBlock"] == "10.0.0.0/16"


def test_vpc_dns_support(vpc_dns_support):
    assert vpc_dns_support


def test_vpc_dns_hostnames(vpc_dns_hostnames):
    assert vpc_dns_hostnames


def test_igw_attached(vpc, igw):
    attachments = igw["Attachments"]
    assert any(a["VpcId"] == vpc["VpcId"] and a["State"] == "available" for a in attachments)


def test_two_public_subnets(public_subnets):
    assert len(public_subnets) == 2


def test_two_private_subnets(private_subnets):
    assert len(private_subnets) == 2


def test_public_subnets_map_public_ip(public_subnets):
    assert all(s["MapPublicIpOnLaunch"] for s in public_subnets)


def test_private_subnets_no_public_ip(private_subnets):
    assert all(not s["MapPublicIpOnLaunch"] for s in private_subnets)


def test_public_subnets_across_two_azs(public_subnets):
    azs = {s["AvailabilityZone"] for s in public_subnets}
    assert azs == {"us-east-1a", "us-east-1b"}


def test_private_subnets_across_two_azs(private_subnets):
    azs = {s["AvailabilityZone"] for s in private_subnets}
    assert azs == {"us-east-1a", "us-east-1b"}


def test_public_route_table_has_default_to_igw(route_tables, igw):
    pub_rt = _route_table_by_name(route_tables, "taobao-pub-rt")
    routes = pub_rt["Routes"]
    default = next(r for r in routes if r["DestinationCidrBlock"] == "0.0.0.0/0")
    assert default["GatewayId"] == igw["InternetGatewayId"]


def test_private_route_table_default_to_nat(route_tables):
    priv_rt = _route_table_by_name(route_tables, "taobao-priv-rt")
    default = next(r for r in priv_rt["Routes"] if r["DestinationCidrBlock"] == "0.0.0.0/0")
    assert default.get("NatGatewayId")


def test_nat_gateway_has_eip(nat_gateway):
    addresses = nat_gateway["NatGatewayAddresses"]
    assert any(a.get("AllocationId") for a in addresses)


def test_public_subnets_associated_to_public_rt(route_tables, public_subnets):
    pub_rt = _route_table_by_name(route_tables, "taobao-pub-rt")
    associated = {
        a["SubnetId"] for a in pub_rt["Associations"] if "SubnetId" in a
    }
    subnet_ids = {s["SubnetId"] for s in public_subnets}
    assert associated == subnet_ids


def test_private_subnets_associated_to_private_rt(route_tables, private_subnets):
    priv_rt = _route_table_by_name(route_tables, "taobao-priv-rt")
    associated = {
        a["SubnetId"] for a in priv_rt["Associations"] if "SubnetId" in a
    }
    subnet_ids = {s["SubnetId"] for s in private_subnets}
    assert associated == subnet_ids
