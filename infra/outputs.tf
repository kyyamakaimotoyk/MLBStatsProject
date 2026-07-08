output "db_endpoint" {
  value       = aws_db_instance.main.address
  description = "RDS Postgres hostname (MLB_DB_HOST in .env)"
}

output "db_port" {
  value       = aws_db_instance.main.port
  description = "RDS Postgres port"
}

output "db_name" {
  value       = aws_db_instance.main.db_name
  description = "Database name"
}

output "db_username" {
  value       = aws_db_instance.main.username
  description = "Master username"
}

output "db_secret_arn" {
  value       = aws_db_instance.main.master_user_secret[0].secret_arn
  description = "Secrets Manager ARN holding the master password (MLB_DB_SECRET_ARN in .env)"
}

output "data_bucket" {
  value       = aws_s3_bucket.data.bucket
  description = "S3 bucket for raw archives, model artifacts, and exports"
}
