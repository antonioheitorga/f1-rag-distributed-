"""
pipeline_parallel.py
Pipeline de ingestão paralela — processa N PDFs simultaneamente via
ProcessPoolExecutor. Cada worker executa os passos 1-5 em memória para
1 PDF, escrevendo só no ChromaDB no final.

Diferenças vs pipeline.py (sequencial):
- Não escreve arquivos intermediários (extracted/, processed/, chunks/).
- Workers compartilham a mesma collection do Chroma — collection é criada
  uma única vez aqui no main.
- Mede e reporta speedup vs sequencial.

Uso:
    python pipeline_parallel.py
    INGEST_MAX_WORKERS=3 python pipeline_parallel.py
"""

import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chromadb  # noqa: E402
import ollama  # noqa: E402

from dados.ingestion import EMBED_MODEL, process_single_pdf  # noqa: E402

CORPUS_DIR = Path(__file__).parent / "corpus"
VECTORSTORE = Path(__file__).parent / "vectorstore"
COLLECTION = "fia_2026_regulations"


def _default_max_workers(n_pdfs: int) -> int:
    """min(6, cpu_count) por default, sobrescrevível via INGEST_MAX_WORKERS."""
    env = os.getenv("INGEST_MAX_WORKERS")
    if env:
        try:
            return max(1, int(env))
        except ValueError:
            pass
    cpu = os.cpu_count() or 1
    return min(n_pdfs, cpu)


def _check_ollama() -> bool:
    """Garante que o modelo de embedding está disponível antes de disparar workers."""
    try:
        models = [m.model for m in ollama.list().models]
    except Exception as e:
        print(f"ERRO: não foi possível conectar ao Ollama — {e}")
        print("Verifique se o Ollama está rodando: ollama serve")
        return False

    if EMBED_MODEL not in models and f"{EMBED_MODEL}:latest" not in models:
        print(f"ERRO: modelo '{EMBED_MODEL}' não encontrado no Ollama.")
        print(f"Execute: ollama pull {EMBED_MODEL}")
        return False
    return True


def _prepare_collection() -> None:
    """Recria a collection (re-ingestão limpa) — executado UMA vez no main,
    antes dos workers serem disparados."""
    VECTORSTORE.mkdir(exist_ok=True)
    client = chromadb.PersistentClient(path=str(VECTORSTORE))
    existing = [c.name for c in client.list_collections()]
    if COLLECTION in existing:
        print(f"Collection '{COLLECTION}' existente — removendo para re-ingestão limpa.")
        client.delete_collection(COLLECTION)
    client.create_collection(
        name=COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )


def _final_count() -> int:
    client = chromadb.PersistentClient(path=str(VECTORSTORE))
    return client.get_collection(COLLECTION).count()


def main():
    if not _check_ollama():
        sys.exit(1)

    pdfs = sorted(CORPUS_DIR.glob("*.pdf"))
    if not pdfs:
        print(f"Nenhum PDF encontrado em {CORPUS_DIR}")
        sys.exit(1)

    max_workers = _default_max_workers(len(pdfs))

    print("=" * 60)
    print("  Pipeline de Ingestão Paralela — FIA 2026 F1 Regulations")
    print("=" * 60)
    print(f"PDFs encontrados   : {len(pdfs)}")
    print(f"Workers em paralelo: {max_workers}")
    print(f"Vector store       : {VECTORSTORE}")
    print(f"Collection         : {COLLECTION}")
    print(f"Modelo de embedding: {EMBED_MODEL}")
    print()

    _prepare_collection()

    print("Disparando workers...\n")
    t0 = time.time()
    results = []
    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        future_to_pdf = {
            pool.submit(process_single_pdf, pdf, VECTORSTORE, COLLECTION): pdf
            for pdf in pdfs
        }
        for fut in as_completed(future_to_pdf):
            pdf = future_to_pdf[fut]
            try:
                r = fut.result()
                results.append(r)
                print(
                    f"  [OK] {r['source_file']:55} "
                    f"section={r['section']:30} "
                    f"chunks={r['chunks_inserted']}"
                )
            except Exception as e:
                print(f"  [ERRO] {pdf.name} → {type(e).__name__}: {e}")

    elapsed = time.time() - t0
    total_chunks = sum(r["chunks_inserted"] for r in results)
    final = _final_count()

    print()
    print("=" * 60)
    print(f"Ingestão paralela concluída em {elapsed:.1f}s")
    print(f"PDFs processados   : {len(results)}/{len(pdfs)}")
    print(f"Total inserido     : {total_chunks:,} chunks")
    print(f"Total no ChromaDB  : {final:,} documentos")
    print(f"Workers usados     : {max_workers}")
    print("=" * 60)


if __name__ == "__main__":
    main()
