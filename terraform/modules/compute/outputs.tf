output "instance_id" {
  value = aws_instance.airflow_orchestrator.id
}

output "instance_private_ip" {
  value = aws_instance.airflow_orchestrator.private_ip
}
