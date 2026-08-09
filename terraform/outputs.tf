output "vpc_id" {
  value = module.networking.vpc_id
}

output "public_subnet_ids" {
  value = module.networking.public_subnet_ids
}

output "private_subnet_ids" {
  value = module.networking.private_subnet_ids
}

output "igw_id" {
  value = module.networking.igw_id
}

output "sg_alb_id" {
  value = module.security_groups.sg_alb_id
}

output "sg_api_ec2_id" {
  value = module.security_groups.sg_api_ec2_id
}

output "sg_batch_ec2_id" {
  value = module.security_groups.sg_batch_ec2_id
}

output "sg_rds_id" {
  value = module.security_groups.sg_rds_id
}

output "iam_role_arn" {
  value = module.iam.role_arn
}

output "iam_role_name" {
  value = module.iam.role_name
}

output "instance_profile_arn" {
  value = module.iam.instance_profile_arn
}

output "datalake_bucket_arn" {
  value = module.s3.bucket_arn
}

output "datalake_bucket_name" {
  value = module.s3.bucket_name
}

output "mlflow_bucket_arn" {
  value = module.s3_mlflow.bucket_arn
}

output "mlflow_bucket_name" {
  value = module.s3_mlflow.bucket_name
}

output "rds_endpoint" {
  value = module.rds.endpoint
}

output "rds_db_name" {
  value = module.rds.db_name
}

output "rds_username" {
  value     = module.rds.username
  sensitive = true
}

output "rds_instance_id" {
  value = module.rds.instance_id
}

output "alb_dns_name" {
  value = module.alb_asg.alb_dns_name
}

output "alb_arn" {
  value = module.alb_asg.alb_arn
}

output "asg_name" {
  value = module.alb_asg.asg_name
}
