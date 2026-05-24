"""Política de retry compartilhada entre os agentes.

Aplicada em chamadas a serviços externos (Ollama, Tavily) que podem
falhar transientemente. Backoff exponencial com tetos curtos — falhas
permanentes ainda quebram rapidamente.
"""

import logging

from tenacity import (
    before_sleep_log,
    retry,
    stop_after_attempt,
    wait_exponential,
)


logger = logging.getLogger("f1rag.retry")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(name)s] %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)


external_call_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
