# Staging environment (synthetic data only, ADR-0010).
#
# NEVER APPLIED WITHOUT THE PRODUCT OWNER'S EXPLICIT APPROVAL. CI only runs fmt, validate,
# tflint and checkov with `-backend=false`; there is no apply path anywhere in this repository.

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

provider "aws" {
  region              = var.region
  allowed_account_ids = var.allowed_account_ids

  default_tags {
    tags = {
      Project     = "financial-compliance-platform"
      Environment = "staging"
      DataClass   = "synthetic-only"
      ManagedBy   = "terraform"
    }
  }
}

locals {
  name_prefix = "fcp-staging"
}

module "kms" {
  source      = "../../modules/kms"
  name_prefix = local.name_prefix
  region      = var.region
}

module "network" {
  source             = "../../modules/network"
  name_prefix        = local.name_prefix
  availability_zones = ["${var.region}a", "${var.region}b", "${var.region}c"]
  logs_kms_key_arn   = module.kms.key_arns["logs"]
}

module "database" {
  source              = "../../modules/database"
  name_prefix         = local.name_prefix
  vpc_id              = module.network.vpc_id
  vpc_cidr_block      = module.network.vpc_cidr_block
  subnet_ids          = module.network.data_subnet_ids
  allowed_cidr_blocks = module.network.app_subnet_cidrs
  kms_key_arn         = module.kms.key_arns["database"]
  multi_az            = false # staging: single AZ to save cost; production is Multi-AZ
}

module "storage" {
  source           = "../../modules/storage"
  name_prefix      = local.name_prefix
  kms_key_arn      = module.kms.key_arns["documents"]
  object_lock_mode = "GOVERNANCE"
  object_lock_days = 7
}
