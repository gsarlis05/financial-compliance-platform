# Backups beyond the database's own point-in-time recovery (M5-5): a separate, locked vault with
# daily and monthly copies, so a deleted or damaged database can still be restored. The restore
# drill is docs/runbooks/backup-restore-drill.md.

data "aws_caller_identity" "current" {}

resource "aws_backup_vault" "this" {
  name        = var.name_prefix
  kms_key_arn = var.kms_key_arn
}

# Recovery points cannot be deleted before their retention ends (governance mode: an account
# administrator can still lift the lock; compliance mode is a production decision).
resource "aws_backup_vault_lock_configuration" "this" {
  backup_vault_name  = aws_backup_vault.this.name
  min_retention_days = 7
}

resource "aws_backup_vault_notifications" "this" {
  backup_vault_name   = aws_backup_vault.this.name
  sns_topic_arn       = var.alarm_topic_arn
  backup_vault_events = ["BACKUP_JOB_FAILED", "BACKUP_JOB_EXPIRED", "RESTORE_JOB_FAILED"]
}

resource "aws_backup_plan" "this" {
  name = var.name_prefix

  rule {
    rule_name         = "daily"
    target_vault_name = aws_backup_vault.this.name
    schedule          = "cron(0 2 * * ? *)" # 02:00 UTC
    start_window      = 60
    completion_window = 240

    lifecycle {
      delete_after = var.daily_retention_days
    }
  }

  rule {
    rule_name         = "monthly"
    target_vault_name = aws_backup_vault.this.name
    schedule          = "cron(0 3 1 * ? *)" # 03:00 UTC on the 1st
    start_window      = 60
    completion_window = 480

    lifecycle {
      delete_after = var.monthly_retention_days
    }
  }
}

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["backup.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "backup" {
  name               = "${var.name_prefix}-backup"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

resource "aws_iam_role_policy_attachment" "backup" {
  for_each = toset(["AWSBackupServiceRolePolicyForBackup", "AWSBackupServiceRolePolicyForRestores"])

  role       = aws_iam_role.backup.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/${each.key}"
}

resource "aws_backup_selection" "this" {
  name         = "${var.name_prefix}-database"
  plan_id      = aws_backup_plan.this.id
  iam_role_arn = aws_iam_role.backup.arn
  resources    = var.resource_arns
}
