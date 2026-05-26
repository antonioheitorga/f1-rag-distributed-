"""
06_verify.py
Verifica a integridade do ChromaDB após a ingestão.
  - Exibe estatísticas da collection (total, distribuição por seção)
  - Executa consultas de teste para validar busca semântica
  - Confirma que embeddings e metadados estão corretos
"""

import sys
from pathlib import Path

# Adiciona raiz do projeto ao path para encontrar config.py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import ollama  # noqa: E402
import chromadb  # noqa: E402
from collections import Counter  # noqa: E402

from config import CHROMA_COLLECTION, EMBED_MODEL  # noqa: E402

VECTORSTORE = Path(__file__).parent.parent / "vectorstore"
COLLECTION = CHROMA_COLLECTION

# Consultas de teste representativas do domínio FIA
TEST_QUERIES = [
    "What are the rules for car weight and ballast?",
    "How many points does the winner of a race receive?",
    "What is the maximum budget cap for F1 teams?",
    "Rules regarding the power unit and energy recovery system",
    "Pit stop procedures and safety car regulations",
]


def get_query_embedding(text: str) -> list[float]:
    response = ollama.embed(model=EMBED_MODEL, input=[text])
    return response["embeddings"][0]


def print_section(title: str):
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")


def main():
    # 1. Conecta ao ChromaDB
    if not VECTORSTORE.exists():
        print("ERRO: vectorstore/ não encontrado. Execute pipeline.py ou 05_embed_ingest.py.")
        return

    client = chromadb.PersistentClient(path=str(VECTORSTORE))
    collections = [c.name for c in client.list_collections()]

    if COLLECTION not in collections:
        print(f"ERRO: collection '{COLLECTION}' não encontrada.")
        return

    collection = client.get_collection(COLLECTION)

    # 2. Estatísticas gerais
    print_section("Estatísticas do Vector Store")
    total = collection.count()
    print(f"  Collection  : {COLLECTION}")
    print(f"  Total docs  : {total:,}")
    print(f"  Embed model : {EMBED_MODEL}")
    print(f"  Localização : {VECTORSTORE}")

    # 3. Distribuição por seção — percorre em batches para não carregar embeddings
    section_counts: Counter = Counter()
    batch = 500
    for offset in range(0, total, batch):
        chunk = collection.get(limit=batch, offset=offset, include=["metadatas"])
        section_counts.update(m["section"] for m in chunk["metadatas"])

    print_section("Distribuição por Seção (amostra)")
    for section, count in sorted(section_counts.items()):
        bar = "█" * (count // 10)
        print(f"  {section:<35} {count:>5}  {bar}")

    # 4. Exemplo de metadados
    print_section("Exemplo de Documento Indexado")
    sample1 = collection.get(limit=1, include=["documents", "metadatas"])
    if sample1["ids"]:
        print(f"  ID       : {sample1['ids'][0]}")
        print(f"  Metadados: {sample1['metadatas'][0]}")
        snippet = sample1["documents"][0][:200].replace("\n", " ")
        print(f"  Texto    : {snippet}...")

    # 5. Consultas de teste semântico
    print_section("Testes de Busca Semântica (top-3 por consulta)")
    for query in TEST_QUERIES:
        embedding = get_query_embedding(query)
        results = collection.query(
            query_embeddings=[embedding],
            n_results=3,
            include=["documents", "metadatas", "distances"],
        )
        print(f"\n  Q: \"{query}\"")
        for i, (doc, meta, dist) in enumerate(zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        )):
            snippet = doc[:120].replace("\n", " ")
            score = 1 - dist  # cosine similarity (0→1, maior = mais relevante)
            print(f"    [{i+1}] score={score:.3f} | [{meta['section']}] pág.{meta.get('chunk_id','?')} | {snippet}...")

    # 6. Resultado final
    print(f"\n{'='*60}")
    checks = [
        total > 0,
        len(section_counts) == 6,
        len(TEST_QUERIES) > 0,
    ]
    if all(checks):
        print("  Vector store OK — pipeline de ingestão totalmente concluída.")
    else:
        print("  AVISO: alguns checks falharam — revise os itens acima.")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
