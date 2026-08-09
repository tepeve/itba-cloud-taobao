resource "aws_db_subnet_group" "main" {
  count = var.enabled ? 1 : 0

  name       = "${var.project}-db-subnet-group"
  subnet_ids = var.private_subnet_ids

  tags = {
    Name        = "${var.project}-db-subnet-group"
    Project     = var.project
    Environment = "localstack"
  }
}

resource "aws_db_instance" "main" {
  count = var.enabled ? 1 : 0

  identifier             = "${var.project}-db"
  engine                 = var.engine
  engine_version         = var.engine_version
  instance_class         = var.instance_class
  allocated_storage      = var.allocated_storage
  username               = var.username
  password               = var.password
  db_name                = var.db_name
  port                   = var.port
  db_subnet_group_name   = var.enabled ? aws_db_subnet_group.main[0].name : null
  vpc_security_group_ids = [var.sg_rds_id]
  publicly_accessible    = false
  skip_final_snapshot    = true

  tags = {
    Name        = "${var.project}-db"
    Project     = var.project
    Environment = "localstack"
  }
}