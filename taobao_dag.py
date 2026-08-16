from datetime import timedelta

import pendulum
from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import ShortCircuitOperator

SHANGHAI = "Asia/Shanghai"

default_args = {
    'owner': 'data_engineering',
    'depends_on_past': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}


def _is_training_day():
    return pendulum.now(SHANGHAI).weekday() == 1


with DAG(
    'taobao_recommender_pipeline',
    default_args=default_args,
    schedule='0 3 * * *',
    start_date=pendulum.datetime(2026, 1, 1, tz=SHANGHAI),
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

    t_training_gate = ShortCircuitOperator(
        task_id='weekly_training_gate',
        python_callable=_is_training_day,
        ignore_downstream_trigger_rules=False,
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
        trigger_rule='none_failed_min_one_success',
    )

    t_bootstrap >> t_features >> t_training_gate >> t_training
    t_features >> t_inference
    t_training >> t_inference
