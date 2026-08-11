variable "project" {
  type = string
}

variable "ami_id" {
  type    = string
  default = "ami-07b643b5e45e"
}

variable "instance_type" {
  type    = string
  default = "t3.medium"
}

variable "private_subnet_id" {
  type = string
}

variable "sg_airflow_id" {
  type = string
}

variable "iam_instance_profile_name" {
  type = string
}

variable "rds_endpoint" {
  type = string
}

variable "db_user" {
  type = string
}

variable "ssm_parameter_name" {
  type = string
}

variable "dags_bucket" {
  type = string
}

variable "datalake_bucket" {
  type = string
}

variable "gateway_ip" {
  type = string
}
