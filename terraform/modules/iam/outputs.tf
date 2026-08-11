output "role_arn" {
  value = aws_iam_role.batch.arn
}

output "role_name" {
  value = aws_iam_role.batch.name
}

output "instance_profile_arn" {
  value = aws_iam_instance_profile.batch.arn
}

output "instance_profile_name" {
  value = aws_iam_instance_profile.batch.name
}

output "ssm_parameter_name" {
  value = aws_ssm_parameter.rds_password.name
}

output "rds_password" {
  value     = random_password.rds_password.result
  sensitive = true
}
