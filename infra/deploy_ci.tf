# GitHub Actions deploys the static site (web/) via OIDC — no stored AWS keys.
# The workflow (.github/workflows/deploy-site.yml) assumes this role, which can
# only sync the site bucket and invalidate the site distribution, and can only
# be assumed by this repo's master branch.
#
# The account-level GitHub OIDC provider predates this project (created for
# hoopmodel), so it's referenced here rather than managed.

data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}

locals {
  github_repo = "kyyamakaimotoyk/MLBStatsProject"
}

resource "aws_iam_role" "site_deploy" {
  name = "${var.project}-site-deploy"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = data.aws_iam_openid_connect_provider.github.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        }
        StringLike = {
          "token.actions.githubusercontent.com:sub" = "repo:${local.github_repo}:ref:refs/heads/master"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "site_deploy" {
  name = "site-deploy"
  role = aws_iam_role.site_deploy.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = aws_s3_bucket.site.arn
      },
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"]
        Resource = "${aws_s3_bucket.site.arn}/*"
      },
      {
        Effect   = "Allow"
        Action   = "cloudfront:CreateInvalidation"
        Resource = aws_cloudfront_distribution.site.arn
      }
    ]
  })
}

output "site_deploy_role_arn" {
  value       = aws_iam_role.site_deploy.arn
  description = "IAM role assumed by the GitHub Actions site-deploy workflow"
}
