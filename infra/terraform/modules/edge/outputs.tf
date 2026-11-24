output "distribution_domain_name" {
  description = "CloudFront domain name; the DNS record of the application host points here."
  value       = aws_cloudfront_distribution.this.domain_name
}

output "distribution_id" {
  description = "CloudFront distribution ID (invalidations after a web release)."
  value       = aws_cloudfront_distribution.this.id
}

output "web_bucket" {
  description = "Bucket the built web app is uploaded to."
  value       = aws_s3_bucket.web.bucket
}

output "web_acl_name" {
  description = "Web ACL name (CloudWatch dimension)."
  value       = aws_wafv2_web_acl.this.name
}
