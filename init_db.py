import os

import psycopg2

PGHOST = os.environ.get("PGHOST", "localhost")
PGPORT = int(os.environ.get("PGPORT", "5432"))
PGUSER = os.environ.get("PGUSER", "taobao")
PGPASSWORD = os.environ.get("PGPASSWORD", "taobao123")
PGDATABASE = os.environ.get("PGDATABASE", "taobao")

DDL = """
CREATE TABLE IF NOT EXISTS inference_results (
    user_id BIGINT PRIMARY KEY,
    recommended_items JSONB NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""


def get_conn():
    return psycopg2.connect(
        host=PGHOST,
        port=PGPORT,
        user=PGUSER,
        password=PGPASSWORD,
        dbname=PGDATABASE,
    )


def init_db(conn=None):
    owns_conn = conn is None
    conn = conn or get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(DDL)
        conn.commit()
    finally:
        if owns_conn:
            conn.close()


def main():
    init_db()
    print(f"Esquema inicializado en {PGHOST}:{PGPORT}/{PGDATABASE} (tabla inference_results)")


if __name__ == "__main__":
    main()