# Pilot environment (Gate P): the owner's own use, in a separate AWS account.
#
# NEVER APPLIED WITHOUT THE PRODUCT OWNER'S EXPLICIT APPROVAL. CI only runs fmt, validate,
# tflint and checkov with `-backend=false`; there is no apply path anywhere in this repository.
# The steps for an approved apply are in infra/README.md and docs/runbooks/pilot-environment.md.

terraform {
  required_version = ">= 1.9"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # Partial configuration: bucket, key, region and lock settings are supplied at init time by
  # an approved operator (`terraform init -backend-config=...`), never committed.
  backend "s3" {}
}

locals {
  name_prefix = "fcp-pilot"
  tags = {
    Project     = "financial-compliance-platform"
    Environment = "pilot"
    DataClass   = "owner-pilot"
    ManagedBy   = "terraform"
  }
}

provider "aws" {
  region              = var.region
  allowed_account_ids = var.allowed_account_ids

  default_tags {
    tags = local.tags
  }
}

# AWS requires the web ACL and certificate of a CloudFront distribution in us-east-1. Nothing
# else is created there, and firewall logs are stored in the EU region.
provider "aws" {
  alias               = "global"
  region              = "us-east-1"
  allowed_account_ids = var.allowed_account_ids

  default_tags {
    tags = local.tags
  }
}

module "kms" {
  source      = "../../modules/kms"
  name_prefix = local.name_prefix
  region      = var.region
}

module "network" {
  source             = "../../modules/network"
  name_prefix        = local.name_prefix
  cidr_block         = "10.50.0.0/16"
  availability_zones = ["${var.region}a", "${var.region}b", "${var.region}c"]
  logs_kms_key_arn   = module.kms.key_arns["logs"]
}

module "endpoints" {
  source          = "../../modules/endpoints"
  name_prefix     = local.name_prefix
  region          = var.region
  vpc_id          = module.network.vpc_id
  vpc_cidr_block  = module.network.vpc_cidr_block
  subnet_ids      = module.network.app_subnet_ids
  route_table_ids = [module.network.main_route_table_id]
}

module "database" {
  source              = "../../modules/database"
  name_prefix         = local.name_prefix
  vpc_id              = module.network.vpc_id
  vpc_cidr_block      = module.network.vpc_cidr_block
  subnet_ids          = module.network.data_subnet_ids
  allowed_cidr_blocks = module.network.app_subnet_cidrs
  kms_key_arn         = module.kms.key_arns["database"]
  multi_az            = true # the pilot holds the owner's real books
}

module "storage" {
  source           = "../../modules/storage"
  name_prefix      = local.name_prefix
  kms_key_arn      = module.kms.key_arns["documents"]
  object_lock_mode = "GOVERNANCE"
  object_lock_days = 30
}

module "registry" {
  source      = "../../modules/registry"
  name_prefix = local.name_prefix
  kms_key_arn = module.kms.key_arns["application"]
}

module "app" {
  source                      = "../../modules/app"
  name_prefix                 = local.name_prefix
  region                      = var.region
  vpc_id                      = module.network.vpc_id
  vpc_cidr_block              = module.network.vpc_cidr_block
  subnet_ids                  = module.network.app_subnet_ids
  image                       = var.image
  repository_arn              = module.registry.repository_arns["backend"]
  kms_key_arn                 = module.kms.key_arns["application"]
  logs_kms_key_arn            = module.kms.key_arns["logs"]
  certificate_arn             = var.regional_certificate_arn
  access_logs_bucket          = module.storage.access_logs_bucket
  app_host                    = var.app_host
  database_host               = module.database.address
  database_security_group_id  = module.database.security_group_id
  endpoints_security_group_id = module.endpoints.security_group_id
  s3_prefix_list_id           = module.endpoints.s3_prefix_list_id
  documents_bucket            = module.storage.documents_bucket
  documents_kms_key_arn       = module.kms.key_arns["documents"]
  oidc_issuer                 = var.oidc_issuer
  oidc_client_id              = var.oidc_client_id
  clamd_host                  = var.clamd_host
}

module "edge" {
  source = "../../modules/edge"
  providers = {
    aws        = aws
    aws.global = aws.global
  }

  name_prefix            = local.name_prefix
  app_host               = var.app_host
  idp_origin             = regex("^https://[^/]+", var.oidc_issuer)
  certificate_arn        = var.global_certificate_arn
  load_balancer_arn      = module.app.load_balancer_arn
  load_balancer_dns_name = module.app.load_balancer_dns_name
  access_logs_bucket     = module.storage.access_logs_bucket
}

module "monitoring" {
  source                   = "../../modules/monitoring"
  name_prefix              = local.name_prefix
  kms_key_arn              = module.kms.key_arns["application"]
  alarm_email              = var.alarm_email
  database_identifier      = module.database.identifier
  load_balancer_arn_suffix = module.app.load_balancer_arn_suffix
  target_group_arn_suffix  = module.app.target_group_arn_suffix
  cluster_name             = module.app.cluster_name
  cluster_arn              = module.app.cluster_arn
  log_group_name           = module.app.log_group_name
}

module "backup" {
  source          = "../../modules/backup"
  name_prefix     = local.name_prefix
  kms_key_arn     = module.kms.key_arns["backups"]
  resource_arns   = [module.database.arn]
  alarm_topic_arn = module.monitoring.alarm_topic_arn
}
