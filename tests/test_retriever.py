"""Testes do Agente Retriever."""

from unittest.mock import patch

from agents.retriever import retrieve


class _FakeCollection:
    def __init__(self, query_result):
        self._query_result = query_result

    def query(self, **_kwargs):
        return self._query_result


class _FakeClient:
    def __init__(self, query_result):
        self._query_result = query_result

    def get_collection(self, _name):
        return _FakeCollection(self._query_result)


def _patch_imports(query_result, embedding):
    """Helper que constrói o side_effect para mock_import."""
    real_import = __import__

    def _fake_import(name, *args, **kwargs):
        if name == "chromadb":
            class _FakeChromadb:
                @staticmethod
                def PersistentClient(path):
                    _ = path
                    return _FakeClient(query_result)
            return _FakeChromadb
        if name == "ollama":
            class _FakeOllama:
                @staticmethod
                def embeddings(model, prompt):
                    _ = model
                    _ = prompt
                    return {"embedding": embedding}
            return _FakeOllama
        return real_import(name, *args, **kwargs)

    return _fake_import


@patch("agents.retriever.Path.exists", return_value=True)
@patch("agents.retriever.CHROMA_COLLECTION", "fia_2026_regulations")
@patch("agents.retriever.RETRIEVER_TOP_K", 5)
@patch("agents.retriever.RETRIEVER_THRESHOLD", 0.5)
def test_retrieve_estrutura_saida(_mock_exists):
    query_result = {
        "documents": [["doc A", "doc B"]],
        "metadatas": [[{"section": "A"}, {"section": "B"}]],
        "distances": [[0.1, 0.4]],  # scores: 0.9, 0.6
    }
    with patch("builtins.__import__") as mock_import:
        mock_import.side_effect = _patch_imports(query_result, [0.01, 0.02, 0.03])
        result = retrieve({"query_reformulada": "DRS rules"})

    assert "retriever_result" in result
    rr = result["retriever_result"]
    assert rr["query"] == "DRS rules"
    assert rr["threshold"] == 0.5
    assert rr["top_k"] == 5
    assert rr["best_score"] == 0.9
    assert rr["fallback_to_web"] is False
    assert rr["confidence_warning"] is None
    assert rr["total_hits"] == 2
    assert len(rr["hits"]) == 2
    assert rr["hits"][0]["content"] == "doc A"
    assert rr["hits"][0]["score"] == 0.9

    assert len(result["trace"]) == 1
    trace = result["trace"][0]
    assert trace["agente"] == "retriever"
    assert trace["entrada"] == "DRS rules"
    assert "hits acima de" in trace["saida"]


@patch("agents.retriever.Path.exists", return_value=True)
@patch("agents.retriever.RETRIEVER_TOP_K", 5)
@patch("agents.retriever.RETRIEVER_THRESHOLD", 0.7)
def test_retrieve_aplica_threshold(_mock_exists):
    query_result = {
        "documents": [["doc A", "doc B"]],
        "metadatas": [[{"section": "A"}, {"section": "B"}]],
        "distances": [[0.2, 0.8]],  # scores: 0.8, 0.2
    }
    with patch("builtins.__import__") as mock_import:
        mock_import.side_effect = _patch_imports(query_result, [0.11, 0.22])
        result = retrieve({"query_original": "engine regulations"})

    rr = result["retriever_result"]
    assert rr["best_score"] == 0.8
    assert rr["fallback_to_web"] is False
    assert rr["confidence_warning"] is None
    assert rr["total_hits"] == 1
    assert len(rr["hits"]) == 1
    assert rr["hits"][0]["content"] == "doc A"
    assert rr["hits"][0]["score"] == 0.8


@patch("agents.retriever.Path.exists", return_value=True)
@patch("agents.retriever.RETRIEVER_TOP_K", 3)
@patch("agents.retriever.RETRIEVER_THRESHOLD", 0.1)
def test_retrieve_appenda_trace_existente(_mock_exists):
    query_result = {
        "documents": [["doc X"]],
        "metadatas": [[{"section": "X"}]],
        "distances": [[0.3]],  # score: 0.7
    }
    trace_anterior = [{
        "agente": "reformulator",
        "entrada": "pt query",
        "saida": "en query",
        "timestamp": "2026-01-01T00:00:00+00:00",
        "latencia_ms": 12,
    }]

    with patch("builtins.__import__") as mock_import:
        mock_import.side_effect = _patch_imports(query_result, [0.5, 0.6])
        result = retrieve({
            "query_reformulada": "en query",
            "trace": trace_anterior,
        })

    assert len(result["trace"]) == 2
    assert result["trace"][0]["agente"] == "reformulator"
    assert result["trace"][1]["agente"] == "retriever"


@patch("agents.retriever.Path.exists", return_value=True)
@patch("agents.retriever.RETRIEVER_TOP_K", 3)
@patch("agents.retriever.RETRIEVER_THRESHOLD", 0.7)
def test_retrieve_aciona_fallback_quando_best_score_abaixo_threshold(_mock_exists):
    query_result = {
        "documents": [["doc low"]],
        "metadatas": [[{"section": "L"}]],
        "distances": [[0.35]],  # score: 0.65
    }

    with patch("builtins.__import__") as mock_import:
        mock_import.side_effect = _patch_imports(query_result, [0.9, 0.1])
        result = retrieve({"query_original": "fallback case"})

    rr = result["retriever_result"]
    assert rr["best_score"] == 0.65
    assert rr["fallback_to_web"] is True
    assert rr["confidence_warning"] is not None
    assert "abaixo do threshold" in rr["confidence_warning"]
    assert rr["total_hits"] == 0
    assert rr["hits"] == []


@patch("agents.retriever.Path.exists", return_value=True)
@patch("agents.retriever.RETRIEVER_TOP_K", 3)
@patch("agents.retriever.RETRIEVER_THRESHOLD", 0.7)
def test_retrieve_sem_resultados_define_best_score_zero_e_fallback_true(_mock_exists):
    query_result = {
        "documents": [[]],
        "metadatas": [[]],
        "distances": [[]],
    }

    with patch("builtins.__import__") as mock_import:
        mock_import.side_effect = _patch_imports(query_result, [0.2, 0.8])
        result = retrieve({"query_original": "no hits case"})

    rr = result["retriever_result"]
    assert rr["best_score"] == 0.0
    assert rr["fallback_to_web"] is True
    assert rr["confidence_warning"] is not None
    assert rr["total_hits"] == 0
    assert rr["hits"] == []
