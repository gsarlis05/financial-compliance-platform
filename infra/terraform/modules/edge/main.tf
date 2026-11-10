# The public entrance (M5-5; docs/deployment/aws.md): one origin for the browser.
#
#   Browser ──HTTPS──► CloudFront + WAF ─┬─ /*              ──► private S3 bucket: the built web app
#                                         └─ /api/*, /auth/* ──► internal load balancer (VPC origin)
#
# One origin keeps the `__Host-` session cookie, strict CSRF and the content security policy
# exactly as in local development and in the production-like smoke test.

data "aws_caller_identity" "current" {}

locals {
  web_bucket      = "${var.name_prefix}-web-${data.aws_caller_identity.current.account_id}"
  waf_logs_bucket = "aws-waf-logs-${var.name_prefix}-${data.aws_caller_identity.current.account_id}"

  # Same policy as frontend/nginx (security-headers.conf).
  content_security_policy = join("; ", [
    "default-src 'self'", "script-src 'self'", "style-src 'self'", "img-src 'self' data:",
    "font-src 'self'", "connect-src 'self'", "object-src 'none'", "base-uri 'self'",
    "frame-ancestors 'none'", "form-action 'self' ${var.idp_origin}",
  ])

  # AWS managed policies (fixed IDs, documented by AWS).
  cache_optimized       = "658327ea-f89d-4fab-a63d-7e88639e58f6"
  cache_disabled        = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
  forward_all_to_origin = "216adef6-5c7f-47e4-b989-5492eafa07d3"

  # Managed rule groups besides the known-bad-inputs group, which is written out below.
  managed_rules = {
    AWSManagedRulesAmazonIpReputationList = 10
    AWSManagedRulesCommonRuleSet          = 30
  }
}

# --- the built web app ------------------------------------------------------------------------

resource "aws_s3_bucket" "web" {
  # checkov:skip=CKV_AWS_145:Public web assets (the same files every visitor downloads); SSE-S3 lets CloudFront read them without a key grant.
  # checkov:skip=CKV_AWS_144:The web app is rebuilt from source; replication adds nothing.
  # checkov:skip=CKV2_AWS_62:No event notifications are needed for static files.
  bucket        = local.web_bucket
  force_destroy = false
}

resource "aws_s3_bucket_public_access_block" "web" {
  bucket                  = aws_s3_bucket.web.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "web" {
  bucket = aws_s3_bucket.web.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_versioning" "web" {
  bucket = aws_s3_bucket.web.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "web" {
  bucket = aws_s3_bucket.web.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "web" {
  bucket = aws_s3_bucket.web.id
  rule {
    id     = "expire-old-releases"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = 90
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

resource "aws_s3_bucket_logging" "web" {
  bucket        = aws_s3_bucket.web.id
  target_bucket = var.access_logs_bucket
  target_prefix = "web/"
}

data "aws_iam_policy_document" "web" {
  statement {
    sid       = "CloudFrontReadsTheWebApp"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.web.arn}/*"]
    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.this.arn]
    }
  }
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.web.arn, "${aws_s3_bucket.web.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "web" {
  bucket = aws_s3_bucket.web.id
  policy = data.aws_iam_policy_document.web.json
}

# --- firewall ---------------------------------------------------------------------------------

resource "aws_wafv2_web_acl" "this" {
  provider = aws.global

  name        = var.name_prefix
  description = "Managed protections and a per-address rate limit for ${var.app_host}"
  scope       = "CLOUDFRONT"

  default_action {
    allow {}
  }

  rule {
    name     = "rate-limit"
    priority = 1

    action {
      block {}
    }

    statement {
      rate_based_statement {
        limit              = var.rate_limit
        aggregate_key_type = "IP"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.name_prefix}-rate-limit"
      sampled_requests_enabled   = true
    }
  }

  # Known bad inputs, including the Log4j lookups (CVE-2021-44228).
  rule {
    name     = "AWSManagedRulesKnownBadInputsRuleSet"
    priority = 20

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.name_prefix}-AWSManagedRulesKnownBadInputsRuleSet"
      sampled_requests_enabled   = true
    }
  }

  dynamic "rule" {
    for_each = local.managed_rules

    content {
      name     = rule.key
      priority = rule.value

      override_action {
        none {}
      }

      statement {
        managed_rule_group_statement {
          name        = rule.key
          vendor_name = "AWS"

          # The common rules block request bodies over 8 KB, which would stop document and bank
          # statement uploads. The application enforces its own upload limits, so that one rule
          # only counts.
          dynamic "rule_action_override" {
            for_each = rule.key == "AWSManagedRulesCommonRuleSet" ? ["SizeRestrictions_BODY"] : []

            content {
              name = rule_action_override.value
              action_to_use {
                count {}
              }
            }
          }
        }
      }

      visibility_config {
        cloudwatch_metrics_enabled = true
        metric_name                = "${var.name_prefix}-${rule.key}"
        sampled_requests_enabled   = true
      }
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = var.name_prefix
    sampled_requests_enabled   = true
  }
}

# Firewall logs are kept in the EU region (an S3 bucket may be in any region; a log group for a
# CloudFront web ACL would have to be in us-east-1).
resource "aws_s3_bucket" "waf_logs" {
  # checkov:skip=CKV_AWS_145:Log delivery to this bucket uses SSE-S3.
  # checkov:skip=CKV_AWS_144:Replication of firewall logs is planned with the DR design (Gate G).
  # checkov:skip=CKV2_AWS_62:No event notifications are needed for firewall logs.
  # checkov:skip=CKV_AWS_18:This bucket holds logs itself.
  bucket        = local.waf_logs_bucket
  force_destroy = false
}

resource "aws_s3_bucket_public_access_block" "waf_logs" {
  bucket                  = aws_s3_bucket.waf_logs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "waf_logs" {
  bucket = aws_s3_bucket.waf_logs.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_versioning" "waf_logs" {
  bucket = aws_s3_bucket.waf_logs.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "waf_logs" {
  bucket = aws_s3_bucket.waf_logs.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "waf_logs" {
  bucket = aws_s3_bucket.waf_logs.id
  rule {
    id     = "expire-firewall-logs"
    status = "Enabled"
    filter {}
    expiration {
      days = var.waf_log_retention_days
    }
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

data "aws_iam_policy_document" "waf_logs" {
  statement {
    sid       = "LogDeliveryWrite"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.waf_logs.arn}/AWSLogs/${data.aws_caller_identity.current.account_id}/*"]
    principals {
      type        = "Service"
      identifiers = ["delivery.logs.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
  statement {
    sid       = "LogDeliveryAclCheck"
    actions   = ["s3:GetBucketAcl"]
    resources = [aws_s3_bucket.waf_logs.arn]
    principals {
      type        = "Service"
      identifiers = ["delivery.logs.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.waf_logs.arn, "${aws_s3_bucket.waf_logs.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "waf_logs" {
  bucket = aws_s3_bucket.waf_logs.id
  policy = data.aws_iam_policy_document.waf_logs.json
}

resource "aws_wafv2_web_acl_logging_configuration" "this" {
  provider = aws.global

  resource_arn            = aws_wafv2_web_acl.this.arn
  log_destination_configs = [aws_s3_bucket.waf_logs.arn]

  # Session cookies and tokens never reach the logs.
  redacted_fields {
    single_header {
      name = "cookie"
    }
  }
  redacted_fields {
    single_header {
      name = "authorization"
    }
  }
  redacted_fields {
    single_header {
      name = "x-csrftoken"
    }
  }

  depends_on = [aws_s3_bucket_policy.waf_logs]
}

# --- distribution -----------------------------------------------------------------------------

resource "aws_cloudfront_origin_access_control" "web" {
  name                              = "${var.name_prefix}-web"
  description                       = "CloudFront reads the private web bucket"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_vpc_origin" "api" {
  vpc_origin_endpoint_config {
    name                   = "${var.name_prefix}-api"
    arn                    = var.load_balancer_arn
    http_port              = 80
    https_port             = 443
    origin_protocol_policy = "https-only"

    origin_ssl_protocols {
      items    = ["TLSv1.2"]
      quantity = 1
    }
  }
}

# Client-side routes (/w/…) have no file in the bucket: serve the app shell for them. Done here
# and not with custom error responses, which would also replace the API's own 404 answers.
resource "aws_cloudfront_function" "spa" {
  name    = "${var.name_prefix}-spa-routes"
  runtime = "cloudfront-js-2.0"
  comment = "Serve index.html for client-side routes"
  publish = true
  code    = <<-EOT
    function handler(event) {
      var request = event.request;
      var last = request.uri.split('/').pop();
      if (last.indexOf('.') === -1) {
        request.uri = '/index.html';
      }
      return request;
    }
  EOT
}

resource "aws_cloudfront_response_headers_policy" "security" {
  # checkov:skip=CKV_AWS_259:HSTS is sent for a year with subdomains. Preload is left off on purpose until the domain is final, as in the application (SECURE_HSTS_PRELOAD).
  name    = "${var.name_prefix}-security-headers"
  comment = "The same security headers as the nginx web image"

  security_headers_config {
    content_security_policy {
      content_security_policy = local.content_security_policy
      override                = false
    }
    content_type_options {
      override = true
    }
    frame_options {
      frame_option = "DENY"
      override     = true
    }
    referrer_policy {
      referrer_policy = "same-origin"
      override        = true
    }
    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = true
      override                   = true
    }
  }

  custom_headers_config {
    items {
      header   = "Permissions-Policy"
      value    = "camera=(), microphone=(), geolocation=(), payment=()"
      override = true
    }
    items {
      header   = "Cross-Origin-Opener-Policy"
      value    = "same-origin"
      override = true
    }
  }
}

resource "aws_cloudfront_distribution" "this" {
  # checkov:skip=CKV_AWS_86:Requests are logged by the firewall (every request, to the EU bucket above) and by the load balancer; CloudFront standard logs would need bucket ACLs.
  # checkov:skip=CKV_AWS_310:Origin failover needs a second region; it follows with the DR design (Gate G).
  # checkov:skip=CKV2_AWS_47:The attached web ACL has the AWSManagedRulesKnownBadInputsRuleSet group (Log4j), which CKV_AWS_192 confirms; this graph check does not resolve the web ACL through the provider alias.
  # checkov:skip=CKV_AWS_374:Geo restriction is a product decision for the owner; none is set for the pilot.
  enabled             = true
  comment             = var.name_prefix
  aliases             = [var.app_host]
  default_root_object = "index.html"
  http_version        = "http2and3"
  is_ipv6_enabled     = true
  price_class         = "PriceClass_100"
  web_acl_id          = aws_wafv2_web_acl.this.arn

  origin {
    origin_id                = "web"
    domain_name              = aws_s3_bucket.web.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.web.id
  }

  origin {
    origin_id   = "api"
    domain_name = var.load_balancer_dns_name

    vpc_origin_config {
      vpc_origin_id = aws_cloudfront_vpc_origin.api.id
    }
  }

  default_cache_behavior {
    target_origin_id           = "web"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true
    cache_policy_id            = local.cache_optimized
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.spa.arn
    }
  }

  dynamic "ordered_cache_behavior" {
    for_each = ["/api/*", "/auth/*"]

    content {
      path_pattern               = ordered_cache_behavior.value
      target_origin_id           = "api"
      viewer_protocol_policy     = "https-only"
      allowed_methods            = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
      cached_methods             = ["GET", "HEAD"]
      compress                   = true
      cache_policy_id            = local.cache_disabled
      origin_request_policy_id   = local.forward_all_to_origin
      response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = var.certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }
}
