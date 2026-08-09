output "alb_dns_name" {
  value = var.enabled ? aws_lb.main[0].dns_name : ""
}

output "alb_arn" {
  value = var.enabled ? aws_lb.main[0].arn : ""
}

output "target_group_arn" {
  value = var.enabled ? aws_lb_target_group.main[0].arn : ""
}

output "asg_name" {
  value = var.enabled ? aws_autoscaling_group.main[0].name : ""
}