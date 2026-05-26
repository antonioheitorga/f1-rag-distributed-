"""Orquestrador LangGraph.

Monta o grafo do sistema RAG multiagente:
reformulator -> retriever -> {web_searcher} -> generator

A transição entre retriever e web_searcher é condicional, baseada
no flag `fallback_to_web` do retriever_result. Lógica determinística,
sem LLM.
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, StateGraph

from agents.generator import generate
from agents.reformulator import reformulate
from agents.retriever import retrieve
from agents.web_searcher import search_web
from config import TRACES_DIR


class GraphState(TypedDict, total=False):
    query_original: str
    session_id: str
    query_reformulada: str
    retriever_result: dict
    web_result: dict
    resposta: str
    corpus_used: bool
    web_used: bool
    fonte: str
    low_confidence: bool
    confidence_warning: str | None
    trace: list[dict]


def _classify_source(corpus_used: bool, web_used: bool) -> str:
    """Classifica a fonte usada na resposta a partir dos flags do Generator.

    Responsabilidade do orquestrador: o Generator reporta apenas o que
    consumiu (corpus_used/web_used); o nome agregado (corpus/web/hybrid/none)
    é metadado de execução do fluxo, não da geração de texto.
    """
    if corpus_used and web_used:
        return "hybrid"
    if corpus_used:
        return "corpus"
    if web_used:
        return "web"
    return "none"


def _route_after_retriever(state: GraphState) -> str:
    """Decide o próximo nó após o retriever.

    Se o melhor score ficou abaixo do threshold (fallback_to_web=True),
    chama o web_searcher. Caso contrário, vai direto pro generator.
    """
    retriever_result = state.get("retriever_result") or {}
    return "web_searcher" if retriever_result.get("fallback_to_web", False) else "generator"


def build_graph():
    """Monta e compila o grafo do sistema."""
    graph = StateGraph(GraphState)

    graph.add_node("reformulator", reformulate)
    graph.add_node("retriever", retrieve)
    graph.add_node("web_searcher", search_web)
    graph.add_node("generator", generate)

    graph.set_entry_point("reformulator")
    graph.add_edge("reformulator", "retriever")
    graph.add_conditional_edges(
        "retriever",
        _route_after_retriever,
        {"web_searcher": "web_searcher", "generator": "generator"},
    )
    graph.add_edge("web_searcher", "generator")
    graph.add_edge("generator", END)

    return graph.compile()


def run(query_original: str, session_id: str | None = None) -> dict:
    """Executa o grafo completo para uma query.

    Gera session_id automaticamente se não for fornecido.
    Retorna o estado final com resposta, fonte, low_confidence e trace.
    """
    sid = session_id or uuid.uuid4().hex
    initial_state: GraphState = {
        "query_original": query_original,
        "session_id": sid,
        "trace": [],
    }
    state = build_graph().invoke(initial_state)
    state["fonte"] = _classify_source(
        state.get("corpus_used", False),
        state.get("web_used", False),
    )
    _export_trace(state, sid)
    return state


def _export_trace(state: GraphState, session_id: str) -> None:
    """Persiste o trace da execução em traces/{session_id}.json."""
    traces_dir = Path(TRACES_DIR)
    traces_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "session_id": session_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "query_original": state.get("query_original", ""),
        "resposta": state.get("resposta", ""),
        "fonte": state.get("fonte", ""),
        "low_confidence": state.get("low_confidence", False),
        "trace": state.get("trace", []),
    }

    trace_file = traces_dir / f"{session_id}.json"
    trace_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
