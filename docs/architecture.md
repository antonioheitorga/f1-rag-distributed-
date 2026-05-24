# Arquitetura — F1 RAG System

Sistema multiagente de IA para responder perguntas sobre Fórmula 1.
Combina busca vetorial em corpus próprio (RAG) com fallback para web via Tavily.

---

## Fluxo do sistema

```mermaid
flowchart TD
    U(["Usuário"]) -->|query_original| REFORM

    REFORM["Reformulador\nllama3.1:8b · temp=0.0"]
    REFORM -->|query_reformulada| RET

    RET["Retriever\nChromaDB · nomic-embed-text"]
    RET --> COND{fallback?}

    COND -- "false · fonte = corpus" --> GEN
    COND -- true --> WS

    WS["Web Searcher\nTavily API"]
    WS --> COND2{encontrou?}

    COND2 -- "true · fonte = web" --> GEN
    COND2 -- "false · low_confidence = True" --> GEN

    GEN["Gerador\nllama3.1:8b"]
    GEN -->|resposta| UI(["Streamlit"])

    style REFORM fill:#dbeafe,stroke:#3b82f6
    style RET    fill:#dcfce7,stroke:#22c55e
    style WS     fill:#fef9c3,stroke:#eab308
    style GEN    fill:#fce7f3,stroke:#ec4899
```

---

## Por que esse fluxo?

| Decisão | Motivo |
|---|---|
| Reformulador roda sempre | Garante que o Retriever recebe query em inglês formal, vocabulário do corpus |
| Retriever decide o `fallback` | Ele é o dono do contexto de busca — encapsula a lógica de relevância |
| Orquestrador sem LLM | Transições são lógica determinística — reduz latência e facilita debugging |
| Terceiro caminho `low_confidence` | Usuário é avisado quando a resposta é incerta, em vez de resposta silenciosamente errada |

---

## GraphState — estado compartilhado entre os agentes

| Campo | Tipo | Escrito por | Lido por |
|---|---|---|---|
| `query_original` | `str` | Orquestrador (START) | Reformulador, Gerador |
| `session_id` | `str` | Orquestrador (START) | Todos (trace) |
| `query_reformulada` | `str` | Reformulador | Retriever, Web Searcher |
| `retriever_result` | `dict` | Retriever | Orquestrador, Gerador |
| `web_result` | `dict\|None` | Web Searcher | Gerador |
| `corpus_used` | `bool` | Gerador | Orquestrador (classifica `fonte`) |
| `web_used` | `bool` | Gerador | Orquestrador (classifica `fonte`) |
| `fonte` | `str` | Orquestrador (pós-grafo) | Streamlit, export JSON |
| `low_confidence` | `bool` | Gerador | Streamlit |
| `confidence_warning` | `str\|None` | Retriever ou Gerador | Streamlit |
| `resposta` | `str` | Gerador | Orquestrador (END), Streamlit |
| `trace` | `list[dict]` | Todos (append) | Streamlit, export JSON |

### `retriever_result` — shape completo

```python
{
    "query":              str,       # query que foi buscada
    "threshold":          float,     # valor do threshold usado
    "top_k":              int,       # número máximo de resultados pedidos
    "total_hits":         int,       # quantos chunks passaram o threshold
    "best_score":         float,     # score do chunk mais relevante (0.0 se nenhum)
    "fallback_to_web":    bool,      # True se nenhum chunk passou o threshold
    "confidence_warning": str|None,  # aviso quando baixa confiança
    "hits": [
        {
            "content":  str,   # texto do chunk
            "score":    float, # similaridade coseno (0.0 a 1.0)
            "metadata": dict,  # source_file, section, chunk_id, char_count
        }
    ]
}
```

### `web_result` — shape completo

```python
{
    "resultados": [
        {
            "titulo": str,
            "trecho": str,
            "url":    str,
        }
    ],
    "encontrou": bool,
}
```

### `trace` — cada agente appenda

```python
{
    "agente":      str,        # "reformulator" | "retriever" | "web_searcher" | "generator"
    "entrada":     str | dict,
    "saida":       str | dict,
    "timestamp":   str,        # ISO 8601
    "latencia_ms": int,
}
```

---

## Contratos dos agentes

| Agente | Arquivo | Usa LLM | Lê do state | Escreve no state |
|---|---|---|---|---|
| **Reformulador** | `agents/reformulator.py` | ✅ llama3.1:8b | `query_original` | `query_reformulada`, `trace` |
| **Retriever** | `agents/retriever.py` | ❌ | `query_reformulada` | `retriever_result`, `trace` |
| **Web Searcher** | `agents/web_searcher.py` | ❌ | `query_reformulada` | `web_result`, `trace` |
| **Gerador** | `agents/generator.py` | ✅ llama3.1:8b | `query_original/query_reformulada`, `retriever_result`, `web_result` | `resposta`, `corpus_used`, `web_used`, `low_confidence`, `confidence_warning`, `trace` |
| **Orquestrador** | `orchestration/orchestrator.py` | ❌ | `retriever_result` (roteamento), `corpus_used`/`web_used` (classificação) | `session_id`, `trace` (init), `fonte` (pós-grafo) |

---

## Stack tecnológico

| Camada | Tecnologia | Onde é usado |
|---|---|---|
| Linguagem | Python 3.11+ | Todo o projeto |
| Orquestração | LangGraph | `orchestration/orchestrator.py` |
| LLM | Ollama · `llama3.1:8b` | Reformulador, Gerador |
| Embeddings | Ollama · `nomic-embed-text` | Retriever |
| Vector store | ChromaDB | Retriever |
| Busca web | Tavily API | Web Searcher |
| Interface | Streamlit | `app.py` |
| Infraestrutura | Docker Compose | Serviço `ollama` |
| Testes | pytest | `tests/` |

---

## Variáveis de ambiente

| Variável | Default | Descrição |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Endereço do servidor Ollama |
| `LLM_MODEL` | `llama3.1:8b` | Modelo LLM para Reformulador e Gerador |
| `EMBEDDING_MODEL` | `nomic-embed-text` | Modelo de embeddings para o Retriever |
| `CHROMA_PERSIST_DIR` | `./dados/vectorstore` | Caminho do vector store persistente |
| `CHROMA_COLLECTION` | `fia_2026_regulations` | Nome da coleção no ChromaDB |
| `RETRIEVER_THRESHOLD` | `0.75` | Similaridade mínima para usar um chunk |
| `RETRIEVER_TOP_K` | `5` | Número máximo de chunks retornados |
| `TAVILY_API_KEY` | — | Chave da API Tavily (obrigatória para web search) |
| `TRACES_DIR` | `./traces` | Diretório para export de traces JSON |
