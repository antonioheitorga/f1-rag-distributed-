"""Orquestrador LangGraph (padrão hub-and-spoke / supervisor).

O orquestrador é um agente central: o usuário conversa apenas com ele, e
cada agente especialista (reformulator, retriever, web_searcher, generator)
conversa apenas com o orquestrador — nunca entre si.

A cada rodada o orquestrador observa o estado, decide o próximo agente de
forma determinística (sem LLM, baseado em quais campos do GraphState já
foram preenchidos), o agente executa e devolve o resultado ao orquestrador,
que então identifica o próximo passo. O ciclo encerra quando a resposta
está pronta.

    usuário ─► orchestrator ─► {reformulator|retriever|web_searcher|generator}
                    ▲                        │
                    └────────────────────────┘ (todo agente volta ao hub)
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


def _decide(state: GraphState) -> tuple[str, str]:
    """Decide o próximo passo do fluxo a partir do estado atual.

    Determinístico, sem LLM: olha quais campos do GraphState já foram
    preenchidos e devolve (decisao, motivo). Cada agente preenche um campo
    distinto, então a decisão sempre avança — não há ciclo infinito.

    Fonte única da decisão: consumida tanto pelo nó `orchestrate` (que grava
    o motivo no trace) quanto pela aresta condicional `_decide_next` (que
    roteia), garantindo que trace e roteamento nunca divergem.
    """
    if not state.get("query_reformulada"):
        return "reformulator", "query ainda não reformulada"
    if state.get("retriever_result") is None:
        return "retriever", "query reformulada; falta buscar no corpus"
    retriever_result = state.get("retriever_result") or {}
    if retriever_result.get("fallback_to_web") and state.get("web_result") is None:
        return "web_searcher", "corpus abaixo do threshold; acionando fallback web"
    if not state.get("resposta"):
        return "generator", "contexto reunido; gerando resposta final"
    return "end", "resposta pronta; encerrando"


def orchestrate(state: GraphState) -> dict:
    """Nó central do grafo: o orquestrador como agente.

    Decide o próximo passo, registra a decisão e o motivo no trace e, ao
    encerrar, classifica a fonte da resposta. O roteamento em si é feito pela
    aresta condicional `_decide_next` logo após este nó.

    Lê: todo o GraphState.
    Escreve: trace (append), fonte (somente ao encerrar).
    """
    decisao, motivo = _decide(state)

    updates: dict = {
        "trace": state.get("trace", []) + [{
            "agente": "orchestrator",
            "decisao": decisao,
            "motivo": motivo,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }],
    }
    if decisao == "end":
        updates["fonte"] = _classify_source(
            state.get("corpus_used", False),
            state.get("web_used", False),
        )
    return updates


def _decide_next(state: GraphState) -> str:
    """Aresta condicional após o orquestrador: devolve só o destino."""
    decisao, _ = _decide(state)
    return decisao


def build_graph():
    """Monta e compila o grafo hub-and-spoke.

    O orquestrador é o ponto de entrada e o hub central: roteia para um
    agente por vez, e todo agente devolve o resultado ao orquestrador.
    """
    graph = StateGraph(GraphState)

    graph.add_node("orchestrator", orchestrate)
    graph.add_node("reformulator", reformulate)
    graph.add_node("retriever", retrieve)
    graph.add_node("web_searcher", search_web)
    graph.add_node("generator", generate)

    graph.set_entry_point("orchestrator")
    graph.add_conditional_edges(
        "orchestrator",
        _decide_next,
        {
            "reformulator": "reformulator",
            "retriever": "retriever",
            "web_searcher": "web_searcher",
            "generator": "generator",
            "end": END,
        },
    )
    graph.add_edge("reformulator", "orchestrator")
    graph.add_edge("retriever", "orchestrator")
    graph.add_edge("web_searcher", "orchestrator")
    graph.add_edge("generator", "orchestrator")

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
