"""Agente Gerador.

Monta a resposta final usando contexto do corpus (Retriever)
e/ou contexto da web (Web Searcher), com aviso de baixa confiança
quando necessário.
"""

import os
import time
from datetime import datetime, timezone

from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama

from agents._retry import external_call_retry
from prompts import load_prompt


@external_call_retry
def _invoke_llm(chain, params: dict):
    """Invoca a chain LLM com retry — isolado para não re-executar
    montagem de contextos ou append de trace em falhas transientes."""
    return chain.invoke(params)


def _build_contexts(state: dict) -> tuple[str, str, str, str, bool, str]:
    query_original = (state.get("query_original") or "").strip()
    query_reformulada = (state.get("query_reformulada") or query_original).strip()
    if not query_reformulada:
        raise ValueError("State inválido: informe 'query_reformulada' ou 'query_original'.")
    if not query_original:
        # fallback raro: caller passou só query_reformulada, sem original
        query_original = query_reformulada

    retriever_result = state.get("retriever_result") or {}
    web_result = state.get("web_result") or {}

    hits = retriever_result.get("hits", [])
    corpus_context = "\n\n".join([h.get("content", "") for h in hits if h.get("content")]).strip()

    web_items = web_result.get("resultados", [])
    web_context = "\n\n".join(
        [
            f"Título: {item.get('titulo', '')}\nTrecho: {item.get('trecho', '')}\nURL: {item.get('url', '')}"
            for item in web_items
        ]
    ).strip()

    confidence_warning = retriever_result.get("confidence_warning") or ""
    low_confidence = not corpus_context and not web_context

    return query_original, query_reformulada, corpus_context, web_context, low_confidence, confidence_warning


def generate(state: dict) -> dict:
    """Gera resposta final com contexto do corpus e/ou web.

    Responsabilidade única: compor texto a partir dos contextos disponíveis.
    A classificação da fonte (corpus/web/hybrid/none) é feita pelo
    orquestrador a partir dos flags corpus_used/web_used reportados aqui.

    Lê: query_original/query_reformulada, retriever_result, web_result
    Escreve: resposta, corpus_used, web_used, low_confidence,
             confidence_warning, trace (append)
    """
    inicio = time.time()

    query_original, query_reformulada, corpus_context, web_context, low_confidence, confidence_warning = _build_contexts(state)

    llm = ChatOllama(
        base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        model=os.getenv("LLM_MODEL", "llama3.1:8b"),
        temperature=0.0,
    )

    chain = ChatPromptTemplate.from_template(load_prompt("generator")) | llm
    llm_response = _invoke_llm(
        chain,
        {
            "query_original": query_original,
            "query_reformulada": query_reformulada,
            "corpus_context": corpus_context or "N/A",
            "web_context": web_context or "N/A",
        },
    )
    answer = llm_response.content.strip()

    corpus_used = bool(corpus_context)
    web_used = bool(web_context)
    confidence_notice = confidence_warning if low_confidence else None

    return {
        "resposta": answer,
        "corpus_used": corpus_used,
        "web_used": web_used,
        "low_confidence": low_confidence,
        "confidence_warning": confidence_notice,
        "trace": state.get("trace", [])
        + [
            {
                "agente": "generator",
                "entrada": query_original,
                "saida": f"resposta gerada com corpus_used={corpus_used}, web_used={web_used}, low_confidence={low_confidence}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "latencia_ms": int((time.time() - inicio) * 1000),
            }
        ],
    }
