variable "project" {
  type = string
}

variable "enabled" {
  type    = bool
  default = false
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "sg_rds_id" {
  type = string
}

variable "engine" {
  type    = string
  default = "postgres"
}

variable "engine_version" {
  type    = string
  default = "15"
}

variable "instance_class" {
  type    = string
  default = "db.t3.micro"
}

variable "allocated_storage" {
  type    = number
  default = 20
}

variable "username" {
  type      = string
  default   = "taobao"
  sensitive = true
}

variable "password" {
  type      = string
  default   = "taobao123"
  sensitive = true
}

variable "db_name" {
  type    = string
  default = "taobao"
}

variable "port" {
  type    = number
  default = 5432
}