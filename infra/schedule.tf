# Daily pipeline run at 14:00 UTC (10:00 ET in summer) — after west-coast
# games finish and before the day's slate firms up. The task itself handles
# "no games today" gracefully.

data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${var.project}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

resource "aws_iam_role_policy" "scheduler" {
  name = "run-pipeline-task"
  role = aws_iam_role.scheduler.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ecs:RunTask"]
        Resource = ["${replace(aws_ecs_task_definition.pipeline.arn, "/:\\d+$/", "")}:*"]
        Condition = {
          ArnEquals = { "ecs:cluster" = aws_ecs_cluster.main.arn }
        }
      },
      {
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = [aws_iam_role.task_execution.arn, aws_iam_role.pipeline_task.arn]
      }
    ]
  })
}

# Afternoon prediction refreshes at 18:00/21:00/23:00 UTC (2pm/5pm/7pm ET):
# posted lineups (~2-4h pregame), late probable announcements, and fresher
# pregame lines. Predictions upsert, so each run sharpens the morning run
# rather than duplicating it. Started games are skipped by the slate's
# Preview filter, and the odds capture stores pregame lines only.
resource "aws_scheduler_schedule" "lineup_refresh" {
  name                         = "${var.project}-lineup-refresh"
  schedule_expression          = "cron(0 18,21,23 * * ? *)"
  schedule_expression_timezone = "UTC"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_ecs_cluster.main.arn
    role_arn = aws_iam_role.scheduler.arn

    ecs_parameters {
      task_definition_arn = aws_ecs_task_definition.pipeline.arn
      launch_type         = "FARGATE"
      network_configuration {
        subnets          = aws_subnet.public[*].id
        security_groups  = [aws_security_group.pipeline_task.id]
        assign_public_ip = true
      }
    }

    retry_policy {
      maximum_retry_attempts = 1
    }
  }
}

# Same-day score refresh: a light ingest-only run (--scores-only) every two
# hours through the game window, so finals and pick grading reach the site
# the same evening instead of at the next morning run. 20:00/22:00 UTC catch
# day games (4pm/6pm ET); 00:00-06:00 UTC catch the night slate through late
# west-coast finishes. Off-slate hours are a cheap no-op.
resource "aws_scheduler_schedule" "score_refresh" {
  name                         = "${var.project}-score-refresh"
  schedule_expression          = "cron(0 0,2,4,6,20,22 * * ? *)"
  schedule_expression_timezone = "UTC"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_ecs_cluster.main.arn
    role_arn = aws_iam_role.scheduler.arn

    input = jsonencode({
      containerOverrides = [{
        name    = "pipeline"
        command = ["python", "-m", "orchestration.daily", "--scores-only"]
      }]
    })

    ecs_parameters {
      task_definition_arn = aws_ecs_task_definition.pipeline.arn
      launch_type         = "FARGATE"
      network_configuration {
        subnets          = aws_subnet.public[*].id
        security_groups  = [aws_security_group.pipeline_task.id]
        assign_public_ip = true
      }
    }

    retry_policy {
      maximum_retry_attempts = 1
    }
  }
}

resource "aws_scheduler_schedule" "daily_pipeline" {
  name                         = "${var.project}-daily-pipeline"
  schedule_expression          = "cron(0 14 * * ? *)"
  schedule_expression_timezone = "UTC"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_ecs_cluster.main.arn
    role_arn = aws_iam_role.scheduler.arn

    ecs_parameters {
      task_definition_arn = aws_ecs_task_definition.pipeline.arn
      launch_type         = "FARGATE"
      network_configuration {
        subnets          = aws_subnet.public[*].id
        security_groups  = [aws_security_group.pipeline_task.id]
        assign_public_ip = true
      }
    }

    retry_policy {
      maximum_retry_attempts = 1
    }
  }
}
