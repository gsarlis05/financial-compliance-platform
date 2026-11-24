variable "name_prefix" {
  description = "Prefix for resource names, e.g. fcp-pilot."
  type        = string
}

variable "region" {
  description = "AWS region (EU only)."
  type        = string
}

variable "vpc_id" {
  description = "VPC ID."
  type        = string
}

variable "vpc_cidr_block" {
  description = "VPC CIDR block."
  type        = string
}

variable "subnet_ids" {
  description = "Private application subnets for the tasks and the internal load balancer."
  type        = list(string)
}

variable "image" {
  description = "API image, by digest (repository@sha256:...). Tags are not accepted."
  type        = string

  validation {
    condition     = can(regex("@sha256:[0-9a-f]{64}$", var.image))
    error_message = "Reference the image by digest (…@sha256:<64 hex>), so what was reviewed and signed is what runs."
  }
}

variable "repository_arn" {
  description = "ECR repository the image is pulled from."
  type        = string
}

variable "kms_key_arn" {
  description = "KMS key for the runtime secrets."
  type        = string
}

variable "logs_kms_key_arn" {
  description = "KMS key for the application log group."
  type        = string
}

variable "certificate_arn" {
  description = "ACM certificate (this region) for the internal load balancer."
  type        = string
}

variable "access_logs_bucket" {
  description = "S3 bucket for load balancer access logs."
  type        = string
}

variable "app_host" {
  description = "Public host name of the application, e.g. app.example.com."
  type        = string
}

variable "database_host" {
  description = "PostgreSQL host name."
  type        = string
}

variable "database_security_group_id" {
  description = "Security group of the database (the tasks may reach it on 5432)."
  type        = string
}

variable "endpoints_security_group_id" {
  description = "Security group of the VPC interface endpoints."
  type        = string
}

variable "s3_prefix_list_id" {
  description = "Prefix list of the S3 gateway endpoint."
  type        = string
}

variable "documents_bucket" {
  description = "Document and evidence bucket."
  type        = string
}

variable "documents_kms_key_arn" {
  description = "KMS key of the documents bucket."
  type        = string
}

variable "oidc_issuer" {
  description = "OIDC issuer URL (https). The identity provider hosting is an owner decision."
  type        = string

  validation {
    condition     = startswith(var.oidc_issuer, "https://")
    error_message = "The OIDC issuer must be an https URL."
  }
}

variable "oidc_client_id" {
  description = "OIDC client ID of the application."
  type        = string
}

variable "clamd_host" {
  description = "Host name of the internal antivirus (ClamAV) service."
  type        = string
}

variable "api_count" {
  description = "Number of API tasks."
  type        = number
  default     = 2
}

variable "cpu" {
  description = "CPU units per task."
  type        = number
  default     = 512
}

variable "memory" {
  description = "Memory (MiB) per task."
  type        = number
  default     = 1024
}

variable "log_retention_days" {
  description = "Application log retention."
  type        = number
  default     = 365
}
