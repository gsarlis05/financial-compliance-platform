output "vpc_id" {
  description = "VPC ID."
  value       = aws_vpc.this.id
}

output "vpc_cidr_block" {
  description = "VPC CIDR block."
  value       = aws_vpc.this.cidr_block
}

output "app_subnet_ids" {
  description = "Private subnets for application workloads."
  value       = aws_subnet.app[*].id
}

output "data_subnet_ids" {
  description = "Private subnets for data stores (no route to the internet)."
  value       = aws_subnet.data[*].id
}

output "app_subnet_cidrs" {
  description = "CIDR blocks of the application subnets."
  value       = aws_subnet.app[*].cidr_block
}

output "main_route_table_id" {
  description = "The VPC's main route table (used by the private subnets; gateway endpoints attach here)."
  value       = aws_vpc.this.main_route_table_id
}
