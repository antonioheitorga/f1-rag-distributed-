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
| Mensageria distribuída | AWS SQS (via LocalStack 3.8 em dev) |
| AWS SDK | boto3 |
| Containerização | Docker + Docker Compose |
| Métricas / EC2 / IaC | AWS CloudWatch / EC2 / Terraform (planejado) |
| Testes | pytest |

---

## Estrutura do projeto

```
harness-rag/
├── agents/
│   ├── reformulator.py     # reescreve a query
│   ├── retriever.py        # busca vetorial no ChromaDB
│   ├── web_searcher.py     # fallback via Tavily
│   ├── generator.py        # compõe texto puro (reporta corpus_used/web_used)
│   └── _retry.py           # política de retry compartilhada (tenacity)
├── orchestration/
│   └── orchestrator.py     # grafo LangGraph + _classify_source() pós-grafo
├── prompts/
│   ├── __init__.py         # load_prompt(name) com lru_cache
│   ├── reformulator.md
│   └── generator.md
├── dados/
│   ├── corpus/             # 6 PDFs FIA 2026 F1 Regulations
│   ├── scripts/            # 01_extract.py … 06_verify.py (thin wrappers)
│   ├── ingestion.py        # funções por-PDF + process_single_pdf()
│   ├── pipeline.py         # pipeline sequencial
│   └── pipeline_parallel.py # ProcessPoolExecutor — paralelismo local
├── infra/
│   ├── producer.py         # publica jobs no SQS + cria DLQ
│   ├── worker.py           # consome SQS, chama process_single_pdf
│   └── dlq_inspector.py    # tool de debug post-mortem da DLQ
├── traces/                 # JSONs gerados por execução
├── tests/
├── docs/architecture.md
├── app.py                  # interface Streamlit
├── docker-compose.yml      # ollama + localstack + worker (escalável)
├── Dockerfile              # imagem do worker
└── requirements.txt
```

Diretórios gerados em runtime (`dados/extracted/`, `dados/processed/`, `dados/chunks/`, `dados/vectorstore/`, `traces/`) ficam fora do controle de versão.

📐 Arquitetura detalhada em [docs/architecture.md](docs/architecture.md).

---

## Setup

### Pré-requisitos

- Python 3.11+
- [Ollama](https://ollama.com) instalado e rodando localmente **OU** Docker Desktop
- Docker Desktop (necessário para o fluxo distribuído via SQS)

### 1. Instalar dependências

```bash
python3 -m pip install -r requirements.txt
```

### 2. Configurar variáveis de ambiente

```bash
cp .env.example .env
```

Preencher `TAVILY_API_KEY` para habilitar busca web. Demais variáveis têm defaults sensatos.

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

O projeto oferece **três modos** de construir a base vetorial — escolha conforme o cenário.

### Modo 1 — Sequencial

Mais simples. Roda os 6 passos em série, um PDF por vez.

```bash
cd dados/
python3 pipeline.py
```

Tempo medido: **79.7s** para os 6 PDFs.

### Modo 2 — Paralelo local (ProcessPoolExecutor)

Dispara 6 processos no mesmo computador, cada um processando 1 PDF.

```bash
cd dados/
python3 pipeline_parallel.py
INGEST_MAX_WORKERS=3 python3 pipeline_parallel.py
```

Tempo medido: **51.2s** (speedup 1.56x). Limitado por Ollama serializar embeddings.

### Modo 3 — Distribuído via SQS (Docker + LocalStack)

Workers em containers separados consomem jobs de uma fila SQS. Demonstra arquitetura pronta para escalar em EC2.

```bash
# 1. Subir infra (Ollama + LocalStack)
docker compose up -d ollama localstack

# 2. Publicar 6 jobs e criar collection limpa
docker compose run --rm worker python infra/producer.py

# 3. Subir N workers em paralelo
docker compose up -d --scale worker=3

# 4. Aguardar terminarem (idle_timeout=60s no compose, sai sozinho)
#    Monitorar: docker ps --filter "name=harness-rag-worker"

# 5. Inspecionar DLQ (deve estar vazia se tudo deu certo)
docker compose run --rm worker python infra/dlq_inspector.py
```

Tempo medido: **~60s** com 3 workers. Inclui overhead de SQS e containerização.

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

### Aplicação

| Variável | Default | Descrição |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | endpoint Ollama (usado por langchain) |
| `OLLAMA_HOST` | `http://localhost:11434` | endpoint Ollama (usado pela lib `ollama` nativa) |
| `LLM_MODEL` | `llama3.1:8b` | modelo de geração |
| `EMBED_MODEL` | `nomic-embed-text` | modelo de embeddings |
| `CHROMA_PERSIST_DIR` | `dados/vectorstore` | path do vector store |
| `CHROMA_COLLECTION` | `fia_2026_regulations` | coleção no ChromaDB |
| `RETRIEVER_THRESHOLD` | `0.75` | limiar mínimo de similaridade |
| `RETRIEVER_TOP_K` | `5` | top-k retornado pelo retriever |
| `TAVILY_API_KEY` | — | obrigatória para web search |
| `TAVILY_MAX_RESULTS` | `5` | máximo de resultados Tavily |
| `TRACES_DIR` | `./traces` | pasta dos traces JSON |

### Pipeline paralelo / SQS

| Variável | Default | Descrição |
|---|---|---|
| `INGEST_MAX_WORKERS` | `min(6, cpu_count)` | workers do `pipeline_parallel.py` |
| `AWS_ENDPOINT_URL` | `http://localhost:4566` | LocalStack ou AWS real |
| `AWS_DEFAULT_REGION` | `us-east-1` | região AWS |
| `SQS_QUEUE_NAME` | `ingestion-jobs` | nome da fila principal |
| `SQS_DLQ_NAME` | `ingestion-jobs-dlq` | nome da DLQ |
| `SQS_MAX_RECEIVE_COUNT` | `3` | falhas antes de mover pra DLQ |
| `SQS_VISIBILITY_TIMEOUT` | `600` | segundos que mensagem fica invisível após receive |
| `SQS_POLL_WAIT_SECONDS` | `20` | long-polling do worker |
| `WORKER_IDLE_TIMEOUT_SEC` | `0` (infinito) | worker sai após N segundos sem mensagem (compose usa 60) |

---

## Testes

```bash
# suite completa (sem integração)
pytest -q

# testes específicos
pytest -q tests/test_generator.py tests/test_retriever.py

# integração (exige Ollama + vector store ao vivo)
pytest -q tests/test_retriever_integration.py
```

**Atual:** 24 testes unitários passando, 2 de integração disponíveis sob demanda.
