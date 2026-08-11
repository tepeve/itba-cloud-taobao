from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.bash import BashOperator

default_args = {
    'owner': 'data_engineering',
    'depends_on_past': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

with DAG(
    'taobao_recommender_pipeline',
    default_args=default_args,
    schedule_interval=timedelta(days=1),
    start_date=datetime(2026, 1, 1),
    catchup=False,
) as dag:

    env_vars = {
        "BUCKET": "{{ var.value.datalake_bucket }}",
        "MLFLOW_TRACKING_URI": "{{ var.value.mlflow_db_uri }}",
        "PGHOST": "{{ var.value.rds_host }}",
        "PGPORT": "5432",
        "PGUSER": "{{ var.value.rds_user }}",
        "PGPASSWORD": "{{ var.value.rds_password }}",
        "PGDATABASE": "taobao",
        "LOCALSTACK_ENDPOINT": "{{ var.value.localstack_endpoint }}",
    }

    t_bootstrap = BashOperator(
        task_id='data_bootstrap',
        bash_command='cd /opt/airflow/dags && uv run python data_bootstrap.py',
        env=env_vars,
    )

    t_features = BashOperator(
        task_id='pipeline_features',
        bash_command='cd /opt/airflow/dags && uv run python pipeline_features.py',
        env=env_vars,
    )

    t_training = BashOperator(
        task_id='pipeline_training',
        bash_command='cd /opt/airflow/dags && uv run python pipeline_training.py',
        env=env_vars,
    )

    t_inference = BashOperator(
        task_id='pipeline_inference',
        bash_command='cd /opt/airflow/dags && uv run python pipeline_inference.py',
        env=env_vars,
    )

    t_bootstrap >> t_features >> t_training >> t_inference
