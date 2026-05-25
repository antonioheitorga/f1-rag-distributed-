"""
Producer SQS — publica 1 mensagem por PDF do corpus na fila de ingestão.

Roda uma vez (do host ou de um container temporário) para disparar uma
ingestão completa. Cada mensagem carrega o nome do arquivo PDF; quem
consome (worker.py) resolve o path relativo ao próprio filesystem.

Antes de publicar, recria a collection do ChromaDB (delete + create)
para garantir re-ingestão limpa.

Uso:
    python infra/producer.py
    SQS_QUEUE_NAME=ingestion-jobs python infra/producer.py
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import boto3  # noqa: E402
import chromadb  # noqa: E402


CORPUS_DIR = Path(__file__).resolve().parent.parent / "dados" / "corpus"
VECTORSTORE = Path(__file__).resolve().parent.parent / "dados" / "vectorstore"

SQS_QUEUE_NAME = os.getenv("SQS_QUEUE_NAME", "ingestion-jobs")
AWS_ENDPOINT_URL = os.getenv("AWS_ENDPOINT_URL", "http://localhost:4566")
COLLECTION = os.getenv("CHROMA_COLLECTION", "fia_2026_regulations")


def _get_or_create_queue(sqs) -> str:
    """Cria a fila se não existir; retorna QueueUrl."""
    existing = sqs.list_queues(QueueNamePrefix=SQS_QUEUE_NAME).get("QueueUrls", [])
    for url in existing:
        if url.endswith(f"/{SQS_QUEUE_NAME}"):
            return url
    response = sqs.create_queue(
        QueueName=SQS_QUEUE_NAME,
        Attributes={
            "VisibilityTimeout": "600",      # 10 min para o worker processar
            "MessageRetentionPeriod": "86400",  # 1 dia
        },
    )
    return response["QueueUrl"]


def _reset_collection() -> None:
    """Apaga e recria a collection do ChromaDB para garantir ingestão limpa."""
    VECTORSTORE.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(VECTORSTORE))
    existing = [c.name for c in client.list_collections()]
    if COLLECTION in existing:
        print(f"Collection '{COLLECTION}' existente — removendo.")
        client.delete_collection(COLLECTION)
    client.create_collection(
        name=COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )
    print(f"Collection '{COLLECTION}' criada limpa.")


def main():
    pdfs = sorted(CORPUS_DIR.glob("*.pdf"))
    if not pdfs:
        print(f"Nenhum PDF em {CORPUS_DIR}")
        sys.exit(1)

    print("=" * 60)
    print("  Producer SQS — F1 RAG Distributed")
    print("=" * 60)
    print(f"PDFs encontrados   : {len(pdfs)}")
    print(f"SQS endpoint       : {AWS_ENDPOINT_URL}")
    print(f"Fila               : {SQS_QUEUE_NAME}")
    print(f"Vector store       : {VECTORSTORE}")
    print(f"Collection         : {COLLECTION}")
    print()

    _reset_collection()

    sqs = boto3.client("sqs", endpoint_url=AWS_ENDPOINT_URL)
    queue_url = _get_or_create_queue(sqs)
    print(f"Queue URL          : {queue_url}\n")

    published = 0
    for pdf in pdfs:
        message = {
            "pdf_filename": pdf.name,
            "submitted_at": datetime.now(timezone.utc).isoformat(),
        }
        sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps(message),
        )
        published += 1
        print(f"  → publicado: {pdf.name}")

    print()
    print("=" * 60)
    print(f"  {published} mensagens publicadas em '{SQS_QUEUE_NAME}'.")
    print("  Suba os workers com: docker compose up -d --scale worker=N")
    print("=" * 60)


if __name__ == "__main__":
    main()
