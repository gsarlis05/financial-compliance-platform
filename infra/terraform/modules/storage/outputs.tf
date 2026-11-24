output "documents_bucket" {
  description = "Name of the document and evidence bucket."
  value       = aws_s3_bucket.documents.bucket
}

output "access_logs_bucket" {
  description = "Name of the S3 server access log bucket."
  value       = aws_s3_bucket.logs.bucket
}
