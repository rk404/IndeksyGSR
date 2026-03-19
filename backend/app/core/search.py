"""
search.py — Wyszukiwanie semantyczne indeksów (BGE-M3 + Qdrant hybrid).

Użycie jako moduł:
    from app.core.search import search
    results = search("śruby M20 ocynkowane ogniowo", top_k=10)
    results = search("śruby M20 ocynkowane ogniowo", rerank=True)

Użycie CLI:
    python search.py "śruby M20 ocynkowane ogniowo"
    python search.py "kołnierz DN65 stal" --top-k 5 --rerank
"""

from __future__ import annotations

import argparse
import re
from functools import lru_cache

from qdrant_client import QdrantClient, models
from app.services.embedding_client import EmbeddingModel, EmbeddingReranker

COLLECTION_NAME = "indeksy"
QUERY_INSTRUCTION = (
    "Represent this sentence for searching relevant passages: "
)

# Wzorce kodów technicznych do normalizacji na uppercase
_TECH_CODE_RE = re.compile(
    r"\b("
    r"m\d+(?:[.,x]\d+)*|dn\d+|pn\d+|s\d{3,}|"
    r"en\d+|din\d+|iso\d+|g\d+(?:[/]\d+)?"
    r")\b",
    flags=re.IGNORECASE,
)

# Słownik synonimów: fraza (lowercase) → token normalizacyjny
_SYNONYMS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bocynkowana?\s+ogniowo\b", re.IGNORECASE), "OGNIOWO"),
    (re.compile(r"\bocynk(?:owana?)?\s+elektrolityczn(?:ie|a)?\b", re.IGNORECASE), "ELEKTROLITYCZNIE"),
    (re.compile(r"\bnierdzewna?\b", re.IGNORECASE), "A2"),
    (re.compile(r"\binox\b", re.IGNORECASE), "A2"),
    (re.compile(r"\bkwasoodporna?\b", re.IGNORECASE), "A4"),
]


# ──────────────────────────────────────────
# Normalizacja zapytania
# ──────────────────────────────────────────

def normalize_query(query: str) -> str:
    """Normalizuje kody techniczne i synonimy materiałowe w zapytaniu."""
    for pattern, replacement in _SYNONYMS:
        query = pattern.sub(replacement, query)
    return _TECH_CODE_RE.sub(lambda m: m.group().upper(), query)


# ──────────────────────────────────────────
# Singletony (lazy, cache)
# ──────────────────────────────────────────

@lru_cache(maxsize=1)
def _get_model() -> EmbeddingModel:
    return EmbeddingModel()


@lru_cache(maxsize=1)
def _get_reranker() -> EmbeddingReranker:
    return EmbeddingReranker()


@lru_cache(maxsize=1)
def _get_qdrant() -> QdrantClient:
    from app.services.qdrant import get_client
    return get_client()


@lru_cache(maxsize=1)
def _load_scrape_map() -> dict[str, dict]:
    """Ładuje dane scrapingu z Firestore (indeks → {title, specifications}).
    Cache — ładuje raz na czas życia procesu."""
    from app.services.firestore import get_client as get_db
    db = get_db()
    result = {}
    for doc in db.collection("product_scrapes").where("status", "==", "ok").stream():
        d = doc.to_dict()
        indeks = d.get("indeks") or doc.id
        result[indeks] = {
            "title": d.get("title", ""),
            "specifications": d.get("specifications", {}),
        }
    return result


def _build_rerank_text(candidate: dict, scrape_map: dict) -> str:
    """Buduje wzbogacony tekst dla cross-encodera."""
    parts = [candidate["nazwa"], candidate["jdmr_nazwa"]]
    scraped = scrape_map.get(candidate["indeks"], {})
    if scraped.get("title"):
        parts.append(scraped["title"])
    if scraped.get("specifications"):
        specs = " ".join(
            f"{k}: {v}"
            for k, v in list(scraped["specifications"].items())[:5]
        )
        parts.append(specs)
    return " | ".join(filter(None, parts))


def get_model():
    """Zwraca załadowany model BGE-M3 (singleton)."""
    return _get_model()


def get_reranker():
    """Zwraca załadowany reranker BGE-reranker-v2-m3 (singleton)."""
    return _get_reranker()


# ──────────────────────────────────────────
# Wyszukiwanie
# ──────────────────────────────────────────

def _lexical_to_sparse(weights: dict) -> models.SparseVector:
    if not weights:
        return models.SparseVector(indices=[], values=[])
    items = sorted(weights.items())
    return models.SparseVector(
        indices=[int(k) for k, _ in items],
        values=[float(v) for _, v in items],
    )


def search(
    query: str,
    top_k: int = 10,
    rerank: bool = False,
) -> list[dict]:
    """
    Wyszukuje indeksy materiałowe pasujące do zapytania.

    Args:
        query:   Opis produktu, np. "śruby M20 ocynkowane ogniowo"
        top_k:   Liczba wyników do zwrócenia
        rerank:  Czy zastosować cross-encoder reranking

    Returns:
        Lista [{indeks, nazwa, komb_id, jdmr_nazwa, score}]
        posortowana malejąco według score.
    """
    model = _get_model()
    qdrant = _get_qdrant()

    query = normalize_query(query)
    output = model.encode(
        [QUERY_INSTRUCTION + query],
        return_dense=True,
        return_sparse=True,
        return_colbert_vecs=False,
    )
    query_dense = output["dense_vecs"][0].tolist()
    query_sparse = _lexical_to_sparse(output["lexical_weights"][0])

    fetch_limit = top_k * 5 if rerank else top_k
    results = qdrant.query_points(
        collection_name=COLLECTION_NAME,
        prefetch=[
            models.Prefetch(
                query=query_sparse,
                using="sparse",
                limit=fetch_limit * 3,
            ),
            models.Prefetch(
                query=query_dense,
                using="dense",
                limit=fetch_limit * 3,
            ),
        ],
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        limit=fetch_limit,
        with_payload=True,
    )

    candidates = [
        {
            "qdrant_id":  p.id,                          # ← dodaj tę linię
            "indeks":     p.payload.get("indeks", ""),
            "nazwa":      p.payload.get("nazwa", ""),
            "komb_id":    p.payload.get("komb_id", ""),
            "jdmr_nazwa": p.payload.get("jdmr_nazwa", ""),
            "score":      round(p.score, 4),
        }
        for p in results.points
    ]    

    if rerank and candidates:
        reranker = _get_reranker()
        scrape_map = _load_scrape_map()
        pairs = [
            (query, _build_rerank_text(c, scrape_map))
            for c in candidates
        ]
        scores = reranker.compute_score(pairs)
        if hasattr(scores, "tolist"):
            scores = scores.tolist()
        for c, s in zip(candidates, scores):
            c["score"] = round(float(s), 4)
        candidates.sort(key=lambda x: x["score"], reverse=True)
        candidates = candidates[:top_k]

    return candidates


# ──────────────────────────────────────────
# CLI
# ──────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Wyszukiwanie semantyczne indeksów materiałowych"
    )
    ap.add_argument(
        "query",
        help="Opis produktu, np. 'śruby M20 ocynkowane ogniowo'",
    )
    ap.add_argument(
        "--top-k", type=int, default=10,
        help="Liczba wyników (domyślnie 10)",
    )
    ap.add_argument(
        "--rerank", action="store_true",
        help="Cross-encoder reranking",
    )
    args = ap.parse_args()

    print(f"\nZapytanie: \"{args.query}\"\n")
    results = search(args.query, top_k=args.top_k, rerank=args.rerank)

    if not results:
        print("Brak wyników.")
        return

    col_w = max(len(r["indeks"]) for r in results)
    print(f"{'#':<3}  {'SCORE':<7}  {'INDEKS':<{col_w}}  NAZWA")
    print("-" * (3 + 2 + 7 + 2 + col_w + 2 + 60))
    for i, r in enumerate(results, 1):
        nazwa = r["nazwa"][:60]
        indeks = r["indeks"]
        print(f"{i:<3}  {r['score']:<7}  {indeks:<{col_w}}  {nazwa}")
    print()


if __name__ == "__main__":
    main()
