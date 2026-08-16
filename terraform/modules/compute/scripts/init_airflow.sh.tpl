#!/bin/bash
exec > >(tee /var/log/user-data.log|logger -t user-data -s 2>/dev/console) 2>&1

apt-get update -y
apt-get install -y docker.io docker-compose awscli cron jq

systemctl enable docker
systemctl start docker
usermod -aG docker ubuntu

mkdir -p /opt/airflow/dags
aws s3 sync s3://${dags_bucket}/ /opt/airflow/dags/

echo "*/5 * * * * root aws s3 sync s3://${dags_bucket}/ /opt/airflow/dags/" > /etc/cron.d/airflow_sync

export DB_PASSWORD=$(aws ssm get-parameter --name "${ssm_db_password}" --with-decryption --query "Parameter.Value" --output text)

cat <<EOF > /opt/docker-compose.yml
services:
  airflow:
    image: apache/airflow:2.9.0
    network_mode: host
    environment:
      AIRFLOW__DATABASE__SQL_ALCHEMY_CONN: postgresql+psycopg2://${db_user}:$DB_PASSWORD@${db_host}:5432/airflow
      AIRFLOW__CORE__EXECUTOR: LocalExecutor
      AIRFLOW__CORE__LOAD_EXAMPLES: 'False'
      AIRFLOW_VAR_DATALAKE_BUCKET: ${datalake_bucket}
      AIRFLOW_VAR_MLFLOW_DB_URI: http://${gateway_ip}:5000
      AIRFLOW_VAR_RDS_HOST: ${db_host}
      AIRFLOW_VAR_RDS_USER: ${db_user}
      AIRFLOW_VAR_RDS_PASSWORD: $DB_PASSWORD
      AIRFLOW_VAR_LOCALSTACK_ENDPOINT: http://${gateway_ip}:4566
    volumes:
      - /opt/airflow/dags:/opt/airflow/dags
    command: standalone
EOF

docker-compose -f /opt/docker-compose.yml up -d

unset DB_PASSWORD
