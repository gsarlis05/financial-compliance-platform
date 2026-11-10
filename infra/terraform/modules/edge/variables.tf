variable "name_prefix" {
  description = "Prefix for resource names, e.g. fcp-pilot."
  type        = string
}

variable "app_host" {
  description = "Public host name of the application, e.g. app.example.com."
  type        = string
}

variable "idp_origin" {
  description = "Origin of the identity provider (https://…), allowed as a form target by the content security policy."
  type        = string

  validation {
    condition     = can(regex("^https://[^/ ;]+$", var.idp_origin))
    error_message = "Give the identity provider origin as https://host, without a path."
  }
}

variable "certificate_arn" {
  description = "ACM certificate for the host name, in us-east-1 (required by CloudFront)."
  type        = string
}

variable "load_balancer_arn" {
  description = "Internal load balancer serving /api and /auth."
  type        = string
}

variable "load_balancer_dns_name" {
  description = "DNS name of the internal load balancer."
  type        = string
}

variable "access_logs_bucket" {
  description = "S3 bucket for server access logs of the web bucket."
  type        = string
}

variable "rate_limit" {
  description = "Requests allowed per IP address in 5 minutes before the firewall blocks it."
  type        = number
  default     = 2000
}

variable "waf_log_retention_days" {
  description = "How long firewall logs are kept."
  type        = number
  default     = 365
}
