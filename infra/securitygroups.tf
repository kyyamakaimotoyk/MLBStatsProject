resource "aws_security_group" "rds" {
  vpc_id      = aws_vpc.main.id
  name        = "${var.project}-rds"
  description = "Postgres access for local development"

  # Dev phase: only the home IP may reach Postgres. In Phase 6 the pipeline
  # task security group gets its own ingress rule here.
  ingress {
    description = "Postgres from home IP"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = [var.home_ip_cidr]
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
