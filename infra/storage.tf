data "aws_caller_identity" "current" {}

# One bucket, three prefixes (see docs/PROJECT_PLAN.md §4):
#   raw/      gzipped raw API JSON, keyed source/date/game_pk.json.gz
#   models/   model bundles via core/artifact_store.py
#   exports/  occasional feature-set snapshots
resource "aws_s3_bucket" "data" {
  bucket = "${var.project}-data-${data.aws_caller_identity.current.account_id}"
  tags = {
    Name = "${var.project}-data"
  }
}

resource "aws_s3_bucket_versioning" "data" {
  bucket = aws_s3_bucket.data.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket                  = aws_s3_bucket.data.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Raw archives are write-once; keep noncurrent versions from accumulating cost.
resource "aws_s3_bucket_lifecycle_configuration" "data" {
  bucket = aws_s3_bucket.data.id
  rule {
    id     = "expire-noncurrent"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}
