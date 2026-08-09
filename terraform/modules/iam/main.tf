resource "aws_iam_role" "batch" {
  name = "${var.project}-batch-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Project     = var.project
    Environment = "localstack"
  }
}

resource "aws_iam_policy" "s3_rw" {
  name = "${var.project}-s3-rw-policy"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket"
        ]
        Resource = concat(
          [for b in var.bucket_names : "arn:aws:s3:::${b}"],
          [for b in var.bucket_names : "arn:aws:s3:::${b}/*"]
        )
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "batch_s3" {
  role       = aws_iam_role.batch.name
  policy_arn = aws_iam_policy.s3_rw.arn
}

resource "aws_iam_instance_profile" "batch" {
  name = "${var.project}-batch-instance-profile"
  role = aws_iam_role.batch.name
}
