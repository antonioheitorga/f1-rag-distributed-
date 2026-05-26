"""
DLQ Inspector — ferramenta de debug post-mortem da Dead Letter Queue.

Lista as mensagens que foram movidas automaticamente do `ingestion-jobs`
para o `ingestion-jobs-dlq` após exceder o maxReceiveCount. Não consome
as mensagens (usa peek via receive + visibility=0 quando necessário).

Uso:
    python infra/dlq_inspector.py              # listar mensagens
    python infra/dlq_inspector.py --purge      # apagar tudo da DLQ
    python infra/dlq_inspector.py --count      # só a contagem aproximada
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import boto3  # noqa: E402

from config import AWS_ENDPOINT_URL, SQS_DLQ_NAME  # noqa: E402


def _resolve_dlq(sqs) -> str:
    """Localiza a URL da DLQ — assume que o producer já a criou."""
    existing = sqs.list_queues(QueueNamePrefix=SQS_DLQ_NAME).get("QueueUrls", [])
    for url in existing:
        if url.endswith(f"/{SQS_DLQ_NAME}"):
            return url
    raise RuntimeError(
        f"DLQ '{SQS_DLQ_NAME}' não encontrada em {AWS_ENDPOINT_URL}. "
        "Rode o producer primeiro para criar as filas."
    )


def _approx_count(sqs, queue_url: str) -> int:
    attrs = sqs.get_queue_attributes(
        QueueUrl=queue_url,
        AttributeNames=["ApproximateNumberOfMessages"],
    )
    return int(attrs["Attributes"]["ApproximateNumberOfMessages"])


def _peek_messages(sqs, queue_url: str, max_total: int = 50) -> list[dict]:
    """Lê mensagens sem deletá-las (visibility=0 devolve imediatamente).
    Repete até esvaziar buffer (até max_total)."""
    collected = []
    seen_ids = set()
    while len(collected) < max_total:
        response = sqs.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=10,
            WaitTimeSeconds=1,
            VisibilityTimeout=0,  # devolve imediatamente — não consome
            AttributeNames=["All"],
        )
        batch = response.get("Messages", [])
        new = [m for m in batch if m["MessageId"] not in seen_ids]
        if not new:
            break
        collected.extend(new)
        for m in new:
            seen_ids.add(m["MessageId"])
    return collected


def cmd_list(sqs, queue_url: str) -> None:
    count = _approx_count(sqs, queue_url)
    print(f"DLQ: {SQS_DLQ_NAME}")
    print(f"Mensagens (aproximado): {count}\n")

    if count == 0:
        print("DLQ vazia — nenhum job falhou além do limite.")
        return

    messages = _peek_messages(sqs, queue_url)
    if not messages:
        print("Contagem indica mensagens, mas receive não retornou. Tente novamente.")
        return

    print(f"--- {len(messages)} mensagens inspecionadas ---\n")
    for i, msg in enumerate(messages, start=1):
        attrs = msg.get("Attributes", {})
        try:
            body = json.loads(msg["Body"])
            pdf = body.get("pdf_filename", "?")
            submitted = body.get("submitted_at", "?")
        except json.JSONDecodeError:
            pdf = "(body não é JSON)"
            submitted = "?"

        receive_count = attrs.get("ApproximateReceiveCount", "?")
        first_received = attrs.get("ApproximateFirstReceiveTimestamp", "?")
        sent_ts = attrs.get("SentTimestamp", "?")

        print(f"[{i}] MessageId: {msg['MessageId']}")
        print(f"    PDF              : {pdf}")
        print(f"    submitted_at     : {submitted}")
        print(f"    ApproximateReceiveCount        : {receive_count}")
        print(f"    ApproximateFirstReceiveTimestamp: {first_received}")
        print(f"    SentTimestamp                   : {sent_ts}")
        print()


def cmd_purge(sqs, queue_url: str) -> None:
    sqs.purge_queue(QueueUrl=queue_url)
    print(f"DLQ '{SQS_DLQ_NAME}' purgada. Pode levar até 60s para refletir.")


def cmd_count(sqs, queue_url: str) -> None:
    print(_approx_count(sqs, queue_url))


def main():
    parser = argparse.ArgumentParser(description="Inspeciona a DLQ do SQS.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--purge", action="store_true", help="Apaga todas as mensagens da DLQ.")
    group.add_argument("--count", action="store_true", help="Mostra só a contagem aproximada.")
    args = parser.parse_args()

    sqs = boto3.client("sqs", endpoint_url=AWS_ENDPOINT_URL)
    queue_url = _resolve_dlq(sqs)

    if args.purge:
        cmd_purge(sqs, queue_url)
    elif args.count:
        cmd_count(sqs, queue_url)
    else:
        cmd_list(sqs, queue_url)


if __name__ == "__main__":
    main()
