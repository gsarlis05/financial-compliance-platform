output "endpoint" {
  description = "Database endpoint (host:port)."
  value       = aws_db_instance.this.endpoint
}

output "master_user_secret_arn" {
  description = "Secrets Manager ARN of the managed master credentials."
  value       = aws_db_instance.this.master_user_secret[0].secret_arn
}

output "security_group_id" {
  description = "Database security group."
  value       = aws_security_group.db.id
}
