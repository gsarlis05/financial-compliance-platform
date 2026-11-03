variable "name_prefix" {
  description = "Prefix for resource names, e.g. fcp-staging."
  type        = string
}

variable "vpc_id" {
  description = "VPC ID."
  type        = string
}

variable "vpc_cidr_block" {
  description = "VPC CIDR block (egress is limited to it)."
  type        = string
}

variable "subnet_ids" {
  description = "Private data subnets for the database."
  type        = list(string)
}

variable "allowed_cidr_blocks" {
  description = "CIDR blocks (application subnets) allowed to connect on 5432."
  type        = list(string)
}

variable "kms_key_arn" {
  description = "KMS key for storage, master secret and Performance Insights encryption."
  type        = string
}

variable "instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t4g.medium"
}

variable "allocated_storage_gb" {
  description = "Initial storage in GiB (autoscaling up to 4x)."
  type        = number
  default     = 50
}

variable "multi_az" {
  description = "Multi-AZ standby for high availability."
  type        = bool
  default     = true
}

variable "backup_retention_days" {
  description = "Automated backup retention (point-in-time recovery window)."
  type        = number
  default     = 14

  validation {
    condition     = var.backup_retention_days >= 7 && var.backup_retention_days <= 35
    error_message = "backup_retention_days must be between 7 and 35."
  }
}
