"""
02_validate.py
Valida os JSONs extraídos em extracted/.
Verifica: cobertura de páginas, páginas vazias, densidade de texto e consistência.

Wrapper sequencial sobre dados/ingestion.py::validate_data().
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from dados.ingestion import MIN_CHARS_PER_PAGE, validate_data  # noqa: E402

EXTRACTED_DIR = Path(__file__).parent.parent / "extracted"


def main():
    jsons = sorted(EXTRACTED_DIR.glob("*.json"))
    if not jsons:
        print("Nenhum JSON encontrado em extracted/. Execute 01_extract.py primeiro.")
        return

    print(f"Validando {len(jsons)} arquivo(s) extraídos...\n")
    print(f"(limiar de página esparsa: {MIN_CHARS_PER_PAGE} chars)\n")
    all_ok = True
    for jp in jsons:
        with open(jp, encoding="utf-8") as f:
            data = json.load(f)
        result = validate_data(data)
        status = "OK" if result["ok"] else "PROBLEMA"
        s = result["stats"]
        print(f"[{status}] {jp.name}")
        print(f"       Páginas: {s.get('total_pages')} | "
              f"Vazias: {s.get('empty_pages')} | "
              f"Esparsas: {s.get('sparse_pages')} | "
              f"Total chars: {s.get('total_chars', 0):,} | "
              f"Média/pág: {s.get('avg_chars_page')}")
        for issue in result["issues"]:
            print(f"       → {issue}")
            all_ok = False
        print()

    if all_ok:
        print("Validação concluída sem problemas.")
    else:
        print("Validação concluída com avisos — revise os itens acima.")


if __name__ == "__main__":
    main()
