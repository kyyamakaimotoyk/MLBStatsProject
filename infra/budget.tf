# MLB-scoped monthly budget, filtered by the Project cost-allocation tag so
# it counts ONLY this project's spend (the NBA account-wide budget predates
# tag discipline and counts everything). Note: the account's two free budgets
# are used; this third one bills ~$0.02/day.

variable "budget_email" {
  type        = string
  default     = "yamamotokai518@gmail.com"
  description = "Where budget alerts go"
}

resource "aws_budgets_budget" "mlb_monthly" {
  name         = "${var.project}-monthly"
  budget_type  = "COST"
  limit_amount = "60"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_filter {
    name   = "TagKeyValue"
    values = ["user:Project$mlb-stats"]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.budget_email]
  }
}
