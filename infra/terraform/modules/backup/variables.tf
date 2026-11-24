variable "name_prefix" {
  description = "Prefix for resource names, e.g. fcp-pilot."
  type        = string
}

variable "kms_key_arn" {
  description = "KMS key for the backup vault."
  type        = string
}

variable "resource_arns" {
  description = "Resources to back up (the database)."
  type        = list(string)
}

variable "alarm_topic_arn" {
  description = "Topic that is told when a backup or restore job fails."
  type        = string
}

variable "daily_retention_days" {
  description = "How long daily backups are kept."
  type        = number
  default     = 35
}

variable "monthly_retention_days" {
  description = "How long monthly backups are kept."
  type        = number
  default     = 365
}
