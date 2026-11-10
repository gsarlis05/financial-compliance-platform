output "alarm_topic_arn" {
  description = "Topic that receives every alarm."
  value       = aws_sns_topic.alarms.arn
}
