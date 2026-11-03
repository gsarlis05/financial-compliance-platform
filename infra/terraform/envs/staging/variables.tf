variable "region" {
  description = "AWS region. EU regions only (data residency, docs/planning/01 §6)."
  type        = string
  default     = "eu-central-1"

  validation {
    condition     = startswith(var.region, "eu-")
    error_message = "Only EU regions are allowed."
  }
}

variable "allowed_account_ids" {
  description = "AWS account IDs this configuration may touch (guards against the wrong account). Required."
  type        = list(string)

  validation {
    condition     = length(var.allowed_account_ids) >= 1
    error_message = "Set allowed_account_ids to the approved staging account."
  }
}
