"""Helper para carregar system prompts dos agentes a partir de arquivos .md.

Cada prompt vive em prompts/{name}.md e é carregado em runtime via
load_prompt(name). Cache simples evita releitura a cada chamada.
"""

from functools import lru_cache
from pathlib import Path


PROMPTS_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    """Carrega o prompt de prompts/{name}.md.

    O arquivo é lido apenas uma vez por processo (lru_cache). Para
    invalidar o cache em runtime (ex: testes), use load_prompt.cache_clear().
    """
    prompt_file = PROMPTS_DIR / f"{name}.md"
    if not prompt_file.exists():
        raise FileNotFoundError(
            f"Prompt '{name}' não encontrado em {prompt_file}."
        )
    return prompt_file.read_text(encoding="utf-8").strip()
