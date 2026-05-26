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
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import boto3  # noqa: E402
import chromadb  # noqa: E402

from config import (  # noqa: E402
    AWS_ENDPOINT_URL,
    CHROMA_COLLECTION,
    SQS_DLQ_NAME,
    SQS_MAX_RECEIVE_COUNT,
    SQS_QUEUE_NAME,
    SQS_VISIBILITY_TIMEOUT,
)
from infra.metrics import emit_metric  # noqa: E402


CORPUS_DIR = Path(__file__).resolve().parent.parent / "dados" / "corpus"
VECTORSTORE = Path(__file__).resolve().parent.parent / "dados" / "vectorstore"
COLLECTION = CHROMA_COLLECTION


def _get_or_create_dlq(sqs) -> tuple[str, str]:
    """Cria a DLQ se não existir; retorna (QueueUrl, QueueArn)."""
    existing = sqs.list_queues(QueueNamePrefix=SQS_DLQ_NAME).get("QueueUrls", [])
    dlq_url = None
    for url in existing:
        if url.endswith(f"/{SQS_DLQ_NAME}"):
            dlq_url = url
            break
    if dlq_url is None:
        response = sqs.create_queue(
            QueueName=SQS_DLQ_NAME,
            Attributes={
                "MessageRetentionPeriod": "1209600",  # 14 dias — DLQ guarda mais tempo p/ debug
            },
        )
        dlq_url = response["QueueUrl"]

    attrs = sqs.get_queue_attributes(QueueUrl=dlq_url, AttributeNames=["QueueArn"])
    return dlq_url, attrs["Attributes"]["QueueArn"]


def _get_or_create_main_queue(sqs, dlq_arn: str) -> str:
    """Cria a fila principal com RedrivePolicy apontando para a DLQ.
    Se já existir, atualiza os atributos (idempotente)."""
    redrive_policy = json.dumps({
        "deadLetterTargetArn": dlq_arn,
        "maxReceiveCount": SQS_MAX_RECEIVE_COUNT,
    })
    attributes = {
        "VisibilityTimeout": str(SQS_VISIBILITY_TIMEOUT),
        "MessageRetentionPeriod": "86400",  # 1 dia
        "RedrivePolicy": redrive_policy,
    }

    existing = sqs.list_queues(QueueNamePrefix=SQS_QUEUE_NAME).get("QueueUrls", [])
    for url in existing:
        if url.endswith(f"/{SQS_QUEUE_NAME}"):
            # Atualiza atributos (pode ter mudado RedrivePolicy ou VisibilityTimeout)
            sqs.set_queue_attributes(QueueUrl=url, Attributes=attributes)
            return url

    response = sqs.create_queue(QueueName=SQS_QUEUE_NAME, Attributes=attributes)
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
    print(f"Fila principal     : {SQS_QUEUE_NAME}")
    print(f"DLQ                : {SQS_DLQ_NAME}")
    print(f"maxReceiveCount    : {SQS_MAX_RECEIVE_COUNT}")
    print(f"Vector store       : {VECTORSTORE}")
    print(f"Collection         : {COLLECTION}")
    print()

    _reset_collection()

    sqs = boto3.client("sqs", endpoint_url=AWS_ENDPOINT_URL)
    dlq_url, dlq_arn = _get_or_create_dlq(sqs)
    queue_url = _get_or_create_main_queue(sqs, dlq_arn)
    print(f"DLQ URL            : {dlq_url}")
    print(f"DLQ ARN            : {dlq_arn}")
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

    emit_metric("jobs_published", published)

    print()
    print("=" * 60)
    print(f"  {published} mensagens publicadas em '{SQS_QUEUE_NAME}'.")
    print("  Suba os workers com: docker compose up -d --scale worker=N")
    print("=" * 60)


if __name__ == "__main__":
    main()
