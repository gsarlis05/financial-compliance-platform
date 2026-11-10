output "security_group_id" {
  description = "Security group of the interface endpoints."
  value       = aws_security_group.endpoints.id
}

output "s3_prefix_list_id" {
  description = "Prefix list of the S3 gateway endpoint (for egress rules)."
  value       = aws_vpc_endpoint.s3.prefix_list_id
}
