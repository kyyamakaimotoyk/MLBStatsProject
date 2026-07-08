variable "aws_region" {
  type        = string
  default     = "us-east-1"
  description = "AWS region used for all resources"
}

variable "project" {
  type        = string
  default     = "mlb-stats"
  description = "Short name; used as a prefix and tag on resources"
}

variable "vpc_cidr" {
  type        = string
  default     = "10.20.0.0/16"
  description = "IP range for the VPC (distinct from the NBA project's 10.0.0.0/16)"
}

variable "public_subnet_cidrs" {
  type        = list(string)
  default     = ["10.20.0.0/24", "10.20.1.0/24"]
  description = "CIDRs for the public subnets (one per AZ; RDS subnet groups need two AZs)"
}

variable "db_instance_class" {
  type        = string
  default     = "db.t4g.micro"
  description = "RDS instance size"
}

variable "db_name" {
  type        = string
  default     = "mlb_data"
  description = "Initial database name"
}

variable "db_username" {
  type        = string
  default     = "mlbadmin"
  description = "RDS master username"
}

# Dev-phase access model: the DB is publicly accessible but the security group
# only admits this CIDR. Update terraform.tfvars and re-apply when your IP changes.
variable "home_ip_cidr" {
  type        = string
  description = "Your machine's public IP as a /32 CIDR, e.g. 1.2.3.4/32"
}
