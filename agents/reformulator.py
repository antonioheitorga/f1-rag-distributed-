"""Agente Reformulador.

Reescreve a query original do usuário para otimizar a busca semântica
no corpus de regulamentos da FIA F1 2026.
"""

import time
from datetime import datetime, timezone

from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama

from agents._retry import external_call_retry
from config import LLM_MODEL, OLLAMA_BASE_URL
from prompts import load_prompt


@external_call_retry
def _invoke_llm(chain, params: dict):
    """Invoca a chain LLM com retry — isolado para não re-executar
    montagem de prompt ou append de trace em falhas transientes."""
    return chain.invoke(params)


def reformulate(state: dict) -> dict:
    """Reformula a query original para busca semântica.

    Lê: state["query_original"]
    Escreve: query_reformulada, trace (append)
    """
    inicio = time.time()
    query_original = state["query_original"]

    llm = ChatOllama(
        base_url=OLLAMA_BASE_URL,
        model=LLM_MODEL,
        temperature=0.0,
    )
    chain = ChatPromptTemplate.from_template(load_prompt("reformulator")) | llm
    resposta = _invoke_llm(chain, {"query": query_original})
    query_reformulada = resposta.content.strip().strip('"\'').strip()

    return {
        "query_reformulada": query_reformulada,
        "trace": state.get("trace", []) + [{
            "agente": "reformulator",
            "entrada": query_original,
            "saida": query_reformulada,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "latencia_ms": int((time.time() - inicio) * 1000),
        }],
    }
