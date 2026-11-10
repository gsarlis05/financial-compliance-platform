# Alarms (M5-5). Everything goes to one encrypted topic; a person subscribes by e-mail.
#
# - Database: CPU, free storage.
# - Application: server errors and unhealthy targets at the load balancer, no running API task,
#   and error-level log lines (the application logs JSON; this is the error tracking for the
#   pilot, with no third-party service receiving application data).
# - Jobs: any task that stops with a non-zero exit code, which includes the nightly integrity,
#   audit-chain and actuals checks and the migration task.

data "aws_caller_identity" "current" {}

resource "aws_sns_topic" "alarms" {
  name              = "${var.name_prefix}-alarms"
  kms_master_key_id = var.kms_key_arn
}

data "aws_iam_policy_document" "alarms" {
  statement {
    sid       = "AlarmsAndEventsPublish"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alarms.arn]
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

resource "aws_sns_topic_policy" "alarms" {
  arn    = aws_sns_topic.alarms.arn
  policy = data.aws_iam_policy_document.alarms.json
}

resource "aws_sns_topic_subscription" "email" {
  count = var.alarm_email == "" ? 0 : 1

  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

locals {
  alarms = {
    database-cpu = {
      description = "Database CPU above 80% for 15 minutes"
      namespace   = "AWS/RDS", metric = "CPUUtilization", statistic = "Average"
      dimensions  = { DBInstanceIdentifier = var.database_identifier }
      comparison  = "GreaterThanThreshold", threshold = 80, periods = 3, period = 300
      missing     = "missing"
    }
    database-storage = {
      description = "Database free storage below ${var.database_free_storage_gb} GiB"
      namespace   = "AWS/RDS", metric = "FreeStorageSpace", statistic = "Minimum"
      dimensions  = { DBInstanceIdentifier = var.database_identifier }
      comparison  = "LessThanThreshold", threshold = var.database_free_storage_gb * 1024 * 1024 * 1024
      periods     = 1, period = 300
      missing     = "breaching"
    }
    api-server-errors = {
      description = "More than 5 server errors (5xx) from the API in 5 minutes"
      namespace   = "AWS/ApplicationELB", metric = "HTTPCode_Target_5XX_Count", statistic = "Sum"
      dimensions  = { LoadBalancer = var.load_balancer_arn_suffix }
      comparison  = "GreaterThanThreshold", threshold = 5, periods = 1, period = 300
      missing     = "notBreaching"
    }
    api-unhealthy = {
      description = "An API task fails its readiness check"
      namespace   = "AWS/ApplicationELB", metric = "UnHealthyHostCount", statistic = "Maximum"
      dimensions  = { LoadBalancer = var.load_balancer_arn_suffix, TargetGroup = var.target_group_arn_suffix }
      comparison  = "GreaterThanThreshold", threshold = 0, periods = 3, period = 60
      missing     = "notBreaching"
    }
    api-not-running = {
      description = "No API task is running"
      namespace   = "ECS/ContainerInsights", metric = "RunningTaskCount", statistic = "Minimum"
      dimensions  = { ClusterName = var.cluster_name, ServiceName = "api" }
      comparison  = "LessThanThreshold", threshold = 1, periods = 2, period = 60
      missing     = "breaching"
    }
    application-errors = {
      description = "The application logged an error"
      namespace   = "${var.name_prefix}/app", metric = "ErrorLogLines", statistic = "Sum"
      dimensions  = {}
      comparison  = "GreaterThanThreshold", threshold = 0, periods = 1, period = 300
      missing     = "notBreaching"
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "this" {
  for_each = local.alarms

  alarm_name          = "${var.name_prefix}-${each.key}"
  alarm_description   = each.value.description
  namespace           = each.value.namespace
  metric_name         = each.value.metric
  statistic           = each.value.statistic
  dimensions          = each.value.dimensions
  comparison_operator = each.value.comparison
  threshold           = each.value.threshold
  evaluation_periods  = each.value.periods
  period              = each.value.period
  treat_missing_data  = each.value.missing
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_log_metric_filter" "errors" {
  name           = "${var.name_prefix}-error-log-lines"
  log_group_name = var.log_group_name
  pattern        = "{ ($.level = \"error\") || ($.level = \"critical\") }"

  metric_transformation {
    name          = "ErrorLogLines"
    namespace     = "${var.name_prefix}/app"
    value         = "1"
    default_value = "0"
  }
}

resource "aws_cloudwatch_event_rule" "task_failed" {
  name        = "${var.name_prefix}-task-failed"
  description = "A task stopped with a non-zero exit code (a check, a migration or a crash)"

  event_pattern = jsonencode({
    source        = ["aws.ecs"]
    "detail-type" = ["ECS Task State Change"]
    detail = {
      clusterArn = [var.cluster_arn]
      lastStatus = ["STOPPED"]
      containers = { exitCode = [{ "anything-but" = [0] }] }
    }
  })
}

resource "aws_cloudwatch_event_target" "task_failed" {
  rule = aws_cloudwatch_event_rule.task_failed.name
  arn  = aws_sns_topic.alarms.arn

  input_transformer {
    input_paths = {
      group  = "$.detail.group"
      reason = "$.detail.stoppedReason"
      task   = "$.detail.taskArn"
    }
    input_template = "\"A task of <group> stopped with an error: <reason> (<task>)\""
  }
}
