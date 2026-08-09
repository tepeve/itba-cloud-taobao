import pytest

pytestmark = pytest.mark.integration

RDS_IDENTIFIER = "taobao-db"
RDS_DB_NAME = "taobao"


@pytest.fixture(scope="module")
def rds_instance(rds_client, rds_available):
    if not rds_available:
        pytest.skip("servicio RDS no disponible en LocalStack community")
    resp = rds_client.describe_db_instances(DBInstanceIdentifier=RDS_IDENTIFIER)
    instances = resp["DBInstances"]
    assert instances, f"Instancia RDS {RDS_IDENTIFIER} no encontrada"
    return instances[0]


def test_rds_instance_exists(rds_instance):
    assert rds_instance["DBInstanceStatus"] == "available"


def test_rds_engine_is_postgres(rds_instance):
    assert rds_instance["Engine"] == "postgres"


def test_rds_engine_version_15_or_higher(rds_instance):
    major = int(rds_instance["EngineVersion"].split(".")[0])
    assert major >= 15


def test_rds_instance_class_db_t3_micro(rds_instance):
    assert rds_instance["DBInstanceClass"] == "db.t3.micro"


def test_rds_not_publicly_accessible(rds_instance):
    assert rds_instance["PubliclyAccessible"] is False


def test_rds_uses_sg_rds(rds_instance, sg_rds):
    sg_ids = {g["VpcSecurityGroupId"] for g in rds_instance["VpcSecurityGroups"]}
    assert sg_rds["GroupId"] in sg_ids


def test_rds_subnet_group_uses_private_subnets(rds_instance):
    group_name = rds_instance["DBSubnetGroup"]["DBSubnetGroupName"]
    assert group_name == "taobao-db-subnet-group"


def test_rds_db_name(rds_instance):
    assert rds_instance["DBName"] == RDS_DB_NAME


def test_inference_results_table_exists(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'inference_results'"
        )
        assert cur.fetchone()


def test_inference_results_schema(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT column_name, data_type, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'inference_results'"
            " ORDER BY ordinal_position"
        )
        cols = {row[0]: row for row in cur.fetchall()}
    assert cols["user_id"][1] == "bigint"
    assert cols["user_id"][2] == "NO"
    assert cols["recommended_items"][1] == "jsonb"
    assert cols["recommended_items"][2] == "NO"
    assert cols["updated_at"][1] == "timestamp without time zone"


def test_inference_results_user_id_primary_key(pg_conn):
    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "ON tc.constraint_name = kcu.constraint_name "
            "WHERE tc.table_name = 'inference_results' "
            "AND tc.constraint_type = 'PRIMARY KEY' AND kcu.column_name = 'user_id'"
        )
        assert cur.fetchone()


def test_init_db_idempotent(pg_conn):
    import init_db

    init_db.init_db(conn=pg_conn)
    init_db.init_db(conn=pg_conn)
    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'inference_results'"
        )
        assert cur.fetchone()