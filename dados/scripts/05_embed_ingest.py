"""
05_embed_ingest.py
Gera embeddings dos chunks com Ollama (nomic-embed-text)
e indexa no ChromaDB com metadados (fonte, seção, chunk_id).

Wrapper sequencial sobre dados/ingestion.py::ingest_chunks() +
build_chunks_for_ingest().

Pré-requisitos:
    - Ollama rodando localmente com nomic-embed-text disponível
    - Chunks gerados em chunks/ (rodar 04_chunk.py antes)
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import chromadb  # noqa: E402
import ollama  # noqa: E402

from config import CHROMA_COLLECTION, EMBED_MODEL  # noqa: E402
from dados.ingestion import (  # noqa: E402
    EMBED_BATCH_SIZE,
    build_chunks_for_ingest,
    ingest_chunks,
)

CHUNKS_DIR = Path(__file__).parent.parent / "chunks"
VECTORSTORE = Path(__file__).parent.parent / "vectorstore"
COLLECTION = CHROMA_COLLECTION


def main():
    # Verifica conexão com Ollama
    try:
        models = [m.model for m in ollama.list().models]
        if EMBED_MODEL not in models and f"{EMBED_MODEL}:latest" not in models:
            print(f"ERRO: modelo '{EMBED_MODEL}' não encontrado no Ollama.")
            print(f"Execute: ollama pull {EMBED_MODEL}")
            return
    except Exception as e:
        print(f"ERRO: não foi possível conectar ao Ollama — {e}")
        print("Verifique se o Ollama está rodando: ollama serve")
        return

    VECTORSTORE.mkdir(exist_ok=True)
    client = chromadb.PersistentClient(path=str(VECTORSTORE))

    # Recria a collection se já existir (re-ingestão limpa)
    existing = [c.name for c in client.list_collections()]
    if COLLECTION in existing:
        print(f"Collection '{COLLECTION}' existente encontrada — removendo para re-ingestão limpa.")
        client.delete_collection(COLLECTION)

    collection = client.create_collection(
        name=COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )

    chunk_files = sorted(CHUNKS_DIR.glob("*_chunks.json"))
    if not chunk_files:
        print("Nenhum arquivo de chunks encontrado. Execute 04_chunk.py primeiro.")
        return

    print(f"Modelo de embedding : {EMBED_MODEL}")
    print(f"Vector store        : {VECTORSTORE}")
    print(f"Collection          : {COLLECTION}")
    print(f"Batch size          : {EMBED_BATCH_SIZE}")
    print(f"Arquivos de chunks  : {len(chunk_files)}\n")

    total_inserted = 0
    start = time.time()

    for chunk_file in chunk_files:
        with open(chunk_file, encoding="utf-8") as f:
            chunks_data = json.load(f)

        chunks = build_chunks_for_ingest(chunks_data)
        section = chunks_data.get("section", "?")
        print(f"Ingerindo [{section}] — {len(chunks)} chunks válidos ...", end=" ", flush=True)

        t0 = time.time()
        n = ingest_chunks(collection, chunks)
        elapsed = time.time() - t0

        total_inserted += n
        print(f"OK ({n} inseridos, {elapsed:.1f}s)")

    total_time = time.time() - start
    final_count = collection.count()

    print(f"\n{'='*55}")
    print(f"Ingestão concluída em {total_time:.1f}s")
    print(f"Total inserido      : {total_inserted:,} chunks")
    print(f"Total no ChromaDB   : {final_count:,} documentos")
    print(f"Vector store em     : {VECTORSTORE}")
    print(f"{'='*55}")


if __name__ == "__main__":
    main()
