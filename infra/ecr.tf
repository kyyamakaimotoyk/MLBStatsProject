resource "aws_ecr_repository" "pipeline" {
  name         = "${var.project}-pipeline"
  force_delete = true
  image_scanning_configuration {
    scan_on_push = false
  }
}

# Keep only the last 5 images; each is ~1GB of layers.
resource "aws_ecr_lifecycle_policy" "pipeline" {
  repository = aws_ecr_repository.pipeline.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "keep last 5 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 5
      }
      action = { type = "expire" }
    }]
  })
}
