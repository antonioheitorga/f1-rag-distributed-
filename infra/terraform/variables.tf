# variables.tf — entradas configuráveis da infra.
#
# Valores podem ser sobrescritos via:
# - terraform.tfvars (arquivo local, fora do git por segurança)
# - -var "nome=valor" na CLI
# - TF_VAR_<nome> como variável de ambiente

variable "aws_region" {
  description = "Região AWS onde provisionar tudo. us-east-1 é o default da Academy."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Prefixo dos nomes dos recursos. Útil pra distinguir do LAPES original."
  type        = string
  default     = "harness-rag"
}

variable "worker_count" {
  description = "Quantas instâncias EC2 subir como workers. 3 é o sweet spot pra demo."
  type        = number
  default     = 3
}

variable "instance_type" {
  description = "Tipo da EC2. t3.medium = 4GB RAM, mínimo viável pra Ollama com nomic-embed-text."
  type        = string
  default     = "t3.medium"
}

variable "ssh_public_key_path" {
  description = "Caminho do .pub local para registrar como key pair na AWS (acesso SSH às EC2)."
  type        = string
  default     = "~/.ssh/id_ed25519.pub"
}

variable "git_repo_url" {
  description = "URL do repositório git clonado pelas EC2 no boot. Público pra evitar tokens."
  type        = string
  default     = "https://github.com/antonioheitorga/f1-rag-distributed-.git"
}

variable "git_branch" {
  description = "Branch a clonar nos workers EC2."
  type        = string
  default     = "develop"
}

variable "sqs_queue_name" {
  description = "Nome da fila principal SQS."
  type        = string
  default     = "ingestion-jobs"
}

variable "sqs_dlq_name" {
  description = "Nome da Dead Letter Queue SQS."
  type        = string
  default     = "ingestion-jobs-dlq"
}

variable "sqs_max_receive_count" {
  description = "Quantas falhas antes da mensagem ir pra DLQ."
  type        = number
  default     = 3
}
