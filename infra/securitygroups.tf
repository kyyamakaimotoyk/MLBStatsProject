resource "aws_security_group" "rds" {
  vpc_id      = aws_vpc.main.id
  name        = "${var.project}-rds"
  description = "Postgres access for local development"

  ingress {
    description = "Postgres from home IP"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = [var.home_ip_cidr]
  }

  ingress {
    description     = "Postgres from the daily pipeline Fargate task"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.pipeline_task.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = -1
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project}-rds-sg"
  }
}
