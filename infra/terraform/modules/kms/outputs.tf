output "key_arns" {
  description = "KMS key ARNs by purpose (database, documents, logs, backups)."
  value       = { for purpose, key in aws_kms_key.this : purpose => key.arn }
}
