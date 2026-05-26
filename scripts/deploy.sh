#!/bin/bash
#
# deploy.sh - provisiona ou destroi a infraestrutura AWS do projeto.
#
# Uso:
#   scripts/deploy.sh up           # provisiona (default worker_count=3)
#   scripts/deploy.sh up 1         # provisiona com 1 worker apenas
#   scripts/deploy.sh down         # destroi tudo
#   scripts/deploy.sh plan         # mostra o plano sem aplicar
#
# Pre-requisitos:
#   - Terraform >= 1.5 e AWS CLI no PATH
#   - Credenciais AWS exportadas (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY,
#     AWS_SESSION_TOKEN se for AWS Academy)
#   - Chave SSH em ~/.ssh/id_ed25519.pub
#
# Este script e apenas um wrapper sobre os comandos terraform documentados
# em infra/terraform/README.md. Use o comando direto se preferir controle
# fino sobre cada etapa.

set -euo pipefail

ACTION="${1:-up}"
WORKER_COUNT="${2:-3}"

TF_DIR="$(cd "$(dirname "$0")/.." && pwd)/infra/terraform"

# Sanity checks antes de comecar
command -v terraform >/dev/null || { echo "ERRO: terraform nao esta no PATH"; exit 1; }
command -v aws >/dev/null || { echo "ERRO: aws CLI nao esta no PATH"; exit 1; }

if ! aws sts get-caller-identity >/dev/null 2>&1; then
    echo "ERRO: credenciais AWS invalidas ou expiradas."
    echo "Exporte AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY e (se Academy) AWS_SESSION_TOKEN."
    exit 1
fi

cd "$TF_DIR"

case "$ACTION" in
    up)
        echo ">>> Provisionando infraestrutura com worker_count=$WORKER_COUNT..."
        terraform init -input=false
        terraform apply -var "worker_count=$WORKER_COUNT" -auto-approve
        echo ""
        echo ">>> Aguarde ~5 min para o user_data.sh terminar o bootstrap das EC2."
        echo ">>> Para acompanhar uma EC2 especifica:"
        echo ">>>   ssh -i ~/.ssh/id_ed25519 ubuntu@<ip> 'tail -f /var/log/cloud-init-output.log'"
        ;;
    down)
        echo ">>> Destruindo infraestrutura..."
        terraform destroy -auto-approve
        ;;
    plan)
        echo ">>> Mostrando plano (sem aplicar)..."
        terraform init -input=false
        terraform plan -var "worker_count=$WORKER_COUNT"
        ;;
    *)
        echo "ERRO: acao desconhecida '$ACTION'. Use up, down ou plan."
        exit 1
        ;;
esac
