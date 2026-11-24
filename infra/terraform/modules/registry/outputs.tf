output "repository_urls" {
  description = "Repository URLs by name."
  value       = { for name, repo in aws_ecr_repository.this : name => repo.repository_url }
}

output "repository_arns" {
  description = "Repository ARNs by name."
  value       = { for name, repo in aws_ecr_repository.this : name => repo.arn }
}
