"""
Cliente CloudWatch — wrapper sobre boto3 para emissão de métricas.

Princípios:
- Observabilidade nunca quebra produção. Erros de emissão são logados
  mas não propagados (try/except silencioso com log warning).
- WorkerId é injetado automaticamente como dimensão (hostname + pid) —
  permite filtrar métricas por worker no dashboard.
- Namespace fixo: F1RagHarness.

Uso:
    from infra.metrics import emit_metric

    emit_metric("pdf_processed_success", 1)
    emit_metric("pdf_processing_duration_ms", 12345, unit="Milliseconds")
    emit_metric("chunks_inserted", 777, dimensions={"Section": "sporting"})
"""

import logging
import os
import socket
from typing import Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError


NAMESPACE = os.getenv("CLOUDWATCH_NAMESPACE", "F1RagHarness")
AWS_ENDPOINT_URL = os.getenv("AWS_ENDPOINT_URL", "http://localhost:4566")
WORKER_ID = f"{socket.gethostname()}#{os.getpid()}"

logger = logging.getLogger("f1rag.metrics")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(name)s] %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)


# Cliente lazy — instanciado na primeira chamada e reutilizado.
_client = None


def _get_client():
    global _client
    if _client is None:
        _client = boto3.client("cloudwatch", endpoint_url=AWS_ENDPOINT_URL)
    return _client


def emit_metric(
    name: str,
    value: float,
    unit: str = "Count",
    dimensions: Optional[dict] = None,
) -> None:
    """Emite uma métrica no CloudWatch. WorkerId é adicionado automaticamente.

    Falhas de rede ou serviço são logadas mas não propagadas — métricas
    são best-effort, não devem bloquear o fluxo principal.
    """
    dims = [{"Name": "WorkerId", "Value": WORKER_ID}]
    if dimensions:
        for k, v in dimensions.items():
            dims.append({"Name": k, "Value": str(v)})

    try:
        _get_client().put_metric_data(
            Namespace=NAMESPACE,
            MetricData=[{
                "MetricName": name,
                "Value": float(value),
                "Unit": unit,
                "Dimensions": dims,
            }],
        )
    except (BotoCoreError, ClientError, Exception) as exc:
        logger.warning(
            f"emit_metric failed: name={name} error={type(exc).__name__}: {exc}"
        )
