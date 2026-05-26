#!/bin/bash
#
# test.sh - roda a suite de testes do projeto.
#
# Uso:
#   scripts/test.sh                # suite padrao (24 testes unitarios)
#   scripts/test.sh integration    # so testes de integracao (precisam Ollama ao vivo)
#   scripts/test.sh all            # tudo (24 unit + 5 integration)
#   scripts/test.sh smoke          # smoke test de imports (rapido)
#   scripts/test.sh verbose        # suite padrao em modo verbose
#
# Sai com codigo 0 se todos os testes passarem, 1 caso contrario.
#
# Este script e um wrapper sobre os comandos pytest documentados no README.md.
# Use os comandos pytest diretos se precisar controle fino (ex: -k, -x, --lf).

set -euo pipefail

MODE="${1:-default}"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

cd "$PROJECT_ROOT"

case "$MODE" in
    default)
        echo ">>> Rodando suite padrao (apenas testes unitarios)..."
        python -m pytest -q
        ;;
    integration)
        echo ">>> Rodando apenas testes de integracao..."
        echo ">>> Pre-requisitos: Ollama rodando com modelos llama3.1:8b e"
        echo ">>> nomic-embed-text, vector store pre-construido em dados/vectorstore/,"
        echo ">>> e TAVILY_API_KEY no .env."
        python -m pytest -q -m integration
        ;;
    all)
        echo ">>> Rodando suite completa (unit + integration)..."
        python -m pytest -q -m "integration or not integration"
        ;;
    smoke)
        echo ">>> Smoke test de imports (valida que config.py refator esta consistente)..."
        python -c "
import config
from agents import retriever, generator, reformulator, web_searcher
from infra import worker, producer, metrics, metrics_viewer, dlq_inspector
from orchestration import orchestrator
from dados import ingestion, pipeline_parallel
print('OK: todos os modulos importam sem erro.')
print(f'   LLM_MODEL={config.LLM_MODEL}')
print(f'   EMBED_MODEL={config.EMBED_MODEL}')
print(f'   RETRIEVER_THRESHOLD={config.RETRIEVER_THRESHOLD}')
print(f'   SQS_QUEUE_NAME={config.SQS_QUEUE_NAME}')
"
        ;;
    verbose)
        echo ">>> Suite padrao em modo verbose..."
        python -m pytest -v
        ;;
    *)
        echo "ERRO: modo desconhecido '$MODE'. Use default, integration, all, smoke ou verbose."
        exit 1
        ;;
esac
