# Plan: Usprawnienia wyszukiwania

Zbiór potencjalnych usprawnień jakości wyszukiwania — do wdrożenia w przyszłości.

---

## 1. Wzbogacenie tekstu dla cross-encodera o dane scrapingu

**Obecny stan:**
Cross-encoder (`BGE-reranker-v2-m3`) w `search.py` reankuje pary `(query, nazwa + jdmr_nazwa)`.

**Propozycja:**
Przekazać do cross-encodera bogatszy tekst: `nazwa + scraped_title + specs` (z Firestore `product_scrapes`).

```python
# Obecne (search.py):
pairs = [(query, r["nazwa"] + " " + r["jdmr_nazwa"]) for r in candidates]

# Proponowane:
pairs = [(query, _build_rerank_text(r, scrape_map)) for r in candidates]

def _build_rerank_text(result: dict, scrape_map: dict) -> str:
    parts = [result["nazwa"], result["jdmr_nazwa"]]
    scraped = scrape_map.get(result["indeks"], {})
    if scraped.get("title"):
        parts.append(scraped["title"])
    if scraped.get("specifications"):
        specs = " ".join(f"{k}: {v}" for k, v in list(scraped["specifications"].items())[:5])
        parts.append(specs)
    return " | ".join(filter(None, parts))
```

**Wymagane zmiany:**
- `backend/app/core/search.py` — załadować `scrape_map` z Firestore (tylko gdy `rerank=True`), wzbogacić tekst par dla cross-encodera
- Opcjonalnie: cache `scrape_map` przez `lru_cache` lub przekazywać jako parametr

**Oczekiwany efekt:** Realer poprawa jakości rankingu dla ~8k indeksów ze scrapingiem.

**Koszt:** Brak — Firestore i cross-encoder już w użyciu.

---

## 2. Normalizacja techniczna zapytań — rozszerzenie

**Kontekst:**
`normalize_query()` w `search.py` obsługuje: `M\d+`, `DN\d+`, `PN\d+`, `S\d{3+}`, `EN\d+`, `DIN\d+`, `ISO\d+`, `G\d+`.

**Propozycja:**
Dodać synonim-mapping dla popularnych opisów → kody:
- "ocynkowana ogniowo" → "OGNIOWO"
- "nierdzewna" / "inox" → "A2" / "A4"
- "ocynkowana elektrolitycznie" → "ELEKTROLITYCZNIE"

**Wymagane zmiany:**
- `backend/app/core/search.py` — słownik synonimów stosowany przed/po `normalize_query()`

---

## 3. Long-running embedding service (własny FastAPI)

**Problem:**
Każde uruchomienie `vectorize` lub `dashboard` ładuje BGE-M3 od nowa — 30-60 min importów przy pierwszym uruchomieniu po zmianie pakietów.

**Propozycja:**
Wydzielić BGE-M3 i BGE-reranker do osobnego serwisu FastAPI który ładuje modele raz i przyjmuje zadania przez HTTP.

**Architektura:**
```
vectorize / dashboard / search.py
    ↓ HTTP (localhost:8080)
backend/app/services/embedding_service.py  ← nowy serwis
    ├── BGE-M3       → POST /encode  (dense + sparse)
    └── BGE-reranker → POST /rerank
```

**Nowy plik: `backend/app/services/embedding_service.py`**
```python
# Startuje raz, model ładuje się przy starcie serwisu
from fastapi import FastAPI
from FlagEmbedding import BGEM3FlagModel, FlagReranker

app = FastAPI()
_model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=True)
_reranker = FlagReranker("BAAI/bge-reranker-v2-m3", use_fp16=True)

@app.post("/encode")
def encode(texts: list[str], return_sparse: bool = True):
    out = _model.encode(texts, return_dense=True, return_sparse=return_sparse)
    return {"dense_vecs": out["dense_vecs"].tolist(),
            "lexical_weights": out["lexical_weights"]}

@app.post("/rerank")
def rerank(query: str, passages: list[str]):
    scores = _reranker.compute_score([(query, p) for p in passages], normalize=True)
    return {"scores": scores if isinstance(scores, list) else [scores]}
```

**Uruchomienie:**
```bash
uv run uvicorn app.services.embedding_service:app --port 8080
```

**Wymagane zmiany:**
- `backend/app/services/embedding_service.py` — NOWY serwis FastAPI
- `backend/app/core/search.py` — `_get_model()` / `_get_reranker()` → HTTP calls
- `backend/app/pipeline/vectorize.py` — `BGEM3FlagModel` → HTTP calls
- `pyproject.toml` — dodać `embed-server` jako entry point + `httpx` jako zależność

**Oczekiwany efekt:**
- Startup `vectorize` i `dashboard`: 30-60 min → **< 5 sek**
- Jeden model w pamięci dla wszystkich procesów (zamiast ~4GB per process)
- Pełne wsparcie sparse (SPLADE) — brak limitów jak w Infinity

**Koszt:** ~150 linii kodu nowego + serwis do uruchomienia przed pracą z projektem.

