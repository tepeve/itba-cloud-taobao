output "endpoint" {
  value = var.enabled ? aws_db_instance.main[0].endpoint : ""
}

output "db_name" {
  value = var.enabled ? aws_db_instance.main[0].db_name : var.db_name
}

output "username" {
  value = var.enabled ? aws_db_instance.main[0].username : var.username
}

output "instance_id" {
  value = var.enabled ? aws_db_instance.main[0].id : ""
}

output "subnet_group_name" {
  value = var.enabled ? aws_db_subnet_group.main[0].name : ""
}