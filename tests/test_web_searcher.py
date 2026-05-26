"""Smoke tests do Agente Web Searcher."""

from unittest.mock import patch

import pytest

from agents.web_searcher import search_web


@patch("agents.web_searcher.TAVILY_API_KEY", "fake-key")
@patch("agents.web_searcher.TavilyClient")
def test_search_web_com_resultados(mock_client_cls):
    """Tavily retorna resultados — encontrou=True, lista preenchida."""
    mock_client = mock_client_cls.return_value
    mock_client.search.return_value = {
        "results": [
            {"title": "DRS Rules", "content": "DRS may be used in...", "url": "https://fia.com/drs"},
            {"title": "F1 Aero", "content": "Aerodynamics regulations...", "url": "https://fia.com/aero"},
        ]
    }

    result = search_web({"query_reformulada": "What are the DRS rules in F1 2026?"})

    assert result["web_result"]["encontrou"] is True
    assert len(result["web_result"]["resultados"]) == 2
    assert result["web_result"]["resultados"][0]["titulo"] == "DRS Rules"
    assert result["web_result"]["resultados"][0]["trecho"] == "DRS may be used in..."
    assert result["web_result"]["resultados"][0]["url"] == "https://fia.com/drs"
    assert result["trace"][0]["agente"] == "web_searcher"
    assert "2 resultados" in result["trace"][0]["saida"]


@patch("agents.web_searcher.TAVILY_API_KEY", "fake-key")
@patch("agents.web_searcher.TavilyClient")
def test_search_web_sem_resultados(mock_client_cls):
    """Tavily retorna lista vazia — encontrou=False."""
    mock_client = mock_client_cls.return_value
    mock_client.search.return_value = {"results": []}

    result = search_web({"query_reformulada": "query muito obscura sem hits"})

    assert result["web_result"]["encontrou"] is False
    assert result["web_result"]["resultados"] == []


@patch("agents.web_searcher.TAVILY_API_KEY", "fake-key")
@patch("agents.web_searcher.TavilyClient")
def test_search_web_erro_api(mock_client_cls):
    """Erro da API Tavily — encontrou=False, erro registrado no trace."""
    mock_client = mock_client_cls.return_value
    mock_client.search.side_effect = ConnectionError("network down")

    result = search_web({"query_reformulada": "qualquer query"})

    assert result["web_result"]["encontrou"] is False
    assert result["web_result"]["resultados"] == []
    assert "ConnectionError" in result["trace"][0]["saida"]
    assert "network down" in result["trace"][0]["saida"]


@patch("agents.web_searcher.TAVILY_API_KEY", None)
def test_search_web_sem_api_key():
    """Sem TAVILY_API_KEY — não tenta chamar a API, registra erro no trace."""
    result = search_web({"query_reformulada": "qualquer query"})

    assert result["web_result"]["encontrou"] is False
    assert "TAVILY_API_KEY" in result["trace"][0]["saida"]


def test_search_web_state_invalido():
    """Sem query no state — levanta ValueError."""
    with pytest.raises(ValueError, match="State inválido"):
        search_web({})


@patch("agents.web_searcher.TAVILY_API_KEY", None)
def test_search_web_usa_query_original_se_reformulada_ausente():
    """Sem query_reformulada, usa query_original como fallback."""
    result = search_web({"query_original": "fallback query"})

    assert result["trace"][0]["entrada"] == "fallback query"


@pytest.mark.integration
def test_search_web_integracao_tavily():
    """Requer TAVILY_API_KEY no .env. Rode com: pytest -m integration"""
    result = search_web({"query_reformulada": "What are the FIA F1 2026 power unit regulations?"})

    assert isinstance(result["web_result"]["encontrou"], bool)
    if result["web_result"]["encontrou"]:
        assert len(result["web_result"]["resultados"]) > 0
        assert all("url" in r for r in result["web_result"]["resultados"])
    assert result["trace"][0]["latencia_ms"] >= 0
