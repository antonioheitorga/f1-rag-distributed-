"""
Worker SQS — consome mensagens da fila de ingestão e processa 1 PDF por vez.

Long-polling com VisibilityTimeout de 600s. Em sucesso, deleta a mensagem;
em falha, deixa expirar e voltar pra fila (DLQ entrará em §4.5).

Idle timeout: se WORKER_IDLE_TIMEOUT_SEC segundos passam sem receber
mensagem, o worker encerra. Default 0 = roda para sempre (produção).
Para demo/teste, setar para algo entre 30 e 120.

Uso:
    python infra/worker.py
    WORKER_IDLE_TIMEOUT_SEC=60 python infra/worker.py
"""

import json
import os
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import boto3  # noqa: E402

from config import (  # noqa: E402
    AWS_ENDPOINT_URL,
    CHROMA_COLLECTION,
    SQS_POLL_WAIT_SECONDS,
    SQS_QUEUE_NAME,
    SQS_VISIBILITY_TIMEOUT,
    WORKER_IDLE_TIMEOUT_SEC,
)
from dados.ingestion import process_single_pdf  # noqa: E402
from infra.metrics import emit_metric  # noqa: E402


CORPUS_DIR = Path(__file__).resolve().parent.parent / "dados" / "corpus"
VECTORSTORE = Path(__file__).resolve().parent.parent / "dados" / "vectorstore"

COLLECTION = CHROMA_COLLECTION
POLL_WAIT_SECONDS = SQS_POLL_WAIT_SECONDS
VISIBILITY_TIMEOUT = SQS_VISIBILITY_TIMEOUT
IDLE_TIMEOUT_SEC = WORKER_IDLE_TIMEOUT_SEC

WORKER_ID = f"{socket.gethostname()}#{os.getpid()}"


def _log(event: str, **fields):
    """Log estruturado simples (timestamp + worker_id + evento + campos)."""
    parts = [
        datetime.now(timezone.utc).isoformat(timespec="seconds"),
        f"[{WORKER_ID}]",
        event,
    ]
    for k, v in fields.items():
        parts.append(f"{k}={v}")
    print(" ".join(parts), flush=True)


def _resolve_queue_url(sqs) -> str:
    """Localiza a URL da fila (espera ela já existir — criada pelo producer)."""
    existing = sqs.list_queues(QueueNamePrefix=SQS_QUEUE_NAME).get("QueueUrls", [])
    for url in existing:
        if url.endswith(f"/{SQS_QUEUE_NAME}"):
            return url
    raise RuntimeError(
        f"Fila '{SQS_QUEUE_NAME}' não encontrada em {AWS_ENDPOINT_URL}. "
        "Rode o producer primeiro."
    )


def _process_message(msg: dict) -> dict:
    """Parseia e processa 1 mensagem. Retorna o resultado de process_single_pdf."""
    body = json.loads(msg["Body"])
    pdf_filename = body["pdf_filename"]
    pdf_path = CORPUS_DIR / pdf_filename

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF não encontrado no worker: {pdf_path}")

    t0 = time.time()
    result = process_single_pdf(pdf_path, VECTORSTORE, COLLECTION)
    result["duration_ms"] = int((time.time() - t0) * 1000)
    return result


def main():
    _log(
        "worker_starting",
        endpoint=AWS_ENDPOINT_URL,
        queue=SQS_QUEUE_NAME,
        collection=COLLECTION,
        idle_timeout=IDLE_TIMEOUT_SEC,
    )

    sqs = boto3.client("sqs", endpoint_url=AWS_ENDPOINT_URL)
    queue_url = _resolve_queue_url(sqs)
    _log("queue_resolved", queue_url=queue_url)

    last_message_at = time.time()
    processed = 0
    failed = 0

    while True:
        # Long-polling: receive bloqueia até MaxNumberOfMessages chegarem
        # OU WaitTimeSeconds expirarem (vazio = retorna lista vazia).
        response = sqs.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=POLL_WAIT_SECONDS,
            VisibilityTimeout=VISIBILITY_TIMEOUT,
        )
        messages = response.get("Messages", [])

        if not messages:
            idle_for = time.time() - last_message_at
            if IDLE_TIMEOUT_SEC > 0 and idle_for >= IDLE_TIMEOUT_SEC:
                _log(
                    "idle_timeout_exit",
                    idle_seconds=int(idle_for),
                    processed=processed,
                    failed=failed,
                )
                break
            continue

        for msg in messages:
            receipt = msg["ReceiptHandle"]
            try:
                body_preview = json.loads(msg["Body"]).get("pdf_filename", "?")
            except Exception:
                body_preview = "?"

            _log("message_received", pdf=body_preview)

            try:
                result = _process_message(msg)
                sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt)
                processed += 1
                _log(
                    "message_done",
                    pdf=result["source_file"],
                    chunks=result["chunks_inserted"],
                    embedding_tokens=result.get("embedding_tokens", 0),
                    duration_ms=result["duration_ms"],
                )
                emit_metric("pdf_processed_success", 1)
                emit_metric("pdf_processing_duration_ms", result["duration_ms"], unit="Milliseconds")
                emit_metric("chunks_inserted", result["chunks_inserted"])
                emit_metric("embedding_tokens_consumed", result.get("embedding_tokens", 0))
            except Exception as exc:
                failed += 1
                _log(
                    "message_failed",
                    pdf=body_preview,
                    error=f"{type(exc).__name__}: {exc}",
                )
                emit_metric("pdf_processed_error", 1)
                # Não deleta — mensagem volta pra fila após visibility timeout.
                # DLQ (§4.5) capturará após N tentativas.

            last_message_at = time.time()


if __name__ == "__main__":
    main()
