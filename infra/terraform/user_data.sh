#!/bin/bash
# user_data.sh — bootstrap script de cada EC2 worker.
#
# Roda no primeiro boot via cloud-init. Saída fica em /var/log/cloud-init-output.log
# (útil pra debugar se algo falhar).
#
# IMPORTANTE: este arquivo passa por templatefile() do Terraform antes de virar
# user_data. Placeholders Terraform usam sintaxe dolar-chave-var-chave; para preservar
# sintaxe bash dolar-chave-VAR-chave, use escape com dolar duplo. $(...) bash funciona normal.

set -euxo pipefail

# ----------------------------------------------------------------------------
# 1. Atualiza e instala dependências de sistema
# ----------------------------------------------------------------------------
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    git \
    curl \
    ca-certificates \
    gnupg \
    lsb-release

# ----------------------------------------------------------------------------
# 2. Instala Docker (padrão oficial Ubuntu)
# ----------------------------------------------------------------------------
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$${VERSION_CODENAME}") stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    docker-ce \
    docker-ce-cli \
    containerd.io \
    docker-buildx-plugin \
    docker-compose-plugin

systemctl enable docker
systemctl start docker

# ----------------------------------------------------------------------------
# 3. Instala Ollama nativamente (sem container — mais rápido pra boot)
# ----------------------------------------------------------------------------
curl -fsSL https://ollama.com/install.sh | sh
systemctl enable ollama
systemctl start ollama

# Aguarda Ollama ficar pronto antes de pull do modelo
for i in {1..30}; do
    if curl -s http://localhost:11434/ > /dev/null; then
        break
    fi
    sleep 2
done

# Baixa modelo de embedding (~274 MB)
ollama pull nomic-embed-text

# ----------------------------------------------------------------------------
# 4. Clona o repo e prepara o worker
# ----------------------------------------------------------------------------
cd /opt
git clone --branch ${git_branch} ${git_repo_url} harness-rag
cd harness-rag

# Builda a imagem do worker (mesma do Dockerfile que já temos)
docker build -t harness-rag-worker .

# ----------------------------------------------------------------------------
# 5. Sobe o worker como container
# ----------------------------------------------------------------------------
# Diferenças vs docker-compose local:
# - Ollama está NA MESMA EC2 (host network simplifica): host.docker.internal não funciona
#   em Linux; usar --network=host pro container ver localhost:11434 direto.
# - SEM AWS_ENDPOINT_URL: boto3 fala com AWS real, não LocalStack.
# - Credenciais vêm do IAM Role anexado à EC2 — boto3 detecta sozinho via Instance Metadata.
# - Idle timeout = 0 (infinito): worker em produção fica disponível pra mais jobs.

mkdir -p /data/vectorstore

docker run -d \
    --name harness-worker \
    --restart unless-stopped \
    --network=host \
    -e AWS_DEFAULT_REGION=${aws_region} \
    -e OLLAMA_HOST=http://localhost:11434 \
    -e OLLAMA_BASE_URL=http://localhost:11434 \
    -e SQS_QUEUE_NAME=${sqs_queue_name} \
    -e WORKER_IDLE_TIMEOUT_SEC=0 \
    -e CHROMA_PERSIST_DIR=/data/vectorstore \
    -v /data/vectorstore:/data/vectorstore \
    -v /opt/harness-rag/dados/corpus:/app/dados/corpus:ro \
    harness-rag-worker \
    python infra/worker.py

echo "Bootstrap concluido. Worker rodando."
