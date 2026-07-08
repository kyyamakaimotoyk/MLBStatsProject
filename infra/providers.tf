provider "aws" {
  region = var.aws_region

  # Applied to every resource. NBA resources carry Project=nba-game-predictor,
  # so activating Project (and League) as cost-allocation tags in the Billing
  # console splits the bill between the two projects.
  default_tags {
    tags = {
      Project   = var.project
      League    = "MLB"
      ManagedBy = "terraform"
    }
  }
}
