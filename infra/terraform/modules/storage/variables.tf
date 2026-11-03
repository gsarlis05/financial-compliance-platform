variable "name_prefix" {
  description = "Prefix for resource names, e.g. fcp-staging."
  type        = string
}

variable "kms_key_arn" {
  description = "KMS key for document encryption."
  type        = string
}

variable "object_lock_mode" {
  description = "Default Object Lock mode. GOVERNANCE for staging; COMPLIANCE for production evidence."
  type        = string
  default     = "GOVERNANCE"

  validation {
    condition     = contains(["GOVERNANCE", "COMPLIANCE"], var.object_lock_mode)
    error_message = "object_lock_mode must be GOVERNANCE or COMPLIANCE."
  }
}

variable "object_lock_days" {
  description = "Default Object Lock retention in days (production values follow the retention policy)."
  type        = number
  default     = 30
}

variable "access_log_retention_days" {
  description = "Retention for S3 server access logs."
  type        = number
  default     = 365
}
