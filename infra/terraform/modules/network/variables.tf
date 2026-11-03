variable "name_prefix" {
  description = "Prefix for resource names, e.g. fcp-staging."
  type        = string
}

variable "cidr_block" {
  description = "VPC CIDR block."
  type        = string
  default     = "10.40.0.0/16"
}

variable "availability_zones" {
  description = "Availability zone names to use (2 or 3; at least 2 for a highly available database)."
  type        = list(string)

  validation {
    condition     = length(var.availability_zones) >= 2 && length(var.availability_zones) <= 3
    error_message = "Provide 2 or 3 availability zones."
  }
}

variable "logs_kms_key_arn" {
  description = "KMS key for encrypting VPC flow logs."
  type        = string
}
