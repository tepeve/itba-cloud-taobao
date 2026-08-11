resource "aws_security_group" "alb" {
  name   = "${var.project}-alb-sg"
  vpc_id = var.vpc_id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${var.project}-sg-alb"
    Project     = var.project
    Environment = "localstack"
  }
}

resource "aws_security_group" "api_ec2" {
  name   = "${var.project}-api-ec2-sg"
  vpc_id = var.vpc_id

  ingress {
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  tags = {
    Name        = "${var.project}-sg-api-ec2"
    Project     = var.project
    Environment = "localstack"
  }
}

resource "aws_security_group" "airflow" {
  name   = "${var.project}-airflow-sg"
  vpc_id = var.vpc_id

  ingress {
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  ingress {
    from_port   = 5000
    to_port     = 5000
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${var.project}-sg-airflow"
    Project     = var.project
    Environment = "localstack"
  }
}

resource "aws_security_group" "rds" {
  name   = "${var.project}-rds-sg"
  vpc_id = var.vpc_id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.airflow.id, aws_security_group.api_ec2.id]
  }

  tags = {
    Name        = "${var.project}-sg-rds"
    Project     = var.project
    Environment = "localstack"
  }
}
