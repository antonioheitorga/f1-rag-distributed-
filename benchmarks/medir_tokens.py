"""Mede chunks e tokens por PDF do corpus FIA, em sequência local.

Roda os 6 PDFs via process_single_pdf() e imprime tabela com:
- chunks inseridos no ChromaDB
- tokens consumidos pelo embedding (campo prompt_eval_count da API Ollama)
- duração total de cada PDF

Útil para gerar dados reais que vão para a Seção 5.2 do documento técnico.

Pré-requisitos:
- Ollama rodando localmente (nativo ou via docker compose)
- Modelo nomic-embed-text baixado (ollama pull nomic-embed-text)

Uso:
    python benchmarks/medir_tokens.py
"""

import sys
import time
from pathlib import Path

# Adiciona raiz do projeto ao path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dados.ingestion import process_single_pdf  # noqa: E402

CORPUS = Path(__file__).resolve().parent.parent / "dados" / "corpus"
VECTORSTORE = Path(__file__).resolve().parent.parent / "dados" / "vectorstore_relatorio"
COLLECTION = "relatorio_test"


def main():
    print(f"{'PDF':<75} {'chunks':>8} {'tokens':>10} {'duracao':>10}")
    print("-" * 105)

    total_chunks = 0
    total_tokens = 0
    total_time = 0.0

    pdfs = sorted(CORPUS.glob("*.pdf"))
    if not pdfs:
        print(f"Nenhum PDF encontrado em {CORPUS}")
        sys.exit(1)

    for pdf in pdfs:
        t0 = time.time()
        result = process_single_pdf(pdf, VECTORSTORE, COLLECTION)
        elapsed = time.time() - t0
        chunks = result["chunks_inserted"]
        tokens = result["embedding_tokens"]
        total_chunks += chunks
        total_tokens += tokens
        total_time += elapsed
        print(f"{pdf.name:<75} {chunks:>8} {tokens:>10} {elapsed:>9.1f}s")

    print("-" * 105)
    print(f"{'TOTAL':<75} {total_chunks:>8} {total_tokens:>10} {total_time:>9.1f}s")


if __name__ == "__main__":
    main()
