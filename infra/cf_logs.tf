# =============================================================================
# CloudFront access logs -> S3: visitor analytics for moundmodel.com
# =============================================================================
# CloudFront writes one log row per request (path, referrer, user-agent, status,
# rough geo) to this bucket; query with Athena (see analytics.tf and the
# local-only dashboard in visualization/site_traffic.py). This uses CloudFront's
# "legacy" S3 logging, which — unlike the rest of our buckets — requires ACLs
# ENABLED on the destination plus a grant to CloudFront's log-delivery account.
# (The site bucket stays OAC-only and private; only THIS logs bucket relaxes to
# ACLs, and it holds nothing sensitive.)
# =============================================================================

# The bucket owner's canonical user id (needed to express the ACL grants).
data "aws_canonical_user_id" "current" {}

resource "aws_s3_bucket" "logs" {
  bucket = "${var.project}-logs-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "logs" {
  bucket                  = aws_s3_bucket.logs.id
  block_public_acls       = true # blocks PUBLIC acls only; the CloudFront grant is to a specific account
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# CloudFront legacy logging delivers objects via ACL, so allow ACLs
# (BucketOwnerPreferred) instead of the modern default (BucketOwnerEnforced).
resource "aws_s3_bucket_ownership_controls" "logs" {
  bucket = aws_s3_bucket.logs.id
  rule {
    object_ownership = "BucketOwnerPreferred"
  }
}

# Grant FULL_CONTROL to the bucket owner + CloudFront's log-delivery account.
resource "aws_s3_bucket_acl" "logs" {
  depends_on = [aws_s3_bucket_ownership_controls.logs]
  bucket     = aws_s3_bucket.logs.id

  access_control_policy {
    owner {
      id = data.aws_canonical_user_id.current.id
    }
    grant {
      grantee {
        type = "CanonicalUser"
        id   = data.aws_canonical_user_id.current.id
      }
      permission = "FULL_CONTROL"
    }
    grant {
      grantee {
        type = "CanonicalUser"
        # CloudFront "awslogsdelivery" account — fixed, AWS-published canonical id.
        id = "c4c1ede66af53448b93c283ce9448c4ba468c9432aa01d700d3878632f77d2d0"
      }
      permission = "FULL_CONTROL"
    }
  }
}

# SSE-S3 (AES256). CloudFront legacy logging does NOT support SSE-KMS buckets.
resource "aws_s3_bucket_server_side_encryption_configuration" "logs" {
  bucket = aws_s3_bucket.logs.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Don't keep logs forever.
resource "aws_s3_bucket_lifecycle_configuration" "logs" {
  bucket = aws_s3_bucket.logs.id
  rule {
    id     = "expire-cf-logs"
    status = "Enabled"
    filter {
      prefix = "cf-site/"
    }
    expiration {
      days = 90
    }
  }
  rule {
    id     = "expire-athena-results"
    status = "Enabled"
    filter {
      prefix = "athena-results/"
    }
    expiration {
      days = 30
    }
  }
  # The API distribution logs one row per XHR, so this grows faster than the
  # site prefix and has no Athena table pointed at it — it exists for cache
  # hit-rate spot checks, not analytics.
  rule {
    id     = "expire-cf-api-logs"
    status = "Enabled"
    filter {
      prefix = "cf-api/"
    }
    expiration {
      days = 30
    }
  }
}

output "logs_bucket" {
  description = "CloudFront access logs land here (cf-site/ and cf-api/); query with Athena"
  value       = aws_s3_bucket.logs.bucket
}
