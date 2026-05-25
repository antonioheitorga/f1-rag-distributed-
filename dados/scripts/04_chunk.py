"""
04_chunk.py
Divide os textos pré-processados em chunks usando LangChain RecursiveCharacterTextSplitter.
Executa testes com diferentes chunk_sizes (exploratório) e salva o melhor resultado em chunks/.

Wrapper sequencial sobre dados/ingestion.py::chunk_data(). Os testes comparativos
ficam aqui pois são análise exploratória, não parte do fluxo de produção.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from langchain_text_splitters import RecursiveCharacterTextSplitter  # noqa: E402

from dados.ingestion import (  # noqa: E402
    BEST_CHUNK_CONFIG,
    CHUNK_SEPARATORS,
    _build_full_text,
    chunk_data,
)

PROCESSED_DIR = Path(__file__).parent.parent / "processed"
CHUNKS_DIR = Path(__file__).parent.parent / "chunks"
CHUNKS_DIR.mkdir(exist_ok=True)

# Configurações comparativas (exploração, não produção)
CHUNK_CONFIGS = [
    {"chunk_size": 256,  "chunk_overlap": 32},
    {"chunk_size": 512,  "chunk_overlap": 64},
    {"chunk_size": 1024, "chunk_overlap": 128},
    {"chunk_size": 2048, "chunk_overlap": 256},
]


def _chunk_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=CHUNK_SEPARATORS,
        length_function=len,
    )
    return splitter.split_text(text)


def _compute_metrics(chunks: list[str], chunk_size: int) -> dict:
    sizes = [len(c) for c in chunks]
    avg = sum(sizes) / len(sizes) if sizes else 0
    over_limit = sum(1 for s in sizes if s > chunk_size)
    return {
        "n_chunks": len(chunks),
        "avg_size": round(avg, 1),
        "min_size": min(sizes, default=0),
        "max_size": max(sizes, default=0),
        "over_limit": over_limit,
    }


def _run_size_tests(text: str, source: str):
    """Avalia diferentes chunk sizes e imprime relatório comparativo."""
    print(f"\n  Testes de chunk size para: {source}")
    print(f"  {'Config':<28} {'Chunks':>7} {'Avg':>7} {'Min':>6} {'Max':>7} {'Over':>5}")
    print(f"  {'-'*65}")
    for cfg in CHUNK_CONFIGS:
        chunks = _chunk_text(text, cfg["chunk_size"], cfg["chunk_overlap"])
        m = _compute_metrics(chunks, cfg["chunk_size"])
        label = f"size={cfg['chunk_size']} overlap={cfg['chunk_overlap']}"
        print(f"  {label:<28} {m['n_chunks']:>7} {m['avg_size']:>7.0f} "
              f"{m['min_size']:>6} {m['max_size']:>7} {m['over_limit']:>5}")


def main():
    jsons = sorted(PROCESSED_DIR.glob("*.json"))
    if not jsons:
        print("Nenhum JSON encontrado em processed/. Execute 03_preprocess.py primeiro.")
        return

    print(f"Chunking de {len(jsons)} arquivo(s)...\n")
    print(f"Configuração de produção: chunk_size={BEST_CHUNK_CONFIG['chunk_size']}, "
          f"overlap={BEST_CHUNK_CONFIG['chunk_overlap']}\n")

    total_chunks = 0
    for jp in jsons:
        with open(jp, encoding="utf-8") as f:
            data = json.load(f)

        # Testes exploratórios
        _run_size_tests(_build_full_text(data), data["source_file"])

        # Chunking de produção
        chunked = chunk_data(data)
        stem = Path(chunked["source_file"]).stem
        out_path = CHUNKS_DIR / f"{stem}_chunks.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(chunked, f, ensure_ascii=False, indent=2)

        total_chunks += chunked["total_chunks"]
        print(f"\n  → Salvo: {out_path.name} ({chunked['total_chunks']} chunks)")

    print(f"\nChunking concluído. Total de chunks: {total_chunks:,} | Arquivos em: {CHUNKS_DIR}")


if __name__ == "__main__":
    main()
