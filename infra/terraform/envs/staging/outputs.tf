output "database_endpoint" {
  description = "PostgreSQL endpoint."
  value       = module.database.endpoint
}

output "database_secret_arn" {
  description = "Secrets Manager ARN of the managed database master credentials."
  value       = module.database.master_user_secret_arn
}

output "documents_bucket" {
  description = "Document and evidence bucket."
  value       = module.storage.documents_bucket
}
