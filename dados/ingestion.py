"""Funções de ingestão por-PDF, reutilizáveis tanto pelo pipeline sequencial
quanto pelo pipeline paralelo (workers locais ou EC2 via SQS).

Cada função opera sobre 1 PDF (ou seu intermediário) e retorna dados em
memória. Scripts 01-05 são thin wrappers que adicionam I/O em disco; o
pipeline_parallel.py encadeia as funções em memória, escrevendo só no
ChromaDB no final.
"""

import re
from pathlib import Path
from typing import Optional

import chromadb
import ollama
import pdfplumber
from langchain_text_splitters import RecursiveCharacterTextSplitter


# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

SECTION_MAP = {
    "section_a": "general_provisions",
    "section_b": "sporting",
    "section_c": "technical",
    "section_d": "financial_f1_teams",
    "section_e": "financial_pu_manufacturers",
    "section_f": "operational",
}

# Validação
MIN_CHARS_PER_PAGE = 100
WARN_EMPTY_RATIO = 0.10

# Chunking
CHUNK_SEPARATORS = ["\n\n", "\n", ". ", " ", ""]
BEST_CHUNK_CONFIG = {"chunk_size": 512, "chunk_overlap": 64}

# Embedding
EMBED_MODEL = "nomic-embed-text"
EMBED_BATCH_SIZE = 32
MIN_CHUNK_CHARS = 30  # ignora chunks muito curtos (marcadores de página)


# ---------------------------------------------------------------------------
# Passo 1 — Extração
# ---------------------------------------------------------------------------

def detect_section(filename: str) -> str:
    for key, label in SECTION_MAP.items():
        if key in filename:
            return label
    return "unknown"


def extract_pdf(pdf_path: Path) -> dict:
    """Extrai texto por página de um PDF. Saída pronta para validate_data()."""
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            pages.append({
                "page": i,
                "text": text,
                "char_count": len(text),
            })

    return {
        "source_file": pdf_path.name,
        "section": detect_section(pdf_path.name),
        "total_pages": len(pages),
        "pages": pages,
    }


# ---------------------------------------------------------------------------
# Passo 2 — Validação
# ---------------------------------------------------------------------------

def validate_data(data: dict) -> dict:
    """Valida cobertura/densidade do texto extraído de 1 PDF.
    Retorna dict com flag ok, stats e lista de issues — não levanta exceção."""
    issues = []
    pages = data.get("pages", [])
    total = data.get("total_pages", 0)

    if not pages:
        return {
            "source_file": data.get("source_file", "?"),
            "ok": False,
            "issues": ["ERRO: nenhuma página encontrada no JSON."],
            "stats": {},
        }

    empty_pages = [p["page"] for p in pages if p["char_count"] == 0]
    sparse_pages = [p["page"] for p in pages if 0 < p["char_count"] < MIN_CHARS_PER_PAGE]
    total_chars = sum(p["char_count"] for p in pages)
    avg_chars = total_chars / total if total else 0

    if len(empty_pages) / total > WARN_EMPTY_RATIO:
        issues.append(
            f"AVISO: {len(empty_pages)} páginas vazias ({len(empty_pages)/total:.0%}) → {empty_pages[:10]}"
        )
    if sparse_pages:
        issues.append(
            f"AVISO: {len(sparse_pages)} páginas esparsas (<{MIN_CHARS_PER_PAGE} chars) → {sparse_pages[:10]}"
        )
    if avg_chars < 200:
        issues.append(f"AVISO: média muito baixa de {avg_chars:.0f} chars/página — possível PDF escaneado.")

    stats = {
        "total_pages": total,
        "empty_pages": len(empty_pages),
        "sparse_pages": len(sparse_pages),
        "total_chars": total_chars,
        "avg_chars_page": round(avg_chars, 1),
    }
    return {
        "source_file": data.get("source_file", "?"),
        "ok": len(issues) == 0,
        "issues": issues,
        "stats": stats,
    }


# ---------------------------------------------------------------------------
# Passo 3 — Pré-processamento
# ---------------------------------------------------------------------------

def _clean_text(text: str) -> str:
    """Remove artefatos comuns de extração de PDF."""
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = re.sub(r"-\n(\w)", r"\1", text)
    text = re.sub(r"(?m)^\s*\d{1,3}\s*$", "", text)
    text = re.sub(r"(?m)^[\s.\-_]{5,}$", "", text)
    text = re.sub(r"[^\x20-\x7eÀ-ɏ -⁯℀-⅏°µ]", " ", text)
    return text


def _normalize_text(text: str) -> str:
    """Normaliza espaços, linhas e formatação geral."""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"(?m)^ +| +$", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"([a-z\)\.])(\d+\.\d+)", r"\1\n\2", text)
    return text.strip()


def preprocess_data(data: dict) -> dict:
    """Aplica limpeza + normalização página a página."""
    processed_pages = []
    for page in data["pages"]:
        raw = page["text"]
        cleaned = _clean_text(raw)
        normalized = _normalize_text(cleaned)
        processed_pages.append({
            "page": page["page"],
            "text": normalized,
            "char_count_raw": page["char_count"],
            "char_count_clean": len(normalized),
        })

    return {
        "source_file": data["source_file"],
        "section": data["section"],
        "total_pages": data["total_pages"],
        "pages": processed_pages,
    }


# ---------------------------------------------------------------------------
# Passo 4 — Chunking
# ---------------------------------------------------------------------------

def build_full_text(data: dict) -> str:
    parts = []
    for page in data["pages"]:
        text = page["text"].strip()
        if text:
            parts.append(f"[Página {page['page']}]\n{text}")
    return "\n\n".join(parts)


def chunk_data(data: dict, chunk_size: Optional[int] = None,
               chunk_overlap: Optional[int] = None) -> dict:
    """Divide o texto pré-processado em chunks. Defaults vêm de BEST_CHUNK_CONFIG."""
    cs = chunk_size or BEST_CHUNK_CONFIG["chunk_size"]
    co = chunk_overlap or BEST_CHUNK_CONFIG["chunk_overlap"]

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=cs,
        chunk_overlap=co,
        separators=CHUNK_SEPARATORS,
        length_function=len,
    )

    full_text = build_full_text(data)
    chunks = splitter.split_text(full_text)

    return {
        "source_file": data["source_file"],
        "section": data["section"],
        "chunk_config": {"chunk_size": cs, "chunk_overlap": co},
        "total_chunks": len(chunks),
        "chunks": [
            {"id": i, "text": chunk, "char_count": len(chunk)}
            for i, chunk in enumerate(chunks)
        ],
    }


# ---------------------------------------------------------------------------
# Passo 5 — Embedding + Ingestão
# ---------------------------------------------------------------------------

def _embed_batch(texts: list[str]) -> list[list[float]]:
    response = ollama.embed(model=EMBED_MODEL, input=texts)
    return response["embeddings"]


def build_chunks_for_ingest(chunks_data: dict) -> list[dict]:
    """Filtra chunks por tamanho mínimo e formata para ChromaDB."""
    stem = Path(chunks_data["source_file"]).stem
    source = chunks_data["source_file"]
    section = chunks_data["section"]

    return [
        {
            "uid": f"{stem}_chunks_{c['id']}",
            "text": c["text"],
            "metadata": {
                "source_file": source,
                "section": section,
                "chunk_id": c["id"],
                "char_count": c["char_count"],
            },
        }
        for c in chunks_data["chunks"]
        if c["char_count"] >= MIN_CHUNK_CHARS
    ]


def ingest_chunks(collection, chunks: list[dict]) -> int:
    """Ingere chunks no ChromaDB em batches. Retorna total inserido."""
    inserted = 0
    for i in range(0, len(chunks), EMBED_BATCH_SIZE):
        batch = chunks[i : i + EMBED_BATCH_SIZE]
        texts = [c["text"] for c in batch]
        ids = [c["uid"] for c in batch]
        metadatas = [c["metadata"] for c in batch]

        embeddings = _embed_batch(texts)

        collection.add(
            ids=ids,
            documents=texts,
            embeddings=embeddings,
            metadatas=metadatas,
        )
        inserted += len(batch)

    return inserted


# ---------------------------------------------------------------------------
# Orquestrador por-PDF (usado pelo pipeline paralelo)
# ---------------------------------------------------------------------------

def process_single_pdf(
    pdf_path: Path,
    vectorstore_path: Path,
    collection_name: str,
) -> dict:
    """Executa os 5 passos para 1 PDF, em memória, escrevendo só no ChromaDB.

    Cada chamada abre seu próprio cliente Chroma (objetos não são picklables
    entre processos do ProcessPoolExecutor). A collection deve ter sido
    criada previamente pelo orquestrador.
    """
    extracted = extract_pdf(pdf_path)
    validation = validate_data(extracted)
    processed = preprocess_data(extracted)
    chunked = chunk_data(processed)
    chunks_for_ingest = build_chunks_for_ingest(chunked)

    client = chromadb.PersistentClient(path=str(vectorstore_path))
    collection = client.get_collection(collection_name)
    inserted = ingest_chunks(collection, chunks_for_ingest)

    return {
        "source_file": extracted["source_file"],
        "section": extracted["section"],
        "total_pages": extracted["total_pages"],
        "total_chunks": chunked["total_chunks"],
        "chunks_inserted": inserted,
        "validation_ok": validation["ok"],
        "validation_issues": validation["issues"],
    }
