variable "project" {
  type    = string
  default = "taobao"
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "localstack_endpoint" {
  type    = string
  default = "http://localhost:4566"
}

variable "vpc_cidr" {
  type    = string
  default = "10.0.0.0/16"
}

variable "azs" {
  type    = list(string)
  default = ["us-east-1a", "us-east-1b"]
}

variable "public_subnet_cidrs" {
  type    = list(string)
  default = ["10.0.1.0/24", "10.0.2.0/24"]
}

variable "private_subnet_cidrs" {
  type    = list(string)
  default = ["10.0.10.0/24", "10.0.11.0/24"]
}

variable "bucket_names" {
  type    = list(string)
  default = ["taobao-datalake", "taobao-mlflow-artifacts", "taobao-airflow-dags"]
}

variable "db_user" {
  type    = string
  default = "taobao"
}

variable "rds_enabled" {
  type    = bool
  default = false
}

variable "alb_asg_enabled" {
  type    = bool
  default = false
}
