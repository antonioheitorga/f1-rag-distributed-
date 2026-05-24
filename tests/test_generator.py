"""Smoke tests do Agente Gerador."""

from unittest.mock import patch

import pytest

from agents.generator import generate


@patch("agents.generator.ChatOllama")
@patch("agents.generator.ChatPromptTemplate")
def test_generate_corpus_only(mock_prompt_cls, _mock_llm_cls):
    chain = mock_prompt_cls.from_template.return_value.__or__.return_value
    chain.invoke.return_value.content = "Resposta baseada no corpus."

    state = {
        "query_reformulada": "What are DRS rules?",
        "retriever_result": {
            "fallback_to_web": False,
            "confidence_warning": None,
            "hits": [
                {"content": "DRS can only be used in designated zones.", "score": 0.91, "metadata": {"section": "B"}}
            ],
        },
    }

    result = generate(state)

    assert result["resposta"] == "Resposta baseada no corpus."
    assert result["corpus_used"] is True
    assert result["web_used"] is False
    assert result["low_confidence"] is False
    assert result["confidence_warning"] is None
    assert result["trace"][-1]["agente"] == "generator"


@patch("agents.generator.ChatOllama")
@patch("agents.generator.ChatPromptTemplate")
def test_generate_web_fallback_com_resultados(mock_prompt_cls, _mock_llm_cls):
    """Web foi acionada e encontrou resultados → low_confidence=False."""
    chain = mock_prompt_cls.from_template.return_value.__or__.return_value
    chain.invoke.return_value.content = "Resposta com base na web."

    state = {
        "query_original": "regra obscura de PU",
        "retriever_result": {
            "fallback_to_web": True,
            "confidence_warning": "Score abaixo do mínimo configurado.",
            "hits": [],
        },
        "web_result": {
            "resultados": [
                {"titulo": "FIA note", "trecho": "Temporary guidance...", "url": "https://example.com/fia"}
            ],
            "encontrou": True,
        },
    }

    result = generate(state)

    assert result["corpus_used"] is False
    assert result["web_used"] is True
    assert result["low_confidence"] is False
    assert result["confidence_warning"] is None


@patch("agents.generator.ChatOllama")
@patch("agents.generator.ChatPromptTemplate")
def test_generate_sem_contexto_low_confidence(mock_prompt_cls, _mock_llm_cls):
    """Corpus e web vazios → low_confidence=True."""
    chain = mock_prompt_cls.from_template.return_value.__or__.return_value
    chain.invoke.return_value.content = "Não tenho informação suficiente."

    state = {
        "query_original": "regra inexistente",
        "retriever_result": {
            "fallback_to_web": True,
            "confidence_warning": "Score abaixo do mínimo configurado.",
            "hits": [],
        },
        "web_result": {"resultados": [], "encontrou": False},
    }

    result = generate(state)

    assert result["corpus_used"] is False
    assert result["web_used"] is False
    assert result["low_confidence"] is True
    assert "Score abaixo" in result["confidence_warning"]


@patch("agents.generator.ChatOllama")
@patch("agents.generator.ChatPromptTemplate")
def test_generate_hybrid(mock_prompt_cls, _mock_llm_cls):
    chain = mock_prompt_cls.from_template.return_value.__or__.return_value
    chain.invoke.return_value.content = "Resposta híbrida."

    state = {
        "query_reformulada": "engine cooling constraints",
        "retriever_result": {
            "fallback_to_web": False,
            "confidence_warning": None,
            "hits": [{"content": "Cooling rules from corpus.", "score": 0.84, "metadata": {}}],
        },
        "web_result": {
            "resultados": [{"titulo": "News", "trecho": "Recent clarification", "url": "https://example.com/news"}],
            "encontrou": True,
        },
    }

    result = generate(state)
    assert result["corpus_used"] is True
    assert result["web_used"] is True


def test_generate_state_invalido():
    with pytest.raises(ValueError, match="State inválido"):
        generate({})


@patch("agents.generator.ChatOllama")
@patch("agents.generator.ChatPromptTemplate")
def test_generate_preserva_query_original_no_prompt(mock_prompt_cls, _mock_llm_cls):
    """Garante que o prompt recebe a query_original (idioma do usuário) e a query_reformulada separadas."""
    chain = mock_prompt_cls.from_template.return_value.__or__.return_value
    chain.invoke.return_value.content = "O DRS é..."

    state = {
        "query_original": "O que é DRS?",
        "query_reformulada": "Drag Reduction System Formula 1 2026 regulations",
        "retriever_result": {
            "fallback_to_web": False,
            "confidence_warning": None,
            "hits": [{"content": "DRS context.", "score": 0.9, "metadata": {}}],
        },
    }

    generate(state)

    # invoke foi chamado com as duas queries separadas
    invoke_args = chain.invoke.call_args[0][0]
    assert invoke_args["query_original"] == "O que é DRS?"
    assert invoke_args["query_reformulada"] == "Drag Reduction System Formula 1 2026 regulations"
