variable "name_prefix" {
  description = "Prefix for resource names, e.g. fcp-pilot."
  type        = string
}

variable "kms_key_arn" {
  description = "KMS key for the alarm topic."
  type        = string
}

variable "alarm_email" {
  description = "Address that receives alarms (it must confirm the subscription). Empty for none."
  type        = string
  default     = ""
}

variable "database_identifier" {
  description = "RDS instance identifier."
  type        = string
}

variable "load_balancer_arn_suffix" {
  description = "Load balancer ARN suffix."
  type        = string
}

variable "target_group_arn_suffix" {
  description = "API target group ARN suffix."
  type        = string
}

variable "cluster_name" {
  description = "ECS cluster name."
  type        = string
}

variable "cluster_arn" {
  description = "ECS cluster ARN."
  type        = string
}

variable "log_group_name" {
  description = "Application log group (JSON lines with a level field)."
  type        = string
}

variable "database_free_storage_gb" {
  description = "Alarm when the database has less free storage than this."
  type        = number
  default     = 10
}
