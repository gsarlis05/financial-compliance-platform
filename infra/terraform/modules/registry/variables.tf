variable "name_prefix" {
  description = "Prefix for resource names, e.g. fcp-pilot."
  type        = string
}

variable "kms_key_arn" {
  description = "KMS key for image encryption at rest."
  type        = string
}

variable "repositories" {
  description = "Image repositories to create."
  type        = set(string)
  default     = ["backend"]
}

variable "keep_images" {
  description = "How many images to keep per repository (older ones expire)."
  type        = number
  default     = 30
}
