module "networking" {
  source              = "./modules/networking"
  project             = var.project
  region              = var.region
  vpc_cidr            = var.vpc_cidr
  azs                 = var.azs
  public_subnet_cidrs  = var.public_subnet_cidrs
  private_subnet_cidrs = var.private_subnet_cidrs
}

module "security_groups" {
  source  = "./modules/security_groups"
  project = var.project
  vpc_id  = module.networking.vpc_id
  vpc_cidr = var.vpc_cidr
}

module "iam" {
  source       = "./modules/iam"
  project      = var.project
  bucket_names = var.bucket_names
}

module "s3" {
  source      = "./modules/s3"
  project     = var.project
  bucket_name = "taobao-datalake"
}

module "s3_mlflow" {
  source      = "./modules/s3"
  project     = var.project
  bucket_name = "taobao-mlflow-artifacts"
}

module "s3_airflow_dags" {
  source      = "./modules/s3"
  project     = var.project
  bucket_name = "taobao-airflow-dags"
}

module "rds" {
  source             = "./modules/rds"
  project            = var.project
  enabled            = var.rds_enabled
  private_subnet_ids = module.networking.private_subnet_ids
  sg_rds_id          = module.security_groups.sg_rds_id
}

module "compute" {
  source                     = "./modules/compute"
  project                    = var.project
  ami_id                     = var.ami_id
  private_subnet_id          = module.networking.private_subnet_ids[0]
  sg_airflow_id              = module.security_groups.sg_airflow_id
  iam_instance_profile_name  = module.iam.instance_profile_name
  rds_endpoint               = module.rds.endpoint
  db_user                    = var.db_user
  ssm_parameter_name         = module.iam.ssm_parameter_name
  dags_bucket                = module.s3_airflow_dags.bucket_name
  datalake_bucket            = module.s3.bucket_name
  gateway_ip                 = var.gateway_ip
}

module "alb_asg" {
  source              = "./modules/alb_asg"
  project             = var.project
  enabled             = var.alb_asg_enabled
  vpc_id              = module.networking.vpc_id
  public_subnet_ids   = module.networking.public_subnet_ids
  private_subnet_ids  = module.networking.private_subnet_ids
  sg_alb_id           = module.security_groups.sg_alb_id
  sg_api_ec2_id       = module.security_groups.sg_api_ec2_id
}
