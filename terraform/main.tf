module "networking" {
  source              = "./modules/networking"
  project             = var.project
  vpc_cidr            = var.vpc_cidr
  azs                 = var.azs
  public_subnet_cidrs  = var.public_subnet_cidrs
  private_subnet_cidrs = var.private_subnet_cidrs
}

module "security_groups" {
  source  = "./modules/security_groups"
  project = var.project
  vpc_id  = module.networking.vpc_id
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

module "rds" {
  source             = "./modules/rds"
  project            = var.project
  enabled            = var.rds_enabled
  private_subnet_ids = module.networking.private_subnet_ids
  sg_rds_id          = module.security_groups.sg_rds_id
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
