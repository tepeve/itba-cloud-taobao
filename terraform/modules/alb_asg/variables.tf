variable "project" {
  type = string
}

variable "enabled" {
  type    = bool
  default = false
}

variable "vpc_id" {
  type = string
}

variable "public_subnet_ids" {
  type = list(string)
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "sg_alb_id" {
  type = string
}

variable "sg_api_ec2_id" {
  type = string
}

variable "api_port" {
  type    = number
  default = 8000
}

variable "min_size" {
  type    = number
  default = 2
}

variable "max_size" {
  type    = number
  default = 4
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

variable "iam_instance_profile_name" {
  type = string
}

variable "ami_id" {
  type    = string
  default = "ami-07b643b5e45e"
}