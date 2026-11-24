output "load_balancer_arn" {
  description = "Internal load balancer ARN (the CloudFront VPC origin)."
  value       = aws_lb.this.arn
}

output "load_balancer_arn_suffix" {
  description = "Load balancer ARN suffix (CloudWatch dimension)."
  value       = aws_lb.this.arn_suffix
}

output "target_group_arn_suffix" {
  description = "API target group ARN suffix (CloudWatch dimension)."
  value       = aws_lb_target_group.api.arn_suffix
}

output "cluster_name" {
  description = "ECS cluster name."
  value       = aws_ecs_cluster.this.name
}

output "cluster_arn" {
  description = "ECS cluster ARN."
  value       = aws_ecs_cluster.this.arn
}

output "log_group_name" {
  description = "Application log group."
  value       = aws_cloudwatch_log_group.app.name
}

output "ops_task_definition_arn" {
  description = "Task definition for migrations and other owner-role one-off tasks."
  value       = aws_ecs_task_definition.this["ops"].arn
}

output "secret_names" {
  description = "Secrets an operator must fill in before the first start."
  value       = [for secret in aws_secretsmanager_secret.this : secret.name]
}

output "load_balancer_dns_name" {
  description = "DNS name of the internal load balancer."
  value       = aws_lb.this.dns_name
}
