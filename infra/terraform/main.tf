# main.tf — recursos AWS provisionados pra rodar o Harness em produção.
#
# Estrutura do que será criado:
#   1. Provider AWS (us-east-1)
#   2. SQS Dead Letter Queue
#   3. SQS Main Queue (com RedrivePolicy apontando pra DLQ)
#   4. IAM Role + Instance Profile (workers precisam permissão pra SQS + CloudWatch)
#   5. Security Group (apenas SSH inbound + tudo outbound)
#   6. Key Pair (chave pública SSH local registrada na AWS)
#   7. N instâncias EC2 (workers) com user_data que bootstrapa Docker + repo + worker.py
#
# Cada recurso aparece como `resource "tipo_aws" "nome_local" { ... }`.
# Você referencia outros recursos com `tipo_aws.nome_local.atributo`.

# ----------------------------------------------------------------------------
# Provider
# ----------------------------------------------------------------------------
# Configura como o Terraform fala com a AWS.
# Credenciais vêm das variáveis de ambiente AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
# e AWS_SESSION_TOKEN (Academy é sempre temporária = precisa session token).

provider "aws" {
  region = var.aws_region
}

# ----------------------------------------------------------------------------
# AMI base — busca o ID mais recente do Ubuntu 22.04 LTS oficial.
# ----------------------------------------------------------------------------
# AMI = Amazon Machine Image. É o "snapshot" usado pra criar EC2.
# Cada região tem AMIs diferentes; data source consulta a Canonical (publisher
# oficial do Ubuntu) e pega a versão mais nova. Evita hardcoded de ID
# regional que ficaria desatualizado.

data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical (mantenedor oficial do Ubuntu)

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }
}

# ----------------------------------------------------------------------------
# SQS — Dead Letter Queue
# ----------------------------------------------------------------------------
# Criada PRIMEIRO porque a fila principal precisa referenciar o ARN dela
# na RedrivePolicy. Terraform resolve a ordem automaticamente, mas declarar
# nessa ordem ajuda a leitura.

resource "aws_sqs_queue" "dlq" {
  name                      = var.sqs_dlq_name
  message_retention_seconds = 1209600 # 14 dias — mensagens mortas guardadas pra debug

  tags = {
    Project = var.project_name
    Role    = "dlq"
  }
}

# ----------------------------------------------------------------------------
# SQS — Main Queue
# ----------------------------------------------------------------------------
# Fila que producer publica e workers consomem.
# RedrivePolicy: depois de maxReceiveCount tentativas sem delete, mensagem
# vai pra DLQ automaticamente (mesmo padrão do LocalStack).

resource "aws_sqs_queue" "main" {
  name                       = var.sqs_queue_name
  visibility_timeout_seconds = 600   # 10 min p/ worker processar antes de mensagem reaparecer
  message_retention_seconds  = 86400 # 1 dia

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = var.sqs_max_receive_count
  })

  tags = {
    Project = var.project_name
    Role    = "main"
  }
}

# ----------------------------------------------------------------------------
# IAM — Instance Profile (usando o pré-criado do AWS Academy)
# ----------------------------------------------------------------------------
# A role `voclabs` do Academy não tem permissão pra criar IAM Roles novos
# (iam:CreateRole é bloqueado). Em vez disso, reutilizamos o `LabInstanceProfile`
# pré-criado pela infra do Academy — ele já vem com permissões pra SQS,
# CloudWatch, EC2 e outros serviços essenciais.
#
# Trade-off: perdemos o princípio do menor privilégio (o LabInstanceProfile
# tem mais permissões que precisamos). Em produção real, criaríamos o role
# customizado. Aqui é restrição do ambiente Academy.

# ----------------------------------------------------------------------------
# Networking — Security Group
# ----------------------------------------------------------------------------
# Firewall da EC2. Pelo princípio do menor privilégio:
# - Inbound: só SSH (porta 22) da internet (pra debug — ideal seria do seu IP)
# - Outbound: tudo (precisa baixar Docker, Ollama, modelo, falar com SQS)

resource "aws_security_group" "worker" {
  name        = "${var.project_name}-worker-sg"
  description = "Security group dos workers Harness"

  ingress {
    description = "SSH for debug"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"] # qualquer IP — em prod, restringir ao seu IP
  }

  egress {
    description = "Outbound unrestricted (Docker pull, Ollama, SQS, CloudWatch)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1" # qualquer protocolo
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Project = var.project_name
  }
}

# ----------------------------------------------------------------------------
# SSH Key Pair
# ----------------------------------------------------------------------------
# Registra a chave PÚBLICA local na AWS pra você poder `ssh` na EC2 sem
# senha. A chave privada NUNCA sai do seu computador.

resource "aws_key_pair" "worker" {
  key_name   = "${var.project_name}-key"
  public_key = file(pathexpand(var.ssh_public_key_path))
}

# ----------------------------------------------------------------------------
# EC2 — Workers
# ----------------------------------------------------------------------------
# `count = N` cria N instâncias idênticas. Cada uma vira `aws_instance.worker[0]`,
# `aws_instance.worker[1]`, etc.
#
# user_data é um script bash que roda na primeira boot da máquina.
# Bootstraps: Docker + Git + clone do repo + build da imagem + run do worker.

resource "aws_instance" "worker" {
  count                  = var.worker_count
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  vpc_security_group_ids = [aws_security_group.worker.id]
  iam_instance_profile   = "LabInstanceProfile"
  key_name               = aws_key_pair.worker.key_name

  # Script que roda no primeiro boot. Lê o arquivo user_data.sh,
  # substitui placeholders ${var}, e injeta como cloud-init.
  user_data = templatefile("${path.module}/user_data.sh", {
    aws_region     = var.aws_region
    sqs_queue_name = var.sqs_queue_name
    git_repo_url   = var.git_repo_url
    git_branch     = var.git_branch
  })

  # Força recriação se o user_data mudar (mudou script = quer reprovisionar)
  user_data_replace_on_change = true

  # Tamanho do disco — Ollama + modelo + Docker images ocupam ~10GB.
  root_block_device {
    volume_size = 20 # GB
    volume_type = "gp3"
  }

  tags = {
    Name    = "${var.project_name}-worker-${count.index + 1}"
    Project = var.project_name
    Role    = "worker"
  }
}
