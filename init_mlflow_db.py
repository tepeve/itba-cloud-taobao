import os

import psycopg2

PGHOST = os.environ.get("PGHOST", "localhost")
PGPORT = int(os.environ.get("PGPORT", "5432"))
PGUSER = os.environ.get("PGUSER", "taobao")
PGPASSWORD = os.environ.get("PGPASSWORD", "taobao123")
PGDATABASE = os.environ.get("PGDATABASE", "taobao")
TARGET_DB = os.environ.get("MLFLOW_DB", "mlflow")


def init_mlflow_db(conn=None):
    owns_conn = conn is None
    conn = conn or psycopg2.connect(
        host=PGHOST,
        port=PGPORT,
        user=PGUSER,
        password=PGPASSWORD,
        dbname=PGDATABASE,
    )
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TARGET_DB,))
            if not cur.fetchone():
                cur.execute(f"CREATE DATABASE {TARGET_DB}")
    finally:
        if owns_conn:
            conn.close()


def main():
    init_mlflow_db()
    print(f"Base de datos '{TARGET_DB}' disponible en {PGHOST}:{PGPORT}")


if __name__ == "__main__":
    main()