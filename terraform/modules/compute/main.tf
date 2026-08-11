resource "aws_instance" "airflow_orchestrator" {
  ami           = var.ami_id
  instance_type = var.instance_type
  subnet_id     = var.private_subnet_id

  vpc_security_group_ids      = [var.sg_airflow_id]
  iam_instance_profile        = var.iam_instance_profile_name
  associate_public_ip_address = false

  user_data = templatefile("${path.module}/scripts/init_airflow.sh.tpl", {
    db_host          = var.rds_endpoint
    db_user          = var.db_user
    ssm_db_password  = var.ssm_parameter_name
    dags_bucket      = var.dags_bucket
    datalake_bucket  = var.datalake_bucket
    gateway_ip       = var.gateway_ip
  })

  tags = {
    Name        = "${var.project}-airflow"
    Project     = var.project
    Environment = "localstack"
  }
}
