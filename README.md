# F1 RAG Distributed

Sistema RAG multiagente sobre os regulamentos técnicos e esportivos da FIA para a temporada de Fórmula 1 2026.

**Adaptação** de um projeto base — desenvolvido por Antonio Heitor e Wisley Gabriel — para a disciplina de **Programação Distribuída e Paralela** (Harness Engineering · Tema 5 · CESUPA). A adaptação adiciona paralelismo na indexação, pool de workers distribuídos via SQS, Dead Letter Queue e métricas agregadas na AWS sobre a base multiagente original.

## Equipe da adaptação

- Antonio Heitor
- Deivison Tavares
- Carlos Eduardo

---

## Stack

| Camada | Tecnologia |
|---|---|
| Linguagem | Python 3.11+ |
| Orquestração de agentes | LangGraph |
| Vector store | ChromaDB |
| LLM | Llama 3.1 8B via Ollama |
| Embeddings | nomic-embed-text via Ollama |
| Busca web (fallback) | Tavily API |
| Interface | Streamlit |
| Extração de PDF | pdfplumber |
| Resiliência | tenacity (retry + backoff) |
| Mensageria distribuída | AWS SQS (LocalStack em dev, AWS real em produção) |
| Containerização | Docker + Docker Compose |
| Infra como código | Terraform (provider AWS 5.x) |
| Métricas | AWS CloudWatch via boto3 |
| Testes | pytest |

---

## Estrutura do projeto

```
harness-rag/
├── config.py                     # Configuração central (todas as envs e defaults)
├── app.py                        # Interface Streamlit
├── docker-compose.yml            # ollama + localstack + worker (dev local)
├── Dockerfile                    # Imagem do worker
│
├── agents/                       # 4 agentes da consulta RAG
│   ├── _retry.py                 # Política de retry compartilhada (tenacity)
│   ├── reformulator.py           # Reescreve a query
│   ├── retriever.py              # Busca vetorial no ChromaDB
│   ├── web_searcher.py           # Fallback via Tavily
│   └── generator.py              # Compõe resposta final
│
├── orchestration/
│   └── orchestrator.py           # Grafo LangGraph + _classify_source()
│
├── prompts/                      # System prompts versionados (§4.3 do enunciado)
│   ├── reformulator.md
│   └── generator.md
│
├── dados/                        # Indexação dos PDFs
│   ├── corpus/                   # 6 PDFs FIA F1 2026
│   ├── ingestion.py              # Funções de extração, chunking, embedding
│   ├── pipeline.py               # Pipeline serial (baseline)
│   ├── pipeline_parallel.py      # ProcessPoolExecutor 6 workers (paralelismo local)
│   └── scripts/                  # 01_extract.py ... 06_verify.py (thin wrappers)
│
├── infra/                        # Paralelismo distribuído AWS
│   ├── producer.py               # Publica jobs no SQS (+ cria DLQ via RedrivePolicy)
│   ├── worker.py                 # Consome SQS + processa PDF + emite métricas
│   ├── metrics.py                # Wrapper CloudWatch PutMetricData
│   ├── metrics_viewer.py         # CLI de consulta agregada de métricas
│   ├── dlq_inspector.py          # CLI de debug da DLQ
│   └── terraform/                # IaC para provisionar AWS Academy
│       ├── main.tf               # SQS + EC2 + SG + KeyPair
│       ├── user_data.sh          # Bootstrap das EC2 (Docker + Ollama + worker)
│       └── README.md             # Manual de operação Terraform
│
├── benchmarks/                   # Bônus SLM (Seção 7 do enunciado)
│   ├── benchmark.sh              # Latência embedding + concorrência Ollama
│   ├── benchmark_v2.sh           # Tokens/seg do Llama 3.2 1B em t3.medium
│   └── results.md                # Resultados consolidados
│
├── docs/
│   └── architecture.md           # Documentação arquitetural
│
├── tests/                        # Suite pytest (24 unit + 5 integration)
├── traces/                       # JSONs gerados por execução do orquestrador
└── requirements.txt
```

Diretórios gerados em runtime (`dados/extracted/`, `dados/processed/`, `dados/chunks/`, `dados/vectorstore/`, `traces/`) ficam fora do controle de versão.

Arquitetura detalhada em [docs/architecture.md](docs/architecture.md).

---

## Setup

### Pré-requisitos

- Python 3.11+
- [Ollama](https://ollama.com) instalado e rodando localmente **OU** Docker Desktop
- Docker Desktop (necessário para o fluxo distribuído via SQS)
- AWS CLI + Terraform (apenas para deploy em AWS real)

### 1. Instalar dependências

```bash
python3 -m pip install -r requirements.txt
```

### 2. Configurar variáveis de ambiente

```bash
cp .env.example .env
```

Preencher `TAVILY_API_KEY` para habilitar busca web. Demais variáveis têm defaults sensatos em `config.py` (que é a fonte única de verdade — `.env.example` é uma réplica literal).

### 3. Subir Ollama e baixar modelos

**Opção A — Docker Compose (recomendado):**

```bash
docker compose up -d ollama
docker exec -it harness-rag-ollama ollama pull llama3.1:8b
docker exec -it harness-rag-ollama ollama pull nomic-embed-text
```

**Opção B — Ollama local (sem Docker):**

```bash
ollama pull llama3.1:8b
ollama pull nomic-embed-text
```

---

## Modos de ingestão

O projeto oferece **quatro modos** de construir a base vetorial. Cada um demonstra um tipo diferente de paralelismo.

### Modo 1 — Sequencial (baseline)

Roda os 6 passos em série, um PDF por vez. Serve como referência para medir speedup.

```bash
cd dados/
python3 pipeline.py
```

Tempo medido: **79.7s** para os 6 PDFs.

### Modo 2 — Paralelo local (ProcessPoolExecutor)

Dispara N processos no mesmo computador. Cada processo processa 1 PDF independente.

```bash
cd dados/
python3 pipeline_parallel.py
INGEST_MAX_WORKERS=3 python3 pipeline_parallel.py
```

Tempo medido: **51.2s** (speedup 1.56x sobre o Modo 1).

Speedup limitado: Ollama serializa internamente as chamadas de embedding, então 6 processos competem por 1 servidor de inferência. Detalhes em `benchmarks/results.md`.

### Modo 3 — Distribuído via SQS (Docker + LocalStack)

Workers em containers consomem jobs de uma fila SQS emulada localmente.

```bash
# 1. Subir infra (Ollama + LocalStack)
docker compose up -d ollama localstack

# 2. Publicar 6 jobs e criar collection limpa
docker compose run --rm worker python infra/producer.py

# 3. Subir N workers em paralelo
docker compose up -d --scale worker=3

# 4. Aguardar workers terminarem (idle_timeout=60s no compose)
docker ps --filter "name=harness-rag-worker"

# 5. Inspecionar DLQ (deve estar vazia se tudo deu certo)
docker compose run --rm worker python infra/dlq_inspector.py
```

Tempo medido: **~60s** com 3 workers locais.

### Modo 4 — Distribuído em AWS real (EC2 + SQS + CloudWatch)

Versão resumida: provisiona 3 EC2 t3.medium via Terraform, publica jobs em SQS real, workers consomem em paralelo e emitem métricas no CloudWatch. Para deploy completo passo a passo, ver **Tutorial AWS Academy** logo abaixo.

Comandos básicos (assumindo lab Academy ativo e credenciais exportadas):

```bash
cd infra/terraform
terraform init
terraform apply -var "worker_count=3"
# Aguardar ~5 min do bootstrap das EC2

# Voltar para a raiz, limpar ENV de LocalStack e publicar jobs
cd ../..
python infra/producer.py

# Acompanhar via CloudWatch
python infra/metrics_viewer.py --window 10

# Limpar
cd infra/terraform
terraform destroy
```

Tempo medido (Sessão de validação): **~24 min agregados** para 4288 chunks em 3 workers t3.medium CPU.

---

## Ferramentas de medição e inspeção

Além dos 4 modos de ingestão acima (que executam o pipeline em diferentes topologias), o projeto inclui 3 ferramentas auxiliares para gerar dados para o relatório, consultar métricas e debugar falhas.

### `benchmarks/medir_tokens.py` — medição determinística por PDF

Roda o pipeline localmente em sequencial, mas com captura detalhada por PDF: número de chunks inseridos, tokens consumidos pelo embedding (via `prompt_eval_count` da API Ollama) e duração de processamento. Útil para gerar a tabela de dados reais que aparece nas Seções 5.2, 5.3 e 5.4 do documento técnico.

Diferente do Modo 1 (`dados/pipeline.py`), este script é otimizado para reportar números, não para ser a pipeline oficial. Ignora as etapas intermediárias salvas em disco e vai direto chunk-por-chunk.

Pré-requisito: Ollama rodando localmente com `nomic-embed-text` baixado.

```bash
python benchmarks/medir_tokens.py
```

Saída esperada:

```
PDF                                                            chunks     tokens   duracao
-------------------------------------------------------------------------------------------
fia_2026_..._section_a_general_provisions_..._.pdf                642      56445     11.1s
fia_2026_..._section_b_sporting_..._.pdf                          777      60517      9.6s
fia_2026_..._section_c_technical_..._.pdf                        1731     144614     24.9s
fia_2026_..._section_d_financial_-_f1_teams_..._.pdf              443      33055      7.6s
fia_2026_..._section_e_financial_-_pu_manufacturers_..._.pdf      459      32946      7.0s
fia_2026_..._section_f_operational_..._.pdf                       236      17167      3.1s
-------------------------------------------------------------------------------------------
TOTAL                                                            4288     344744     63.3s
```

### `infra/metrics_viewer.py` — consulta agregada de métricas

Lê as métricas emitidas no CloudWatch (real ou LocalStack) e imprime sum/min/avg/max por métrica numa janela de tempo. Usado para inspecionar a saúde do sistema após uma execução distribuída.

```bash
# Janela padrão de 5 minutos
python infra/metrics_viewer.py

# Janela customizada de 30 minutos
python infra/metrics_viewer.py --window 30

# Agrupar por WorkerId (mostra contribuição de cada worker)
python infra/metrics_viewer.py --by-worker

# Filtrar uma métrica específica
python infra/metrics_viewer.py --metric chunks_inserted
```

Em dev local, requer `AWS_ENDPOINT_URL=http://localhost:4566` apontando para LocalStack. Em produção, deixe a variável vazia para usar o CloudWatch real.

### `infra/dlq_inspector.py` — debug post-mortem da DLQ

Lista as mensagens que caíram na Dead Letter Queue (após 3 tentativas falhas). Mostra payload e contagem de receives. Útil quando um worker está falhando consistentemente para entender o que está em loop.

```bash
python infra/dlq_inspector.py
```

Saída esperada se DLQ vazia: `Nenhuma mensagem na DLQ.`

Em caso de falhas, mostra para cada mensagem: PDF que estava sendo processado, número de tentativas, timestamp do primeiro receive.

---

## Tutorial AWS Academy passo a passo

Esta seção descreve, do zero, como subir o projeto na AWS real usando o AWS Academy Learner Lab. Foi escrita após duas sessões de validação onde encontramos várias armadilhas, e está organizada para que qualquer pessoa consiga reproduzir sem precisar entender Terraform ou AWS profundamente.

**Tempo total estimado:** 45 minutos (10 min de setup, 5 min de provisionamento, 25 min de execução e validação, 5 min de destruição).

### Etapa 1. Pré-requisitos locais (uma vez por máquina)

Você precisa de três ferramentas instaladas: AWS CLI, Terraform e uma chave SSH. Se já tem, pule para a Etapa 2.

**1.1 Instalar AWS CLI (Windows via winget):**

```powershell
winget install Amazon.AWSCLI
```

No macOS: `brew install awscli`. No Linux: `sudo apt install awscli` ou via pip.

**1.2 Instalar Terraform (Windows via winget):**

```powershell
winget install Hashicorp.Terraform
```

No macOS: `brew install terraform`. No Linux: ver instruções oficiais HashiCorp.

**1.3 Validar PATH (Windows):**

O winget às vezes instala os binários sem adicionar ao PATH global. Em cada nova janela do PowerShell, adicione manualmente:

```powershell
$env:PATH += ";C:\Program Files\Amazon\AWSCLIV2;$env:USERPROFILE\AppData\Local\Microsoft\WinGet\Packages\Hashicorp.Terraform_Microsoft.Winget.Source_8wekyb3d8bbwe"
```

Para tornar permanente, adicione esses caminhos via **Sistema → Variáveis de Ambiente** no Windows.

**1.4 Gerar par de chaves SSH (se ainda não tiver):**

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.ssh" | Out-Null
ssh-keygen -t ed25519 -C "harness-rag" -f "$env:USERPROFILE\.ssh\id_ed25519" -N '""'
```

Isso cria `~/.ssh/id_ed25519` (chave privada) e `~/.ssh/id_ed25519.pub` (chave pública). O Terraform vai registrar a chave pública na AWS automaticamente.

### Etapa 2. Iniciar o lab AWS Academy

**2.1** Faça login no AWS Academy: https://awsacademy.instructure.com/

**2.2** Vá em **Courses → AWS Academy Learner Lab → Modules → Learner Lab**.

**2.3** Clique no botão **Start Lab**. Aguarde o indicador no topo da página mudar de vermelho (parando) para amarelo (iniciando) para verde (pronto). Isso leva ~3 minutos.

**2.4** Clique em **AWS Details** no topo da página. Vai abrir um painel com:
- AWS CLI: bloco contendo as credenciais
- SSH key: chave do ambiente (não precisamos, usamos a nossa)

Clique em **Show** ao lado de **AWS CLI**. Vai aparecer algo como:

```
[default]
aws_access_key_id=ASIA...
aws_secret_access_key=...
aws_session_token=...
```

**2.5** Copie esse bloco inteiro. Vamos usar na próxima etapa.

**Aviso importante:** as credenciais expiram após algumas horas, mesmo com o lab rodando. Se receber erro `InvalidClientTokenId`, volte aqui e re-copie.

### Etapa 3. Configurar credenciais no terminal

Abra um PowerShell e cole as credenciais como variáveis de ambiente:

```powershell
$env:AWS_ACCESS_KEY_ID="ASIA..."
$env:AWS_SECRET_ACCESS_KEY="..."
$env:AWS_SESSION_TOKEN="..."
$env:AWS_DEFAULT_REGION="us-east-1"
```

(Substitua os valores pelos copiados da Etapa 2.5.)

Valide que funcionou:

```powershell
aws sts get-caller-identity
```

Deve retornar um JSON com seu `Account`, `UserId` e `Arn`. Se retornar `InvalidClientTokenId`, as credenciais estão erradas ou expiradas.

### Etapa 4. Provisionar a infraestrutura

**4.1** Navegue para a pasta do projeto e depois para a pasta do Terraform:

```powershell
cd C:\Users\heito\Documents\ProjetoHarness\harness-rag\infra\terraform
```

**4.2** Inicialize o Terraform (baixa o provider AWS, só precisa rodar uma vez por máquina):

```powershell
terraform init
```

Saída esperada: `Terraform has been successfully initialized!`

**4.3** Aplique a configuração:

```powershell
terraform apply -var "worker_count=3"
```

O Terraform vai mostrar um plano com **10 recursos a criar** (3 EC2, 2 SQS, Security Group, Key Pair, etc) e pedir confirmação. Digite `yes` e pressione Enter.

A criação leva ~30 segundos para as filas SQS e ~1 minuto para subir as EC2.

**4.4** Quando terminar, o Terraform vai imprimir os outputs:

```
worker_public_ips = [
  "44.213.103.163",
  "35.153.126.58",
  "34.239.93.33",
]
```

Anote esses IPs, você vai usar na próxima etapa.

**Atenção:** as EC2 acabaram de ser criadas mas o aplicativo ainda não está rodando. O script `user_data.sh` está executando em background, instalando Docker, Ollama e o worker. Isso leva **~5 minutos**.

### Etapa 5. Aguardar bootstrap e validar

**5.1** Espere 5 minutos. Para verificar se o bootstrap terminou em uma das EC2:

```powershell
ssh -i $env:USERPROFILE\.ssh\id_ed25519 -o StrictHostKeyChecking=no ubuntu@<IP_DA_WORKER> "tail -3 /var/log/cloud-init-output.log"
```

Se aparecer a linha **`Bootstrap concluido. Worker rodando.`**, está pronto. Caso contrário, espere mais um minuto e tente de novo.

**5.2** Para acompanhar o bootstrap em tempo real (opcional, útil em desenvolvimento):

```powershell
ssh -i $env:USERPROFILE\.ssh\id_ed25519 ubuntu@<IP_DA_WORKER> "sudo tail -f /var/log/cloud-init-output.log"
```

Use Ctrl+C para sair do tail.

**5.3** Para confirmar que o worker está conectado à fila SQS:

```powershell
ssh -i $env:USERPROFILE\.ssh\id_ed25519 ubuntu@<IP_DA_WORKER> "sudo docker logs harness-worker 2>&1 | grep queue_resolved | tail -1"
```

Deve mostrar uma linha como `queue_resolved queue_url=https://sqs.us-east-1.amazonaws.com/...`. Se aparecer, o worker está esperando mensagens.

### Etapa 6. Publicar jobs e processar

**6.1** Abra um novo PowerShell na raiz do projeto (não esqueça de re-exportar as credenciais AWS na nova janela):

```powershell
cd C:\Users\heito\Documents\ProjetoHarness\harness-rag

$env:AWS_ACCESS_KEY_ID="ASIA..."
$env:AWS_SECRET_ACCESS_KEY="..."
$env:AWS_SESSION_TOKEN="..."
$env:AWS_DEFAULT_REGION="us-east-1"
```

**6.2** Limpe a variável `AWS_ENDPOINT_URL` se ela existir (ela é usada para LocalStack, e o producer precisa apontar para AWS real):

```powershell
Remove-Item Env:AWS_ENDPOINT_URL -ErrorAction SilentlyContinue
```

**6.3** Publique os 6 jobs (1 por PDF do corpus FIA):

```powershell
python infra/producer.py
```

Saída esperada: `6 mensagens publicadas em 'ingestion-jobs'`.

**6.4** Para acompanhar o processamento ao vivo, abra mais janelas SSH (uma por worker):

```powershell
ssh -i $env:USERPROFILE\.ssh\id_ed25519 ubuntu@<IP_WORKER_1> "sudo docker logs -f harness-worker --tail 0"
```

Cada PDF leva de 3 a 6 minutos. Com 3 workers em paralelo, o processamento completo deve terminar em ~10 minutos.

**6.5** Quando os logs ficarem quietos (sem novos `message_done`), todos os PDFs foram processados. Verifique as métricas agregadas:

```powershell
python infra/metrics_viewer.py --window 30
```

Deve mostrar:
- `pdf_processed_success`: 6
- `chunks_inserted`: total na faixa de 3000 a 5000
- `embedding_tokens_consumed`: total na faixa de 300 mil
- `pdf_processing_duration_ms`: média na ordem de 200 mil (3-4 min por PDF)

### Etapa 7. Destruir a infraestrutura

**Importante:** sempre destrua os recursos após uso para não consumir crédito desnecessariamente.

```powershell
cd C:\Users\heito\Documents\ProjetoHarness\harness-rag\infra\terraform
terraform destroy
```

Digite `yes` quando pedir confirmação. Em ~1 minuto tudo é removido (EC2, SQS, etc).

**7.2** No AWS Academy, clique em **End Lab** no topo da página. Isso encerra o relógio do lab e libera o crédito não consumido.

### Troubleshooting

**Erro `InvalidClientTokenId` ao rodar `aws sts get-caller-identity`:**
As credenciais expiraram. Volte na Etapa 2, copie credenciais novas e re-exporte na Etapa 3.

**Erro `aws: command not found` ou `terraform: command not found`:**
PATH não está configurado nessa janela. Re-execute o comando da Etapa 1.3.

**Bootstrap das EC2 nunca termina (aguardando mais de 10 minutos):**
SSH na EC2 e verifique o que está rodando: `ssh ... "ps aux | grep -E 'apt|ollama|docker'"`. Se nada estiver rodando, veja o log de erro: `ssh ... "sudo tail -50 /var/log/cloud-init-output.log"`.

**Worker conecta no LocalStack em vez de AWS real:**
Variável `AWS_ENDPOINT_URL` está setada quando deveria estar vazia. No worker, isso é controlado pelo `docker run` do user_data.sh (deve estar correto). No producer local, execute `Remove-Item Env:AWS_ENDPOINT_URL` antes do producer.

**`terraform apply` falha com `AccessDenied: iam:CreateRole`:**
O Terraform deste projeto NÃO cria IAM Role (usa o `LabInstanceProfile` pré-criado pelo Academy). Se está vendo esse erro, você pode estar usando uma versão antiga do código. Atualize via `git pull`.

**Mensagens "duplicadas" na fila (mais de 6 visíveis):**
Comportamento esperado do SQS. Visibility timeout é 10 min. Se uma mensagem demora mais que isso para ser processada, ela volta a ficar visível e outro worker pega. Isso causa reprocessamento; o sistema é idempotente (ChromaDB faz upsert) então não é problema funcional.

**EC2 nunca aparece como Running no console AWS:**
Sua conta pode ter atingido quota de instâncias. Verifique: `aws ec2 describe-account-attributes --attribute-names supported-platforms`. Em AWS Academy, quota costuma ser limitada a 4 instâncias `t3.medium` simultâneas.

**Custo do lab disparou:**
Verifique no console AWS Academy quanto crédito você gastou (campo "Used"). 3 EC2 `t3.medium` por 1 hora custam aproximadamente $0.15. Se gastou mais que isso, provavelmente esqueceu de destruir uma execução anterior. Vá no console EC2 e termine instâncias órfãs manualmente.

### Arquivos importantes para entender o que acontece

| Arquivo | Função |
|---|---|
| `infra/terraform/main.tf` | Define os recursos AWS criados |
| `infra/terraform/variables.tf` | Parâmetros configuráveis (worker_count, region, etc) |
| `infra/terraform/user_data.sh` | Script que roda no primeiro boot de cada EC2 (instala Docker + Ollama + worker) |
| `infra/producer.py` | Publica jobs no SQS |
| `infra/worker.py` | Consome jobs do SQS e processa PDFs |
| `infra/metrics.py` | Emite métricas no CloudWatch |
| `infra/metrics_viewer.py` | Consulta métricas agregadas via CLI |
| `infra/dlq_inspector.py` | Lista mensagens na Dead Letter Queue (para debug) |

---

## Como rodar a interface

Com Ollama rodando, `.env` configurado e vector store indexado:

```bash
streamlit run app.py
```

A interface sobe em `http://localhost:8501`. Cada query gera um trace JSON em `traces/{session_id}.json`.

Exemplo de uso programático:

```python
from dotenv import load_dotenv
load_dotenv()

from orchestration.orchestrator import run

resultado = run("What is DRS?")
print(resultado["fonte"])         # "corpus" | "web" | "hybrid" | "none"
print(resultado["resposta"])
print(resultado["trace"])
```

---

## Variáveis de ambiente

Todas as envs declaradas em `config.py`. Lista resumida:

### Aplicação (consulta)

| Variável | Default | Descrição |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | endpoint Ollama |
| `LLM_MODEL` | `llama3.1:8b` | modelo de geração |
| `EMBED_MODEL` | `nomic-embed-text` | modelo de embeddings |
| `CHROMA_PERSIST_DIR` | (sem default) | path do vector store; caller decide o fallback |
| `CHROMA_COLLECTION` | `fia_2026_regulations` | nome da collection |
| `RETRIEVER_THRESHOLD` | `0.75` | similaridade mínima antes do fallback web |
| `RETRIEVER_TOP_K` | `5` | top-k retornado pelo retriever |
| `TAVILY_API_KEY` | (sem default) | obrigatória para web search |
| `TAVILY_MAX_RESULTS` | `5` | máximo de resultados Tavily |
| `TRACES_DIR` | `./traces` | pasta dos traces JSON |

### Indexação (chunking)

| Variável | Default | Descrição |
|---|---|---|
| `CHUNK_SIZE` | `512` | tamanho em caracteres de cada chunk |
| `CHUNK_OVERLAP` | `64` | caracteres compartilhados entre chunks adjacentes |
| `INGEST_MAX_WORKERS` | `min(6, cpu_count)` | workers do `pipeline_parallel.py` |

### Distribuído (AWS / SQS)

| Variável | Default | Descrição |
|---|---|---|
| `AWS_ENDPOINT_URL` | `None` (AWS real) | LocalStack ou AWS; em dev local com compose, setar para LocalStack |
| `AWS_DEFAULT_REGION` | `us-east-1` | região AWS |
| `SQS_QUEUE_NAME` | `ingestion-jobs` | nome da fila principal |
| `SQS_DLQ_NAME` | `ingestion-jobs-dlq` | nome da DLQ |
| `SQS_MAX_RECEIVE_COUNT` | `3` | falhas antes de mover pra DLQ |
| `SQS_VISIBILITY_TIMEOUT` | `600` | segundos que mensagem fica invisível após receive |
| `SQS_POLL_WAIT_SECONDS` | `20` | long-polling do worker |
| `WORKER_IDLE_TIMEOUT_SEC` | `0` (infinito) | worker sai após N segundos sem mensagem |
| `CLOUDWATCH_NAMESPACE` | `F1RagHarness` | namespace customizado para as métricas |

---

## Testes

A suite usa **pytest** com **marker `integration`** para separar testes que exigem infraestrutura ao vivo (Ollama, vector store, Tavily API). O `pytest.ini` exclui integração do run padrão via `addopts = -m "not integration"`.

**Inventário atual:** 29 testes ao total, sendo 24 unitários (rodam em qualquer máquina) e 5 de integração (precisam de Ollama e vector store ao vivo).

| Arquivo | Unit | Integration | O que testa |
|---|---|---|---|
| `tests/test_generator.py` | 6 | 0 | Geração de resposta, fallback de fonte, flags `corpus_used`/`web_used` |
| `tests/test_orchestrator.py` | 4 | 0 | Roteamento condicional do grafo LangGraph |
| `tests/test_reformulator.py` | 3 | 1 | Reescrita de query (mockada) e teste real contra Ollama |
| `tests/test_retriever.py` | 5 | 0 | Busca vetorial, threshold, fallback, append de trace |
| `tests/test_retriever_integration.py` | 0 | 3 | Smoke test contra ChromaDB persistente real |
| `tests/test_web_searcher.py` | 6 | 1 | Mocks Tavily + 1 chamada real |

### Pré-requisitos por tipo de teste

| Tipo | Precisa Ollama? | Precisa vector store? | Precisa Tavily? |
|---|---|---|---|
| Unitários (24) | Não | Não | Não |
| Integração reformulator | **Sim** (`llama3.1:8b`) | Não | Não |
| Integração retriever | **Sim** (`nomic-embed-text`) | **Sim** (executar `dados/pipeline.py` antes) | Não |
| Integração web_searcher | Não | Não | **Sim** (`TAVILY_API_KEY` no `.env`) |

### Comandos

**Suite padrão (apenas unitários):**

```bash
pytest -q
```

Saída esperada: `24 passed, 5 deselected`.

**Apenas testes de integração:**

```bash
pytest -q -m integration
```

Antes de rodar, garanta que os pré-requisitos da tabela acima estão atendidos.

**Suite completa (unit + integration):**

```bash
pytest -q -m "integration or not integration"
```

**Por arquivo específico:**

```bash
pytest -q tests/test_generator.py
pytest -q tests/test_retriever.py tests/test_orchestrator.py
```

**Por nome de teste (substring match):**

```bash
pytest -q -k "fallback"
pytest -q -k "trace"
```

**Modo verbose (mostra cada teste individual):**

```bash
pytest -v
```

**Mostra prints/logs durante os testes:**

```bash
pytest -s
```

**Para no primeiro erro:**

```bash
pytest -x
```

**Last failed (rodar só os que falharam na execução anterior):**

```bash
pytest --lf
```

**Smoke test de imports (não usa pytest):**

Validação rápida de que todos os módulos importam sem erro depois de mudanças em `config.py`:

```bash
python -c "
import config
from agents import retriever, generator, reformulator, web_searcher
from infra import worker, producer, metrics, metrics_viewer, dlq_inspector
from orchestration import orchestrator
from dados import ingestion, pipeline_parallel
print('Todos os módulos importam sem erro.')
"
```

### Wrappers de teste e deploy

Para conveniência, o diretório `scripts/` tem dois wrappers shell que encapsulam os comandos mais usados:

```bash
# Testes
scripts/test.sh                # suite padrão (24 unitários)
scripts/test.sh integration    # só integração
scripts/test.sh all            # tudo (29 testes)
scripts/test.sh smoke          # smoke test de imports
scripts/test.sh verbose        # suite padrão em modo verbose

# Deploy AWS
scripts/deploy.sh up           # provisiona com 3 workers (default)
scripts/deploy.sh up 1         # provisiona com 1 worker
scripts/deploy.sh plan         # mostra o plano sem aplicar
scripts/deploy.sh down         # destrói tudo
```

Os wrappers chamam `pytest` e `terraform` por baixo. Use os comandos diretos se precisar controle fino.

### Como adicionar um novo teste

Testes unitários novos não precisam de marker. Vão direto pra suite padrão:

```python
# tests/test_meu_modulo.py
def test_alguma_coisa():
    assert ...
```

Testes que precisam de infraestrutura ao vivo recebem o marker `integration`:

```python
import pytest

@pytest.mark.integration
def test_contra_ollama_real():
    ...
```

---

## Bônus SLM e benchmarks

A pasta `benchmarks/` contém scripts e resultados do estudo do servidor de inferência (Ollama) que sustentam o bônus do critério de avaliação. Quantização dos modelos, tokens por segundo por worker e análise empírica da interação entre paralelismo da aplicação e paralelismo interno do servidor estão documentados em `benchmarks/results.md`.

Os scripts `benchmark.sh` e `benchmark_v2.sh` são feitos pra rodar em EC2 t3.medium provisionada via Terraform. Cobrem três medições: latência de embedding (warm/cold start), tokens por segundo em geração, e ratio de concorrência (1 vs 2 chamadas paralelas).

---

## Solução de problemas

**`ModuleNotFoundError: No module named 'config'`** quando rodar um script: a raiz do projeto não está no `PYTHONPATH`. Os scripts em `dados/scripts/` e `infra/` incluem `sys.path.insert` no topo. Se rodar via Docker, o `Dockerfile` define `PYTHONPATH=/app`.

**Testes de integração travados:** o teste do `test_retriever_integration.py` tem `@pytest.mark.timeout(20)` mas o marker `timeout` requer o plugin `pytest-timeout`. Sem ele, o timeout é ignorado e o teste pode travar se Ollama não responder. Instale com `pip install pytest-timeout` ou apenas evite rodar integração sem Ollama no ar.

**`InvalidCollectionException` em workers EC2:** garantir que a versão do código nas EC2 tem `get_or_create_collection` em `dados/ingestion.py` (fix do commit `48e239a`). Versões antigas com `get_collection` quebram porque cada worker tem seu próprio vector store vazio.
