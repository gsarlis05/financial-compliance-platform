terraform {
  required_version = ">= 1.9"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
      # aws.global is us-east-1: AWS requires the web ACL of a CloudFront distribution there.
      # No customer data is stored there (firewall logs go to a bucket in the EU region).
      configuration_aliases = [aws.global]
    }
  }
}
