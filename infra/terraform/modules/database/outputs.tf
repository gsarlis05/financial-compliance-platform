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

output "arn" {
  description = "Database instance ARN (for backup selection)."
  value       = aws_db_instance.this.arn
}

output "identifier" {
  description = "Database instance identifier (for alarms)."
  value       = aws_db_instance.this.identifier
}

output "address" {
  description = "Database host name."
  value       = aws_db_instance.this.address
}
