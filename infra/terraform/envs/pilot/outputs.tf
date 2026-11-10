output "distribution_domain_name" {
  description = "Point the DNS record of the application host here."
  value       = module.edge.distribution_domain_name
}

output "distribution_id" {
  description = "CloudFront distribution ID."
  value       = module.edge.distribution_id
}

output "web_bucket" {
  description = "Bucket the built web app is uploaded to."
  value       = module.edge.web_bucket
}

output "image_repository" {
  description = "Repository the API image is pushed to."
  value       = module.registry.repository_urls["backend"]
}

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

output "ops_task_definition_arn" {
  description = "Task definition for the migration and other owner-role one-off tasks."
  value       = module.app.ops_task_definition_arn
}

output "secrets_to_fill" {
  description = "Secrets an operator must fill in before the first start."
  value       = module.app.secret_names
}

output "backup_vault" {
  description = "Backup vault name."
  value       = module.backup.vault_name
}

output "alarm_topic_arn" {
  description = "Topic that receives every alarm."
  value       = module.monitoring.alarm_topic_arn
}
