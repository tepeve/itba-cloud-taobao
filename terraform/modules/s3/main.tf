resource "aws_s3_bucket" "datalake" {
  bucket = var.bucket_name

  tags = {
    Name        = var.bucket_name
    Project     = var.project
    Environment = "localstack"
  }
}

resource "aws_s3_bucket_public_access_block" "datalake" {
  bucket                  = aws_s3_bucket.datalake.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}