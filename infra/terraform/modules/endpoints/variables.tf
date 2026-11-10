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
  description = "VPC CIDR block (who may use the endpoints)."
  type        = string
}

variable "subnet_ids" {
  description = "Private application subnets the interface endpoints live in."
  type        = list(string)
}

variable "route_table_ids" {
  description = "Route tables that get the S3 gateway endpoint."
  type        = list(string)
}

variable "interface_services" {
  description = "AWS services reached privately through interface endpoints."
  type        = set(string)
  default     = ["ecr.api", "ecr.dkr", "logs", "secretsmanager", "kms"]
}
