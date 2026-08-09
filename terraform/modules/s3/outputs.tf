output "bucket_arn" {
  value = aws_s3_bucket.datalake.arn
}

output "bucket_name" {
  value = aws_s3_bucket.datalake.bucket
}