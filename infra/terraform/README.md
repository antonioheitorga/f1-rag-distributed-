# Terraform — Provisionamento AWS Academy

Infraestrutura como código para subir o fluxo Harness em AWS real (EC2 + SQS + CloudWatch).

## O que é provisionado

| Recurso | Quantidade | Função |
|---|---|---|
| SQS Main Queue | 1 | Fila `ingestion-jobs` |
| SQS Dead Letter Queue | 1 | Fila `ingestion-jobs-dlq` (após 3 falhas) |
| IAM Role + Instance Profile | 1 | Permissões SQS + CloudWatch para EC2 |
| Security Group | 1 | SSH inbound (porta 22) + saída livre |
| Key Pair | 1 | Sua chave SSH pública registrada na AWS |
| EC2 t3.medium | 3 (configurável) | Workers — cada uma com Ollama + Docker + worker.py |

## Pré-requisitos

1. **AWS CLI** instalado (`aws --version` deve responder)
2. **Terraform** instalado (`terraform version` deve responder)
3. **Chave SSH local** existente:
   ```powershell
   # Se ainda não tem:
   ssh-keygen -t ed25519 -C "harness-rag" -f $env:USERPROFILE\.ssh\id_ed25519 -N '""'
   ```
4. **AWS Academy Lab ativo** com credenciais copiadas

## Como usar

### 1. Iniciar o lab AWS Academy e copiar credenciais

No portal da Academy, clique **Start Lab**. Quando o LED ficar verde, abra **AWS Details > AWS CLI > Show**. Copie as 3 linhas (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`).

### 2. Configurar credenciais no PowerShell

```powershell
$env:AWS_ACCESS_KEY_ID = "ASIA..."
$env:AWS_SECRET_ACCESS_KEY = "..."
$env:AWS_SESSION_TOKEN = "..."
$env:AWS_DEFAULT_REGION = "us-east-1"

# Validar:
aws sts get-caller-identity
```

Se aparecer um JSON com `Account` e `Arn`, está autenticado.

### 3. Provisionar

```powershell
cd infra\terraform

# Primeira vez: baixa o provider AWS (uma única vez por máquina)
terraform init

# Mostra o que SERIA criado (não cria nada ainda)
terraform plan

# Cria tudo (pede confirmação interativa antes de aplicar)
terraform apply
```

Aplicar leva ~2-3 min. EC2 leva mais ~5-7 min depois do apply pra terminar o `user_data.sh` (instalar Docker, baixar Ollama e modelo, buildar imagem).

### 4. Ver outputs

```powershell
terraform output                     # tudo
terraform output sqs_main_queue_url  # só a URL da fila
terraform output worker_public_ips   # só os IPs das EC2
```

### 5. Rodar o producer apontando para AWS real

Como `AWS_ENDPOINT_URL` não está setado, boto3 usa endpoints reais da AWS:

```powershell
cd ..\..

# Garante que nenhum endpoint LocalStack vaza:
Remove-Item Env:AWS_ENDPOINT_URL -ErrorAction SilentlyContinue

# Publica os 6 jobs no SQS REAL:
python infra\producer.py
```

Em poucos segundos, os workers EC2 começam a processar.

### 6. Acompanhar via CloudWatch

```powershell
python infra\metrics_viewer.py --by-worker
```

Ou abra a console da AWS (browser) → CloudWatch → Metrics → Custom namespaces → `F1RagHarness`.

### 7. SSH em um worker pra debugar (opcional)

```powershell
ssh -i $env:USERPROFILE\.ssh\id_ed25519 ubuntu@<IP_PUBLICO>

# Lá dentro:
docker ps                              # ver container do worker
docker logs harness-worker --follow    # logs ao vivo
sudo cat /var/log/cloud-init-output.log  # ver bootstrap do user_data
```

### 8. Destruir tudo quando terminar

```powershell
terraform destroy
```

**Sempre rode antes de encerrar o lab Academy.** Senão as EC2 ficam ligadas consumindo crédito.

## Estrutura de arquivos

```
infra/terraform/
├── versions.tf       # Versões fixas do Terraform e provider AWS
├── variables.tf      # Entradas configuráveis (worker_count, instance_type, etc.)
├── main.tf           # Os recursos AWS de fato
├── outputs.tf        # Valores expostos depois do apply
├── user_data.sh      # Bootstrap script de cada EC2 (Docker + Ollama + worker)
├── .gitignore        # Não commitar state nem credenciais
└── README.md         # Este arquivo
```

## Customização

Sobrescrever variáveis sem editar `variables.tf`:

```powershell
# Inline:
terraform apply -var "worker_count=5" -var "instance_type=t3.large"

# Ou via terraform.tfvars (arquivo local, gitignored):
@'
worker_count  = 5
instance_type = "t3.large"
'@ | Out-File terraform.tfvars -Encoding utf8
terraform apply
```

## Pegadinhas conhecidas

**Credenciais expiram em ~4h.** Se o `terraform apply` rodar com credenciais expirando no meio, ele falha. Solução: re-exporte as 3 variáveis e rode `terraform apply` de novo — Terraform é idempotente e continua de onde parou.

**EC2 pode demorar para terminar o bootstrap.** O `apply` retorna assim que a EC2 está "running", mas o `user_data.sh` ainda está rodando por dentro (5-7 min). Acompanhe via:

```powershell
ssh -i ~/.ssh/id_ed25519 ubuntu@<IP> "tail -f /var/log/cloud-init-output.log"
```

**Esqueceu de rodar `terraform destroy`?** Crédito vai vazando. Mesmo que o Academy expire, EC2 continua ligada. Se ficou esquecida: dar Start Lab de novo, exportar credenciais novas, rodar `terraform destroy`.

**`terraform.tfstate` é local.** Se você apagar esse arquivo sem antes destruir os recursos, Terraform "esquece" o que existe. Pra recuperar: ou recria do zero ou importa manualmente com `terraform import`.

## Custo estimado (AWS Academy)

| Recurso | Custo/h | Observação |
|---|---|---|
| 3× t3.medium | ~$0.12 | Único custo significativo |
| SQS | ~$0 | Free tier cobre easy 1M requests/mês |
| CloudWatch | ~$0 | Free tier cobre as métricas que emitimos |
| Tráfego de rede | ~$0 | Ingestão interna não custa |

Sessão completa (apply → testar → destroy) gasta ~$0.20–0.50. Folga grande dentro dos $100 da Academy.
