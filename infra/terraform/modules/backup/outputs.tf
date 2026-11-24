output "vault_name" {
  description = "Backup vault name."
  value       = aws_backup_vault.this.name
}
