"""
03_preprocess.py
Pré-processa os textos extraídos:
  - Limpeza: remove caracteres inválidos, ruídos e artefatos de PDF
  - Normalização: padroniza espaços, quebras de linha e formatação
Salva os resultados em processed/ como JSON.

Wrapper sequencial sobre dados/ingestion.py::preprocess_data().
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from dados.ingestion import preprocess_data  # noqa: E402

EXTRACTED_DIR = Path(__file__).parent.parent / "extracted"
PROCESSED_DIR = Path(__file__).parent.parent / "processed"
PROCESSED_DIR.mkdir(exist_ok=True)


def main():
    jsons = sorted(EXTRACTED_DIR.glob("*.json"))
    if not jsons:
        print("Nenhum JSON encontrado em extracted/. Execute 01_extract.py primeiro.")
        return

    print(f"Pré-processando {len(jsons)} arquivo(s)...\n")
    for jp in jsons:
        print(f"Processando: {jp.name} ...", end=" ")
        with open(jp, encoding="utf-8") as f:
            data = json.load(f)
        result = preprocess_data(data)
        out_path = PROCESSED_DIR / jp.name
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        raw_total = sum(p["char_count_raw"] for p in result["pages"])
        clean_total = sum(p["char_count_clean"] for p in result["pages"])
        reduction = (1 - clean_total / raw_total) * 100 if raw_total else 0
        print(f"OK — redução de {reduction:.1f}% ({raw_total:,} → {clean_total:,} chars)")

    print(f"\nPré-processamento concluído. Arquivos salvos em: {PROCESSED_DIR}")


if __name__ == "__main__":
    main()
