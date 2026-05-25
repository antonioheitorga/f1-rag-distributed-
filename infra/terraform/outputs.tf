# outputs.tf — valores expostos depois do `terraform apply`.
#
# Acessar com: terraform output <nome>
# Útil pra automação (ex: pegar IPs pra rodar SSH em loop).

output "sqs_main_queue_url" {
  description = "URL da fila principal — usar no producer.py local."
  value       = aws_sqs_queue.main.url
}

output "sqs_main_queue_arn" {
  description = "ARN da fila principal."
  value       = aws_sqs_queue.main.arn
}

output "sqs_dlq_url" {
  description = "URL da DLQ — usar no dlq_inspector.py local."
  value       = aws_sqs_queue.dlq.url
}

output "worker_public_ips" {
  description = "IPs públicos das EC2 workers (pra SSH)."
  value       = aws_instance.worker[*].public_ip
}

output "worker_instance_ids" {
  description = "IDs das EC2 workers (pra usar em comandos da AWS CLI)."
  value       = aws_instance.worker[*].id
}

output "ssh_commands" {
  description = "Comandos prontos pra fazer SSH em cada worker."
  value = [
    for ip in aws_instance.worker[*].public_ip :
    "ssh -i ~/.ssh/id_ed25519 ubuntu@${ip}"
  ]
}
