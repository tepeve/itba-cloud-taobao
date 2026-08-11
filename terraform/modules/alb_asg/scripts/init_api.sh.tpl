#!/bin/bash
exec > >(tee /var/log/user-data.log|logger -t user-data -s 2>/dev/console) 2>&1

apt-get update -y
apt-get install -y docker.io awscli jq

systemctl enable docker
systemctl start docker
usermod -aG docker ubuntu

export DB_PASSWORD=$(aws ssm get-parameter --name "${ssm_db_password}" --with-decryption --query "Parameter.Value" --output text)

mkdir -p /opt/taobao-api
aws s3 sync s3://${dags_bucket}/api /opt/taobao-api/
cd /opt/taobao-api

docker build -t taobao-api:latest .

docker run -d \
  --name taobao-api \
  --network host \
  --restart always \
  -e PGHOST=${db_host} \
  -e PGPORT=5432 \
  -e PGUSER=${db_user} \
  -e PGPASSWORD=$DB_PASSWORD \
  -e PGDATABASE=taobao \
  taobao-api:latest

unset DB_PASSWORD
