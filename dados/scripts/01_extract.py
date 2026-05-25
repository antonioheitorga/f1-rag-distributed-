"""
01_extract.py
Extrai texto de todos os PDFs do corpus usando pdfplumber.
Salva cada PDF como um JSON em extracted/ com metadados por página.

Wrapper sequencial sobre dados/ingestion.py::extract_pdf().
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from dados.ingestion import extract_pdf  # noqa: E402

CORPUS_DIR = Path(__file__).parent.parent / "corpus"
OUTPUT_DIR = Path(__file__).parent.parent / "extracted"
OUTPUT_DIR.mkdir(exist_ok=True)


def main():
    pdfs = sorted(CORPUS_DIR.glob("*.pdf"))
    if not pdfs:
        print("Nenhum PDF encontrado em corpus/")
        return

    print(f"Encontrados {len(pdfs)} PDFs para extração.\n")
    for pdf_path in pdfs:
        print(f"Extraindo: {pdf_path.name} ...", end=" ")
        data = extract_pdf(pdf_path)
        out_path = OUTPUT_DIR / (pdf_path.stem + ".json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        total_chars = sum(p["char_count"] for p in data["pages"])
        print(f"OK — {data['total_pages']} páginas, {total_chars:,} caracteres → {out_path.name}")

    print(f"\nExtração concluída. Arquivos salvos em: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
