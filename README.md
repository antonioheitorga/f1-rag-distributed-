# F1 RAG Distributed

Sistema RAG multiagente sobre os regulamentos técnicos e esportivos da FIA para a temporada de Fórmula 1 2026.

**Adaptação** de um projeto base — desenvolvido por Antonio Heitor e Wisley Gabriel — para a disciplina de **Programação Distribuída e Paralela** (Harness Engineering · Tema 5 · CESUPA). A adaptação adiciona paralelismo na indexação, pool de workers distribuídos via SQS e métricas agregadas na AWS sobre a base multiagente original.

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
| Mensageria distribuída | AWS SQS (planejado) |
| Infraestrutura | AWS EC2 / AWS Academy (planejado) |
| Métricas | AWS CloudWatch via boto3 (planejado) |
| Containerização | Docker + Docker Compose (planejado) |
| Testes | pytest |

---

## Estrutura do projeto

```
harness-rag/
├── agents/
│   ├── reformulator.py     # reescreve a query para busca semântica
│   ├── retriever.py        # busca vetorial no ChromaDB
│   ├── web_searcher.py     # fallback via Tavily
│   ├── generator.py        # compõe a resposta final
│   └── _retry.py           # política de retry compartilhada
├── orchestration/
│   └── orchestrator.py     # grafo LangGraph + classificação de fonte
├── prompts/
│   ├── reformulator.md     # system prompt do reformulador
│   └── generator.md        # system prompt do gerador
├── dados/
│   ├── corpus/             # 6 PDFs FIA 2026 F1 Regulations
│   ├── scripts/            # 01_extract.py … 06_verify.py
│   └── pipeline.py         # orquestrador da ingestão
├── infra/                  # producer, worker, IaC (a criar)
├── traces/                 # JSONs gerados por execução
├── tests/
├── docs/architecture.md    # diagrama do fluxo + contratos dos agentes
├── app.py                  # interface Streamlit
├── docker-compose.yml
└── requirements.txt
```

Os diretórios `dados/extracted/`, `dados/processed/`, `dados/chunks/`, `dados/vectorstore/` e `traces/` são gerados em runtime e ficam fora do controle de versão.

📐 Arquitetura detalhada em [docs/architecture.md](docs/architecture.md).

---

## Setup

### Pré-requisitos

- Python 3.11+
- [Ollama](https://ollama.com) instalado e rodando localmente
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (opcional — sobe Ollama via container)

### 1. Instalar dependências

```bash
python3 -m pip install -r requirements.txt
```

### 2. Subir Ollama e baixar modelos

**Opção A — local:**

```bash
ollama pull llama3.1:8b
ollama pull nomic-embed-text
```

**Opção B — Docker Compose:**

```bash
docker compose up -d ollama
docker exec -it harness-rag-ollama ollama pull llama3.1:8b
docker exec -it harness-rag-ollama ollama pull nomic-embed-text
```

### 3. Configurar variáveis de ambiente

```bash
cp .env.example .env
```

Preencher `TAVILY_API_KEY` para habilitar a busca web. Demais variáveis têm defaults sensatos.

### 4. Construir a base vetorial

```bash
cd dados/
python3 pipeline.py
```

A pipeline executa os 6 passos sequencialmente (extract → validate → preprocess → chunk → embed → verify). Para rodar passos específicos:

```bash
python3 pipeline.py --from 5
python3 pipeline.py --only 6
```

---

## Como executar

Com Ollama rodando, `.env` configurado e vector store indexado:

```bash
streamlit run app.py
```

A interface sobe em `http://localhost:8501`. Cada query gera um trace JSON em `traces/{session_id}.json` com query, resposta, fonte e latência por agente.

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

## Variáveis de ambiente relevantes

| Variável | Default | Descrição |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | endpoint do Ollama |
| `LLM_MODEL` | `llama3.1:8b` | modelo de geração |
| `EMBED_MODEL` | `nomic-embed-text` | modelo de embeddings |
| `CHROMA_PERSIST_DIR` | `dados/vectorstore` | path do vector store (necessário customizar em deploy distribuído) |
| `CHROMA_COLLECTION` | `fia_2026_regulations` | nome da coleção no ChromaDB |
| `RETRIEVER_THRESHOLD` | `0.75` | limiar mínimo de similaridade |
| `RETRIEVER_TOP_K` | `5` | top-k retornado pelo retriever |
| `TAVILY_API_KEY` | — | obrigatória para web search |
| `TAVILY_MAX_RESULTS` | `5` | máximo de resultados do Tavily |
| `TRACES_DIR` | `./traces` | pasta onde o trace de cada execução é salvo |

---

## Testes

```bash
# suite completa (sem integração)
pytest -q

# testes específicos
pytest -q tests/test_generator.py tests/test_retriever.py

# integração (exige Ollama + ChromaDB indexados)
pytest -q tests/test_retriever_integration.py
```
