"""Smoke tests do Orquestrador LangGraph.

Os 4 agentes são mockados — os testes verificam apenas o roteamento
do grafo, não o comportamento interno de cada agente.
"""

from unittest.mock import patch

from orchestration.orchestrator import run


def _fake_reformulate(state):
    return {
        "query_reformulada": "reformulated query",
        "trace": state.get("trace", []) + [{"agente": "reformulator"}],
    }


def _fake_retrieve_hit(state):
    return {
        "retriever_result": {
            "fallback_to_web": False,
            "best_score": 0.85,
            "hits": [{"content": "corpus chunk", "score": 0.85, "metadata": {}}],
            "confidence_warning": None,
        },
        "trace": state.get("trace", []) + [{"agente": "retriever"}],
    }


def _fake_retrieve_miss(state):
    return {
        "retriever_result": {
            "fallback_to_web": True,
            "best_score": 0.2,
            "hits": [],
            "confidence_warning": "Score abaixo do threshold.",
        },
        "trace": state.get("trace", []) + [{"agente": "retriever"}],
    }


def _fake_search_web(state):
    return {
        "web_result": {
            "resultados": [{"titulo": "T", "trecho": "C", "url": "http://x"}],
            "encontrou": True,
        },
        "trace": state.get("trace", []) + [{"agente": "web_searcher"}],
    }


def _fake_generate(state):
    return {
        "resposta": "final answer",
        "corpus_used": True,
        "web_used": False,
        "low_confidence": False,
        "confidence_warning": None,
        "trace": state.get("trace", []) + [{"agente": "generator"}],
    }


@patch("orchestration.orchestrator.generate", side_effect=_fake_generate)
@patch("orchestration.orchestrator.search_web", side_effect=_fake_search_web)
@patch("orchestration.orchestrator.retrieve", side_effect=_fake_retrieve_hit)
@patch("orchestration.orchestrator.reformulate", side_effect=_fake_reformulate)
def test_fluxo_corpus(mock_ref, mock_ret, mock_web, mock_gen):
    final_state = run("o que é DRS?")

    assert mock_ref.called
    assert mock_ret.called
    assert mock_web.called is False
    assert mock_gen.called

    agentes = [t["agente"] for t in final_state["trace"]]
    assert agentes == ["reformulator", "retriever", "generator"]


@patch("orchestration.orchestrator.generate", side_effect=_fake_generate)
@patch("orchestration.orchestrator.search_web", side_effect=_fake_search_web)
@patch("orchestration.orchestrator.retrieve", side_effect=_fake_retrieve_miss)
@patch("orchestration.orchestrator.reformulate", side_effect=_fake_reformulate)
def test_fluxo_web_fallback(mock_ref, mock_ret, mock_web, mock_gen):
    final_state = run("pergunta fora do corpus")

    assert mock_web.called
    agentes = [t["agente"] for t in final_state["trace"]]
    assert agentes == ["reformulator", "retriever", "web_searcher", "generator"]


@patch("orchestration.orchestrator.generate", side_effect=_fake_generate)
@patch("orchestration.orchestrator.search_web", side_effect=_fake_search_web)
@patch("orchestration.orchestrator.retrieve", side_effect=_fake_retrieve_hit)
@patch("orchestration.orchestrator.reformulate", side_effect=_fake_reformulate)
def test_run_gera_session_id(mock_ref, mock_ret, mock_web, mock_gen):
    final_state = run("qualquer query")

    assert "session_id" in final_state
    assert len(final_state["session_id"]) > 0


@patch("orchestration.orchestrator.generate", side_effect=_fake_generate)
@patch("orchestration.orchestrator.search_web", side_effect=_fake_search_web)
@patch("orchestration.orchestrator.retrieve", side_effect=_fake_retrieve_hit)
@patch("orchestration.orchestrator.reformulate", side_effect=_fake_reformulate)
def test_state_final_completo(mock_ref, mock_ret, mock_web, mock_gen):
    final_state = run("qualquer query", session_id="fixed-id")

    assert final_state["session_id"] == "fixed-id"
    assert final_state["resposta"] == "final answer"
    assert final_state["fonte"] == "corpus"
    assert final_state["low_confidence"] is False
    assert final_state["confidence_warning"] is None
    assert [t["agente"] for t in final_state["trace"]] == ["reformulator", "retriever", "generator"]
