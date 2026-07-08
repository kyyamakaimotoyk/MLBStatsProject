resource "aws_db_subnet_group" "main" {
  name       = "${var.project}-db-subnets"
  subnet_ids = aws_subnet.public[*].id
  tags = {
    Name = "${var.project}-db-subnets"
  }
}

resource "aws_db_instance" "main" {
  identifier        = "${var.project}-db"
  engine            = "postgres"
  engine_version    = "17"
  instance_class    = var.db_instance_class
  allocated_storage = 20
  # Statcast pitch data (~3M rows) plus everything else fits in a few GB;
  # autoscaling headroom so a backfill never hits a storage wall.
  max_allocated_storage = 50
  storage_type          = "gp3"
  storage_encrypted     = true
  db_name               = var.db_name
  username              = var.db_username
  # Master password lives in Secrets Manager, managed and rotated by RDS.
  # core/db.py fetches it at startup, so rotation never breaks clients
  # (the NBA project's rotated-password pain point, solved structurally).
  manage_master_user_password = true
  db_subnet_group_name        = aws_db_subnet_group.main.name
  vpc_security_group_ids      = [aws_security_group.rds.id]
  multi_az                    = false
  # Public during the local-dev phases; the security group restricts to home IP.
  # RDS Postgres 15+ defaults rds.force_ssl=1, so connections are TLS-only.
  publicly_accessible     = true
  backup_retention_period = 7
  skip_final_snapshot     = true
  deletion_protection     = false
  apply_immediately       = true
  tags = {
    Name = "${var.project}-db-instance"
  }
}
