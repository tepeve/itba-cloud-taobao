output "sg_alb_id" {
  value = aws_security_group.alb.id
}

output "sg_api_ec2_id" {
  value = aws_security_group.api_ec2.id
}

output "sg_batch_ec2_id" {
  value = aws_security_group.batch_ec2.id
}

output "sg_rds_id" {
  value = aws_security_group.rds.id
}
