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