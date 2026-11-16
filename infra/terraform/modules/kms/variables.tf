variable "name_prefix" {
  description = "Prefix for resource names, e.g. fcp-staging."
  type        = string
}

variable "region" {
  description = "AWS region (EU only)."
  type        = string
}
