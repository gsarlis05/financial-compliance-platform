# Customer-managed KMS keys, one per data class, with automatic annual rotation.
# Per-tenant document data keys are envelope-encrypted under the "documents" key by the
# application (docs/planning/04 §6); this module only creates the root keys.

data "aws_caller_identity" "current" {}

locals {
  # "application": container images, runtime secrets and the alarm topic (M5-5).
  purposes = toset(["database", "documents", "logs", "backups", "application"])
}

data "aws_iam_policy_document" "key" {
  # checkov:skip=CKV_AWS_111:Key policy; Resource "*" means this key only. Standard AWS default admin statement.
  # checkov:skip=CKV_AWS_356:Key policy; Resource "*" means this key only.
  # checkov:skip=CKV_AWS_109:Key policy; account-root administration is the AWS default and is required to avoid an unmanageable key.

  # Account administrators manage the key; usage grants are given to service roles elsewhere.
  statement {
    sid       = "AccountAdministration"
    actions   = ["kms:*"]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
  }

  statement {
    sid       = "CloudWatchLogsUse"
    actions   = ["kms:Encrypt*", "kms:Decrypt*", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:Describe*"]
    resources = ["*"]
    principals {
      type        = "Service"
      identifiers = ["logs.${var.region}.amazonaws.com"]
    }
    condition {
      test     = "ArnLike"
      variable = "kms:EncryptionContext:aws:logs:arn"
      values   = ["arn:aws:logs:${var.region}:${data.aws_caller_identity.current.account_id}:log-group:*"]
    }
  }

  # Alarms and event rules publish to the encrypted alarm topic (M5-5).
  statement {
    sid       = "AlarmPublishersUse"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey*"]
    resources = ["*"]
    principals {
      type        = "Service"
      identifiers = ["cloudwatch.amazonaws.com", "events.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_kms_key" "this" {
  for_each = local.purposes

  description             = "${var.name_prefix} ${each.key} encryption key"
  enable_key_rotation     = true
  rotation_period_in_days = 365
  deletion_window_in_days = 30
  policy                  = data.aws_iam_policy_document.key.json
}

resource "aws_kms_alias" "this" {
  for_each = local.purposes

  name          = "alias/${var.name_prefix}-${each.key}"
  target_key_id = aws_kms_key.this[each.key].key_id
}
