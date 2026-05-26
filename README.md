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

Mesmo código do Modo 3 mas rodando em EC2 reais provisionadas via Terraform. Workers ficam em hosts independentes, cada um com seu Ollama dedicado, eliminando a contenção do Modo 2.

```bash
# 1. Iniciar lab AWS Academy e exportar credenciais no PowerShell
$env:AWS_ACCESS_KEY_ID="..."
$env:AWS_SECRET_ACCESS_KEY="..."
$env:AWS_SESSION_TOKEN="..."
$env:AWS_DEFAULT_REGION="us-east-1"

# 2. Provisionar 3 EC2 t3.medium + SQS + DLQ
cd infra/terraform
terraform init
terraform apply -var "worker_count=3"

# 3. Aguardar ~5 min do user_data.sh bootstrapar Docker, Ollama e worker
ssh -i ~/.ssh/id_ed25519 ubuntu@<worker_ip> "tail -f /var/log/cloud-init-output.log"

# 4. Publicar 6 jobs na SQS real (executar localmente)
Remove-Item Env:AWS_ENDPOINT_URL -ErrorAction SilentlyContinue
python infra/producer.py

# 5. Acompanhar processamento via metrics_viewer
python infra/metrics_viewer.py --window 10

# 6. Destruir tudo após validar
terraform destroy
```

Manual completo de operação Terraform em `infra/terraform/README.md`.

Tempo medido (Sessão de validação): **~24 min agregados** para 3127 chunks em 3 workers t3.medium CPU.

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
