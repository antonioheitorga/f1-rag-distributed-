"""Configuração central do projeto f1-rag-distributed.

Toda constante e variável de ambiente do sistema é declarada aqui.
Cada módulo importa o que precisa em vez de redefinir defaults locais.

Benefícios:
1. Evita divergência entre defaults espalhados em vários arquivos.
2. Centraliza documentação: leitor abre um arquivo e entende tudo que é
   configurável.
3. Facilita override via env var: o .env.example reflete exatamente este
   arquivo, sem campos faltando ou divergentes.

Convenção: defaults aqui são os defaults de produção para o cenário Harness
(workers AWS reais). Dev local com LocalStack passa env vars explícitas via
docker-compose.
"""

import os


# ----------------------------------------------------------------------------
# Modelos (servidos via Ollama local)
# ----------------------------------------------------------------------------
# LLM_MODEL: modelo de geração usado pelo agente Generator.
# Llama 3.1 8B com quantização Q4_K_M (default do Ollama).
LLM_MODEL = os.getenv("LLM_MODEL", "llama3.1:8b")

# EMBED_MODEL: modelo de embedding usado pelo Retriever (queries) e pelo
# worker de ingestão (chunks do corpus). nomic-embed-text em F16.
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")

# OLLAMA_BASE_URL: endpoint HTTP do servidor Ollama local.
# Em dev local, localhost. Em worker EC2 com --network=host, também localhost.
# Em docker-compose, sobrescrito para http://harness-rag-ollama:11434.
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")


# ----------------------------------------------------------------------------
# Chunking (particionamento do texto extraído dos PDFs)
# ----------------------------------------------------------------------------
# CHUNK_SIZE: tamanho de cada chunk em caracteres.
# 512 é compatível com a janela de contexto do nomic-embed-text (2048 tokens)
# com folga para metadados.
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "512"))

# CHUNK_OVERLAP: caracteres compartilhados entre chunks adjacentes.
# 64 caracteres (12.5%) reduz perda de contexto em fronteiras.
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "64"))


# ----------------------------------------------------------------------------
# ChromaDB (vector store)
# ----------------------------------------------------------------------------
# CHROMA_COLLECTION: nome da collection que armazena os embeddings do corpus.
CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION", "fia_2026_regulations")

# CHROMA_PERSIST_DIR: diretório local do ChromaDB persistido.
# Sem default global: cada caller (pipeline local, worker distribuído) decide
# o path apropriado ao seu contexto. None significa "não setado pelo ambiente".
CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR")


# ----------------------------------------------------------------------------
# Retriever (busca vetorial + decisão de fallback)
# ----------------------------------------------------------------------------
# RETRIEVER_THRESHOLD: limiar de similaridade para acionar busca web.
# Se o melhor score < threshold, o orquestrador chama o Web Searcher.
RETRIEVER_THRESHOLD = float(os.getenv("RETRIEVER_THRESHOLD", "0.75"))

# RETRIEVER_TOP_K: número de chunks retornados pela busca vetorial.
RETRIEVER_TOP_K = int(os.getenv("RETRIEVER_TOP_K", "5"))


# ----------------------------------------------------------------------------
# Tavily (busca web externa)
# ----------------------------------------------------------------------------
# TAVILY_API_KEY: chave da API Tavily. Sem default por segurança.
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

# TAVILY_MAX_RESULTS: número máximo de resultados retornados por busca.
TAVILY_MAX_RESULTS = int(os.getenv("TAVILY_MAX_RESULTS", "5"))


# ----------------------------------------------------------------------------
# AWS (SQS, CloudWatch)
# ----------------------------------------------------------------------------
# AWS_ENDPOINT_URL: endpoint customizado.
# None significa "use endpoint real da AWS". Dev com LocalStack seta
# explicitamente via env (http://localhost:4566 ou http://harness-rag-localstack:4566).
AWS_ENDPOINT_URL = os.getenv("AWS_ENDPOINT_URL") or None

AWS_DEFAULT_REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")

# SQS_QUEUE_NAME: fila principal de jobs de indexação.
SQS_QUEUE_NAME = os.getenv("SQS_QUEUE_NAME", "ingestion-jobs")

# SQS_DLQ_NAME: Dead Letter Queue derivada da fila principal por convenção.
SQS_DLQ_NAME = os.getenv("SQS_DLQ_NAME", f"{SQS_QUEUE_NAME}-dlq")

# SQS_MAX_RECEIVE_COUNT: tentativas antes de rotear mensagem para DLQ.
SQS_MAX_RECEIVE_COUNT = int(os.getenv("SQS_MAX_RECEIVE_COUNT", "3"))

# SQS_VISIBILITY_TIMEOUT: segundos que uma mensagem fica invisível após
# receive. Worker tem este tempo para chamar DeleteMessage antes da
# mensagem voltar à fila.
SQS_VISIBILITY_TIMEOUT = int(os.getenv("SQS_VISIBILITY_TIMEOUT", "600"))

# SQS_POLL_WAIT_SECONDS: long polling. Worker aguarda até este tempo
# por mensagens antes de retornar lista vazia.
SQS_POLL_WAIT_SECONDS = int(os.getenv("SQS_POLL_WAIT_SECONDS", "20"))


# ----------------------------------------------------------------------------
# Worker (comportamento do consumer SQS)
# ----------------------------------------------------------------------------
# WORKER_IDLE_TIMEOUT_SEC: segundos sem mensagens antes do worker encerrar.
# 0 significa "nunca encerrar" (modo produção).
# Valor positivo é útil em dev/demo para o container parar sozinho.
WORKER_IDLE_TIMEOUT_SEC = int(os.getenv("WORKER_IDLE_TIMEOUT_SEC", "0"))


# ----------------------------------------------------------------------------
# CloudWatch (métricas)
# ----------------------------------------------------------------------------
# CLOUDWATCH_NAMESPACE: namespace customizado para as métricas do projeto.
CLOUDWATCH_NAMESPACE = os.getenv("CLOUDWATCH_NAMESPACE", "F1RagHarness")


# ----------------------------------------------------------------------------
# Paths gerais
# ----------------------------------------------------------------------------
# TRACES_DIR: onde os traces JSON de cada execução do orquestrador são salvos.
TRACES_DIR = os.getenv("TRACES_DIR", "./traces")


# ----------------------------------------------------------------------------
# Telemetria de bibliotecas externas
# ----------------------------------------------------------------------------
# SILENCE_CHROMA_TELEMETRY: silencia avisos repetidos do tipo
# "Failed to send telemetry event ClientStartEvent: capture() takes
# 1 positional argument but 3 were given". O problema vem de incompatibilidade
# entre a versão atual do ChromaDB e a versão de PostHog instalada como
# dependência transitiva. Setting(anonymized_telemetry=False) e a env var
# ANONYMIZED_TELEMETRY não silenciam na versão 0.5.20; a única forma estável
# é elevar o nível do logger específico do ChromaDB para CRITICAL.
# Default "True" para deixar o output limpo. Defina como "False" se quiser
# ver as mensagens (útil para diagnosticar problemas reais de telemetria).
SILENCE_CHROMA_TELEMETRY = os.getenv("SILENCE_CHROMA_TELEMETRY", "True").lower() == "true"
if SILENCE_CHROMA_TELEMETRY:
    import logging as _logging
    _logging.getLogger("chromadb.telemetry.product.posthog").setLevel(_logging.CRITICAL)
