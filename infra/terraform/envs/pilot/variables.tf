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
  description = "AWS account IDs this configuration may touch (the separate pilot account). Required."
  type        = list(string)

  validation {
    condition     = length(var.allowed_account_ids) >= 1
    error_message = "Set allowed_account_ids to the approved pilot account."
  }
}

variable "app_host" {
  description = "Public host name of the application, e.g. app.example.com."
  type        = string
}

variable "image" {
  description = "API image by digest (repository@sha256:...), built, scanned and signed by the release process."
  type        = string
}

variable "regional_certificate_arn" {
  description = "ACM certificate for app_host in the region (internal load balancer)."
  type        = string
}

variable "global_certificate_arn" {
  description = "ACM certificate for app_host in us-east-1 (CloudFront)."
  type        = string
}

variable "oidc_issuer" {
  description = "OIDC issuer URL of the identity provider (owner decision: hosted Keycloak or a managed provider)."
  type        = string
}

variable "oidc_client_id" {
  description = "OIDC client ID of the application."
  type        = string
  default     = "fcp-web"
}

variable "clamd_host" {
  description = "Host name of the internal antivirus (ClamAV) service."
  type        = string
}

variable "alarm_email" {
  description = "Address that receives alarms."
  type        = string
}
