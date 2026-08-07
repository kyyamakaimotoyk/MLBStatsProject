# Public API: small always-on Fargate service behind an ALB at api.<domain>.

resource "aws_ecr_repository" "api" {
  name         = "${var.project}-api"
  force_delete = true
}

resource "aws_ecr_lifecycle_policy" "api" {
  repository = aws_ecr_repository.api.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "keep last 5 images"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 5 }
      action       = { type = "expire" }
    }]
  })
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${var.project}-api"
  retention_in_days = 30
}

# AWS-managed list of the addresses CloudFront uses to reach origins. Looked up
# rather than hardcoded: the id differs per region, and AWS edits the contents
# as the edge fleet changes.
data "aws_ec2_managed_prefix_list" "cloudfront_origin" {
  name = "com.amazonaws.global.cloudfront.origin-facing"
}

resource "aws_security_group" "alb" {
  vpc_id      = aws_vpc.main.id
  name = "${var.project}-alb"
  # NOTE: a security group's description is immutable in AWS, so editing this
  # string forces Terraform to REPLACE the group — which briefly leaves the ALB
  # and the task security group pointing at different ids and fails health
  # checks. It is deliberately left at its original wording; the accurate
  # description of what this group now does is the comment below.
  description = "Public HTTPS to the API load balancer"

  # CloudFront is the only way in. Without this the CDN is trivially
  # bypassable — api-origin.<domain> is published in Certificate Transparency
  # logs, so the hostname is enumerable by anyone — and a bypass puts load
  # straight onto a single 0.25 vCPU task with no autoscaling, skipping the
  # edge cache that is this service's entire capacity buffer. It also makes
  # any future WAF or rate limit attached to the distribution enforceable
  # rather than decorative.
  #
  # 443 only. The prefix list holds ~45 entries and each counts toward the
  # 60-rules-per-security-group quota, so it cannot go on two ports — and it
  # does not need to: CloudFront reaches the origin with
  # origin_protocol_policy = "https-only" (infra/api_cdn.tf).
  ingress {
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    prefix_list_ids = [data.aws_ec2_managed_prefix_list.cloudfront_origin.id]
    description     = "HTTPS from CloudFront origin-facing ranges only"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = -1
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "api_task" {
  vpc_id      = aws_vpc.main.id
  name        = "${var.project}-api-task"
  description = "API Fargate task; only the ALB may reach it"
  ingress {
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = -1
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_lb" "api" {
  name               = "${var.project}-api"
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id
}

resource "aws_lb_target_group" "api" {
  name        = "${var.project}-api"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"
  health_check {
    path                = "/api/health"
    interval            = 30
    healthy_threshold   = 2
    unhealthy_threshold = 5
  }
}

resource "aws_lb_listener" "api_https" {
  load_balancer_arn = aws_lb.api.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = aws_acm_certificate_validation.site.certificate_arn
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

# Unreachable while the security group above is CloudFront-only (CloudFront
# talks HTTPS to the origin, and nothing else can reach the ALB at all). Kept
# so that re-opening port 80 is a one-line change rather than a rebuild, and
# so a stray plaintext request gets a redirect instead of a connection reset
# if the group is ever widened.
resource "aws_lb_listener" "api_http_redirect" {
  load_balancer_arn = aws_lb.api.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${var.project}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.pipeline_task.arn # S3 read + DB secret

  container_definitions = jsonencode([{
    name      = "api"
    image     = "${aws_ecr_repository.api.repository_url}:latest"
    essential = true
    portMappings = [{ containerPort = 8000, protocol = "tcp" }]
    environment = [
      { name = "AWS_REGION", value = var.aws_region },
      { name = "MLB_DB_HOST", value = aws_db_instance.main.address },
      { name = "MLB_DB_PORT", value = "5432" },
      { name = "MLB_DB_NAME", value = var.db_name },
      { name = "MLB_DB_USER", value = var.db_username },
      { name = "MLB_DB_SECRET_ARN", value = aws_db_instance.main.master_user_secret[0].secret_arn },
      { name = "ALLOWED_ORIGINS", value = "https://${var.site_domain},https://www.${var.site_domain}" },
      # Only the API sets this — the pipeline task deliberately has no ceiling
      # (feature builds and walk-forward pulls run for minutes). Without it,
      # one runaway query pins a slot in a 5-connection pool on a
      # single-worker process.
      #
      # 30s is not arbitrary: it matches origin_read_timeout on the CloudFront
      # distribution (infra/api_cdn.tf), so the database abandons a statement
      # at the same moment the CDN stops waiting for it, instead of burning a
      # pool slot producing a response nobody will receive. The slowest
      # legitimate statement measured 2.6s — /api/performance at its 365-day
      # max, which fetches ~124k un-deduplicated prediction rows and backs the
      # /performance page — so this clips nothing real.
      { name = "MLB_DB_STATEMENT_TIMEOUT", value = "30s" },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.api.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "api"
      }
    }
  }])
}

resource "aws_ecs_service" "api" {
  name            = "${var.project}-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  # Fargate usage is billed per task, so cost allocation needs the Project tag
  # on the tasks themselves — the service/task-definition tags don't count.
  enable_ecs_managed_tags = true
  propagate_tags          = "SERVICE"

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.api_task.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  depends_on = [aws_lb_listener.api_https]
}

# Points at CloudFront, not the ALB — see api_cdn.tf. The ALB stays reachable
# directly on api-origin.<domain> for isolating CDN problems from origin ones.
resource "aws_route53_record" "api" {
  zone_id = data.aws_route53_zone.site.zone_id
  name    = "api.${var.site_domain}"
  type    = "A"
  alias {
    name                   = aws_cloudfront_distribution.api.domain_name
    zone_id                = aws_cloudfront_distribution.api.hosted_zone_id
    evaluate_target_health = false
  }
}

output "api_url" {
  value = "https://api.${var.site_domain}"
}
