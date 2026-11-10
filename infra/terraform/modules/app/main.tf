# The application on ECS Fargate (M5-5; docs/deployment/aws.md, ADR-0012).
#
# - API service and the bank-import worker run as the database **runtime** role (no schema rights,
#   no BYPASSRLS). Migrations, the nightly integrity checks and the workspace purge run as
#   one-off tasks with the **owner** role, from a separate task definition with separate secrets.
# - Tasks have no public IP, a read-only root file system and run as a non-root user (the image).
# - The load balancer is internal: only CloudFront reaches it, through a VPC origin.
# - Secret values are set by an operator in Secrets Manager; they are never in Terraform state.

data "aws_caller_identity" "current" {}

locals {
  secrets = toset(["django-secret-key", "database-runtime", "database-owner", "oidc-client-secret"])

  environment = {
    DJANGO_SETTINGS_MODULE        = "fcp.settings.prod"
    DJANGO_ALLOWED_HOSTS          = var.app_host
    CSRF_TRUSTED_ORIGINS          = "https://${var.app_host}"
    POSTGRES_HOST                 = var.database_host
    POSTGRES_DB                   = "fcp"
    POSTGRES_SSLMODE              = "verify-full"
    OIDC_ISSUER                   = var.oidc_issuer
    OIDC_CLIENT_ID                = var.oidc_client_id
    OIDC_REDIRECT_URI             = "https://${var.app_host}/auth/callback"
    OIDC_POST_LOGOUT_REDIRECT_URI = "https://${var.app_host}/"
    FORWARDED_ALLOW_IPS           = var.vpc_cidr_block
    DOCUMENTS_BUCKET              = var.documents_bucket
    DOCUMENTS_KMS_KEY_ID          = var.documents_kms_key_arn
    CLAMD_HOST                    = var.clamd_host
    AWS_DEFAULT_REGION            = var.region
  }

  common_secrets = {
    DJANGO_SECRET_KEY  = aws_secretsmanager_secret.this["django-secret-key"].arn
    OIDC_CLIENT_SECRET = aws_secretsmanager_secret.this["oidc-client-secret"].arn
  }
  runtime_secrets = merge(local.common_secrets, {
    POSTGRES_APP_USER     = "${aws_secretsmanager_secret.this["database-runtime"].arn}:username::"
    POSTGRES_APP_PASSWORD = "${aws_secretsmanager_secret.this["database-runtime"].arn}:password::"
  })
  owner_secrets = merge(local.common_secrets, {
    POSTGRES_OWNER_USER     = "${aws_secretsmanager_secret.this["database-owner"].arn}:username::"
    POSTGRES_OWNER_PASSWORD = "${aws_secretsmanager_secret.this["database-owner"].arn}:password::"
  })

  # One task definition per duty. "ops" is the only one with the owner role.
  tasks = {
    api = {
      command     = null
      environment = local.environment
      secrets     = local.runtime_secrets
      port        = true
    }
    worker = {
      command     = ["python", "manage.py", "banking_process_imports", "--loop"]
      environment = local.environment
      secrets     = local.runtime_secrets
      port        = false
    }
    ops = {
      command     = ["python", "manage.py", "migrate", "--check"]
      environment = merge(local.environment, { DB_ROLE = "owner" })
      secrets     = local.owner_secrets
      port        = false
    }
  }

  # Scheduled one-off tasks (EventBridge Scheduler). Times are UTC.
  schedules = {
    audit-verify     = { task = "ops", expression = "cron(15 1 * * ? *)", command = ["python", "manage.py", "audit_verify"] }
    ledger-integrity = { task = "ops", expression = "cron(30 1 * * ? *)", command = ["python", "manage.py", "ledger_integrity_check"] }
    actuals-verify   = { task = "ops", expression = "cron(45 1 * * ? *)", command = ["python", "manage.py", "actuals_verify"] }
    purge-workspaces = { task = "ops", expression = "cron(0 2 * * ? *)", command = ["python", "manage.py", "tenancy_purge_workspaces"] }
    cashflow-refresh = { task = "api", expression = "rate(15 minutes)", command = ["python", "manage.py", "cashflow_refresh"] }
  }
}

# --- logs and secrets ------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "app" {
  name              = "/${var.name_prefix}/app"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.logs_kms_key_arn
}

resource "aws_secretsmanager_secret" "this" {
  # checkov:skip=CKV2_AWS_57:Values are set and rotated by an operator (runbook); automatic rotation needs a rotation function per secret type and follows with the production design.
  for_each = local.secrets

  name                    = "${var.name_prefix}/${each.key}"
  kms_key_id              = var.kms_key_arn
  recovery_window_in_days = 30
}

# --- roles ------------------------------------------------------------------------------------

data "aws_iam_policy_document" "assume_tasks" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

# What ECS needs to start a task: pull the image, write logs, read that task's secrets.
resource "aws_iam_role" "execution" {
  for_each = local.tasks

  name               = "${var.name_prefix}-${each.key}-execution"
  assume_role_policy = data.aws_iam_policy_document.assume_tasks.json
}

data "aws_iam_policy_document" "execution" {
  for_each = local.tasks

  statement {
    sid       = "RegistryLogin"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"] # this action has no resource-level permissions
  }
  statement {
    sid       = "PullImage"
    actions   = ["ecr:BatchCheckLayerAvailability", "ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage"]
    resources = [var.repository_arn]
  }
  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.app.arn}:*"]
  }
  statement {
    sid       = "ReadOwnSecrets"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = distinct([for arn in values(each.value.secrets) : split(":username::", split(":password::", arn)[0])[0]])
  }
  statement {
    sid       = "DecryptSecrets"
    actions   = ["kms:Decrypt"]
    resources = [var.kms_key_arn]
  }
}

resource "aws_iam_role_policy" "execution" {
  for_each = local.tasks

  name   = "start-task"
  role   = aws_iam_role.execution[each.key].id
  policy = data.aws_iam_policy_document.execution[each.key].json
}

# What the application itself may do: documents of tenants, under the documents key.
resource "aws_iam_role" "task" {
  name               = "${var.name_prefix}-task"
  assume_role_policy = data.aws_iam_policy_document.assume_tasks.json
}

data "aws_iam_policy_document" "task" {
  statement {
    sid       = "TenantDocuments"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:GetObjectVersion"]
    resources = ["arn:aws:s3:::${var.documents_bucket}/tenants/*"]
  }
  statement {
    sid       = "DocumentsKey"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [var.documents_kms_key_arn]
  }
}

resource "aws_iam_role_policy" "task" {
  name   = "documents"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task.json
}

# The owner-role one-off tasks also purge a deleted workspace's documents (M5-6), so only they
# may list and delete objects, and only under the tenants/ prefix.
resource "aws_iam_role" "ops_task" {
  name               = "${var.name_prefix}-ops-task"
  assume_role_policy = data.aws_iam_policy_document.assume_tasks.json
}

data "aws_iam_policy_document" "ops_task" {
  source_policy_documents = [data.aws_iam_policy_document.task.json]

  statement {
    sid       = "ListTenantDocuments"
    actions   = ["s3:ListBucket", "s3:ListBucketVersions"]
    resources = ["arn:aws:s3:::${var.documents_bucket}"]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["tenants/*"]
    }
  }
  statement {
    sid       = "PurgeTenantDocuments"
    actions   = ["s3:DeleteObject", "s3:DeleteObjectVersion"]
    resources = ["arn:aws:s3:::${var.documents_bucket}/tenants/*"]
  }
}

resource "aws_iam_role_policy" "ops_task" {
  name   = "documents-and-purge"
  role   = aws_iam_role.ops_task.id
  policy = data.aws_iam_policy_document.ops_task.json
}

# --- cluster and task definitions -----------------------------------------------------------

resource "aws_ecs_cluster" "this" {
  name = var.name_prefix

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_ecs_task_definition" "this" {
  for_each = local.tasks

  family                   = "${var.name_prefix}-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = aws_iam_role.execution[each.key].arn
  task_role_arn            = each.key == "ops" ? aws_iam_role.ops_task.arn : aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([{
    name                   = "app"
    image                  = var.image
    essential              = true
    command                = each.value.command
    readonlyRootFilesystem = true
    user                   = "10001"
    portMappings           = each.value.port ? [{ containerPort = 8000, protocol = "tcp" }] : []
    environment            = [for name, value in each.value.environment : { name = name, value = value }]
    secrets                = [for name, arn in each.value.secrets : { name = name, valueFrom = arn }]
    linuxParameters        = { initProcessEnabled = true }
    mountPoints            = [{ sourceVolume = "tmp", containerPath = "/tmp", readOnly = false }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.app.name
        awslogs-region        = var.region
        awslogs-stream-prefix = each.key
      }
    }
  }])

  volume {
    name = "tmp"
  }
}

# --- network access ---------------------------------------------------------------------------

resource "aws_security_group" "alb" {
  name        = "${var.name_prefix}-alb"
  description = "Internal load balancer: HTTPS from inside the VPC (the CloudFront VPC origin)"
  vpc_id      = var.vpc_id
}

resource "aws_vpc_security_group_ingress_rule" "alb_https" {
  security_group_id = aws_security_group.alb.id
  description       = "HTTPS from the VPC"
  cidr_ipv4         = var.vpc_cidr_block
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "alb_to_tasks" {
  security_group_id            = aws_security_group.alb.id
  description                  = "To the API tasks"
  referenced_security_group_id = aws_security_group.tasks.id
  from_port                    = 8000
  to_port                      = 8000
  ip_protocol                  = "tcp"
}

resource "aws_security_group" "tasks" {
  name        = "${var.name_prefix}-tasks"
  description = "Application tasks"
  vpc_id      = var.vpc_id
}

resource "aws_vpc_security_group_ingress_rule" "tasks_from_alb" {
  security_group_id            = aws_security_group.tasks.id
  description                  = "From the load balancer"
  referenced_security_group_id = aws_security_group.alb.id
  from_port                    = 8000
  to_port                      = 8000
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "tasks_to_database" {
  security_group_id            = aws_security_group.tasks.id
  description                  = "PostgreSQL"
  referenced_security_group_id = var.database_security_group_id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "tasks_to_endpoints" {
  security_group_id            = aws_security_group.tasks.id
  description                  = "AWS service endpoints"
  referenced_security_group_id = var.endpoints_security_group_id
  from_port                    = 443
  to_port                      = 443
  ip_protocol                  = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "tasks_to_s3" {
  security_group_id = aws_security_group.tasks.id
  description       = "S3 through the gateway endpoint"
  prefix_list_id    = var.s3_prefix_list_id
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
}

resource "aws_vpc_security_group_egress_rule" "tasks_to_vpc" {
  security_group_id = aws_security_group.tasks.id
  description       = "Antivirus service and the identity provider inside the VPC"
  cidr_ipv4         = var.vpc_cidr_block
  from_port         = 0
  to_port           = 65535
  ip_protocol       = "tcp"
}

# --- load balancer ----------------------------------------------------------------------------

resource "aws_lb" "this" {
  # checkov:skip=CKV2_AWS_28:The load balancer is internal; the web application firewall is on CloudFront, the only way in.
  name                       = var.name_prefix
  internal                   = true
  load_balancer_type         = "application"
  subnets                    = var.subnet_ids
  security_groups            = [aws_security_group.alb.id]
  drop_invalid_header_fields = true
  enable_deletion_protection = true

  access_logs {
    bucket  = var.access_logs_bucket
    prefix  = "alb"
    enabled = true
  }
}

resource "aws_lb_target_group" "api" {
  # checkov:skip=CKV_AWS_378:TLS ends at the load balancer; tasks listen on HTTP inside private subnets, reachable only from the load balancer's security group.
  name        = "${var.name_prefix}-api"
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = var.vpc_id

  health_check {
    path                = "/readyz"
    matcher             = "200"
    interval            = 15
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.this.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

# --- services ---------------------------------------------------------------------------------

resource "aws_ecs_service" "api" {
  name                              = "api"
  cluster                           = aws_ecs_cluster.this.id
  task_definition                   = aws_ecs_task_definition.this["api"].arn
  desired_count                     = var.api_count
  launch_type                       = "FARGATE"
  platform_version                  = "LATEST"
  health_check_grace_period_seconds = 60

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "app"
    container_port   = 8000
  }

  depends_on = [aws_lb_listener.https]
}

resource "aws_ecs_service" "worker" {
  name             = "worker"
  cluster          = aws_ecs_cluster.this.id
  task_definition  = aws_ecs_task_definition.this["worker"].arn
  desired_count    = 1
  launch_type      = "FARGATE"
  platform_version = "LATEST"

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = false
  }
}

# --- scheduled one-off tasks ------------------------------------------------------------------

data "aws_iam_policy_document" "assume_scheduler" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${var.name_prefix}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.assume_scheduler.json
}

data "aws_iam_policy_document" "scheduler" {
  statement {
    sid       = "RunTheseTasks"
    actions   = ["ecs:RunTask"]
    resources = [for name in ["api", "ops"] : aws_ecs_task_definition.this[name].arn]
    condition {
      test     = "ArnEquals"
      variable = "ecs:cluster"
      values   = [aws_ecs_cluster.this.arn]
    }
  }
  statement {
    sid     = "PassTaskRoles"
    actions = ["iam:PassRole"]
    resources = concat(
      [aws_iam_role.task.arn, aws_iam_role.ops_task.arn],
      [for name in ["api", "ops"] : aws_iam_role.execution[name].arn],
    )
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "scheduler" {
  name   = "run-tasks"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler.json
}

resource "aws_scheduler_schedule" "this" {
  for_each = local.schedules

  name                = "${var.name_prefix}-${each.key}"
  schedule_expression = each.value.expression
  kms_key_arn         = var.kms_key_arn

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_ecs_cluster.this.arn
    role_arn = aws_iam_role.scheduler.arn

    ecs_parameters {
      task_definition_arn = aws_ecs_task_definition.this[each.value.task].arn
      launch_type         = "FARGATE"
      platform_version    = "LATEST"

      network_configuration {
        subnets          = var.subnet_ids
        security_groups  = [aws_security_group.tasks.id]
        assign_public_ip = false
      }
    }

    input = jsonencode({
      containerOverrides = [{ name = "app", command = each.value.command }]
    })

    retry_policy {
      maximum_retry_attempts = 1
    }
  }
}
