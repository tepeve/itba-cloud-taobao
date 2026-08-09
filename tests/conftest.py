import os
import subprocess

import boto3
import pytest

PROJECT = "taobao"
REGION = "us-east-1"


def _wsl_gateway_endpoint():
    if os.name != "nt":
        return None
    try:
        result = subprocess.run(
            ["wsl", "-d", "Ubuntu", "--", "bash", "-lc", "ip route | grep default | awk '{print $3}'"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            gw = result.stdout.strip()
            if gw:
                return f"http://{gw}:4566"
    except (FileNotFoundError, subprocess.SubprocessError):
        pass
    return None


def _wsl_gateway_ip():
    if os.name != "nt":
        return None
    try:
        result = subprocess.run(
            ["wsl", "-d", "Ubuntu", "--", "bash", "-lc", "ip route | grep default | awk '{print $3}'"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            gw = result.stdout.strip()
            if gw:
                return gw
    except (FileNotFoundError, subprocess.SubprocessError):
        pass
    return None


@pytest.fixture(scope="session")
def localstack_endpoint():
    return (
        os.environ.get("LOCALSTACK_ENDPOINT")
        or _wsl_gateway_endpoint()
        or "http://localhost:4566"
    )


@pytest.fixture(scope="session")
def ec2_client(localstack_endpoint):
    return boto3.client(
        "ec2",
        endpoint_url=localstack_endpoint,
        region_name=REGION,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


@pytest.fixture(scope="session")
def iam_client(localstack_endpoint):
    return boto3.client(
        "iam",
        endpoint_url=localstack_endpoint,
        region_name=REGION,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


@pytest.fixture(scope="session")
def s3_client(localstack_endpoint):
    return boto3.client(
        "s3",
        endpoint_url=localstack_endpoint,
        region_name=REGION,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


@pytest.fixture(scope="session")
def rds_client(localstack_endpoint):
    return boto3.client(
        "rds",
        endpoint_url=localstack_endpoint,
        region_name=REGION,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


@pytest.fixture(scope="session")
def rds_available(rds_client):
    try:
        rds_client.describe_db_instances()
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def pg_host():
    return os.environ.get("PGHOST") or _wsl_gateway_ip() or "localhost"


@pytest.fixture(scope="function")
def pg_conn(pg_host):
    import psycopg2

    conn = psycopg2.connect(
        host=pg_host,
        port=int(os.environ.get("PGPORT", "5432")),
        user=os.environ.get("PGUSER", "taobao"),
        password=os.environ.get("PGPASSWORD", "taobao123"),
        dbname=os.environ.get("PGDATABASE", "taobao"),
    )
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def mlflow_uri(pg_host):
    return f"http://{pg_host}:5000"


@pytest.fixture(scope="session")
def mlflow_s3_env(pg_host):
    env = {
        "MLFLOW_S3_ENDPOINT_URL": f"http://{pg_host}:4566",
        "AWS_ACCESS_KEY_ID": "test",
        "AWS_SECRET_ACCESS_KEY": "test",
        "AWS_DEFAULT_REGION": REGION,
    }
    for k, v in env.items():
        os.environ[k] = v
    return env


@pytest.fixture(scope="session")
def mlflow_ready(mlflow_uri):
    import time

    import requests

    for _ in range(30):
        try:
            resp = requests.get(f"{mlflow_uri}/health", timeout=2)
            if resp.status_code == 200:
                return mlflow_uri
        except requests.RequestException:
            pass
        time.sleep(2)
    pytest.fail(f"MLflow no respondio en {mlflow_uri} despues de 60s")


@pytest.fixture(scope="function")
def mlflow_pg_conn(pg_host):
    import psycopg2

    conn = psycopg2.connect(
        host=pg_host,
        port=int(os.environ.get("PGPORT", "5432")),
        user=os.environ.get("PGUSER", "taobao"),
        password=os.environ.get("PGPASSWORD", "taobao123"),
        dbname=os.environ.get("MLFLOW_DB", "mlflow"),
    )
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def vpc(ec2_client):
    response = ec2_client.describe_vpcs(
        Filters=[{"Name": "tag:Name", "Values": [f"{PROJECT}-vpc"]}]
    )
    vpcs = response["Vpcs"]
    assert vpcs, f"VPC con tag Name={PROJECT}-vpc no encontrada"
    return vpcs[0]


@pytest.fixture(scope="session")
def subnets(ec2_client, vpc):
    response = ec2_client.describe_subnets(
        Filters=[{"Name": "vpc-id", "Values": [vpc["VpcId"]]}]
    )
    return response["Subnets"]


@pytest.fixture(scope="session")
def public_subnets(subnets):
    return [s for s in subnets if s["MapPublicIpOnLaunch"]]


@pytest.fixture(scope="session")
def private_subnets(subnets):
    return [s for s in subnets if not s["MapPublicIpOnLaunch"]]


@pytest.fixture(scope="session")
def igw(ec2_client, vpc):
    response = ec2_client.describe_internet_gateways(
        Filters=[{"Name": "attachment.vpc-id", "Values": [vpc["VpcId"]]}]
    )
    gateways = response["InternetGateways"]
    assert gateways, f"IGW adjuntado a {vpc['VpcId']} no encontrado"
    return gateways[0]


@pytest.fixture(scope="session")
def vpc_dns_support(ec2_client, vpc):
    response = ec2_client.describe_vpc_attribute(
        VpcId=vpc["VpcId"], Attribute="enableDnsSupport"
    )
    return response["EnableDnsSupport"]


@pytest.fixture(scope="session")
def vpc_dns_hostnames(ec2_client, vpc):
    response = ec2_client.describe_vpc_attribute(
        VpcId=vpc["VpcId"], Attribute="enableDnsHostnames"
    )
    return response["EnableDnsHostnames"]


@pytest.fixture(scope="session")
def route_tables(ec2_client, vpc):
    response = ec2_client.describe_route_tables(
        Filters=[{"Name": "vpc-id", "Values": [vpc["VpcId"]]}]
    )
    return response["RouteTables"]


@pytest.fixture(scope="session")
def security_groups(ec2_client, vpc):
    response = ec2_client.describe_security_groups(
        Filters=[{"Name": "vpc-id", "Values": [vpc["VpcId"]]}]
    )
    return {
        sg["GroupName"]: sg for sg in response["SecurityGroups"]
    }


@pytest.fixture(scope="session")
def sg_alb(security_groups):
    return security_groups[f"{PROJECT}-alb-sg"]


@pytest.fixture(scope="session")
def sg_api_ec2(security_groups):
    return security_groups[f"{PROJECT}-api-ec2-sg"]


@pytest.fixture(scope="session")
def sg_batch_ec2(security_groups):
    return security_groups[f"{PROJECT}-batch-ec2-sg"]


@pytest.fixture(scope="session")
def sg_rds(security_groups):
    return security_groups[f"{PROJECT}-rds-sg"]


@pytest.fixture(scope="session")
def batch_role(iam_client):
    return iam_client.get_role(RoleName=f"{PROJECT}-batch-role")["Role"]


@pytest.fixture(scope="session")
def s3_rw_policy(iam_client):
    policies = iam_client.list_policies(Scope="Local")["Policies"]
    match = [p for p in policies if p["PolicyName"] == f"{PROJECT}-s3-rw-policy"]
    assert match, f"Policy {PROJECT}-s3-rw-policy no encontrada"
    version = iam_client.get_policy_version(
        PolicyArn=match[0]["Arn"], VersionId=match[0]["DefaultVersionId"]
    )
    return version["PolicyVersion"]["Document"]


@pytest.fixture(scope="session")
def instance_profile(iam_client):
    return iam_client.get_instance_profile(
        InstanceProfileName=f"{PROJECT}-batch-instance-profile"
    )["InstanceProfile"]
