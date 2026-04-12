# IndeksyGSR — Dokumentacja

## Przegląd

Semantyczny system wyszukiwania indeksów materiałowych (~69 000 pozycji). Użytkownik podaje opis produktu (tekstem, linkiem URL lub plikiem Excel) — system dopasowuje właściwy indeks z bazy, korzystając z hybrydowego wyszukiwania wektorowego (BGE-M3 dense + sparse + RRF) z opcjonalnym rerankingiem cross-encodera.

Interfejs użytkownika to aplikacja webowa React (Vite + Tailwind, motyw Solarized) komunikująca się z backendem FastAPI. Dane indeksów przechowywane są w Qdrant Cloud, dane operacyjne w Google Cloud Firestore i Cloud Storage.

## Architektura

```
Google Drive (.pst, CSV)
        │
        ├────────────────────┬────────────────────┐
        ▼                    ▼                    ▼
  parse_email.py         scrape.py          vectorize.py
        │                    │                    │
   Firestore + GCS      Firestore             Qdrant Cloud
   (emails,             (product_scrapes)     (68 991 pkt)
    attachments)
                                                  ▲
                                         embed-server :8080
                                         (BGE-M3 + reranker)

                    ┌─────────────────────┐
                    │   FastAPI :8000      │
                    │  /api/search         │
                    │  /api/search-url     │
                    │  /api/search/bulk    │
                    │  /api/segments       │
                    │  /api/proposals      │
                    └────────┬────────────┘
                             │
                    ┌────────▼────────────┐
                    │  React SPA :5173    │
                    │  Wyszukiwanie       │
                    │  Wyszukiwanie URL   │
                    │  Wyszukiwanie zbior.│
                    │  Propozycje indeks. │
                    └─────────────────────┘
```

---

## Struktura projektu

```
IndeksyGSR/
├── pyproject.toml              # definicja pakietu + zależności
├── uv.lock                     # lock file (uv)
├── install.py                  # skrypt instalacyjny (jednorazowy)
├── .python-version             # Python 3.13
├── backend/
│   └── app/
│       ├── main.py             # FastAPI — CORS, montowanie routerów
│       ├── dashboard.py        # Streamlit UI (legacy)
│       ├── core/
│       │   ├── search.py       # wyszukiwanie hybrydowe (BGE-M3 + RRF + reranker)
│       │   ├── suggest.py      # auto-sugestia segmentów dla nowych indeksów
│       │   ├── scraper.py      # scrapowanie URL → dane produktu
│       │   └── extractors.py  # parsery DOM per domena (Allegro, TME, generic)
│       ├── api/
│       │   ├── models.py       # schematy Pydantic (request/response)
│       │   ├── search.py       # endpointy /search, /search-url, /bulk, /generate-description
│       │   └── segments.py     # endpointy /segments, /suggest, /propose, /proposals
│       ├── pipeline/
│       │   ├── parse_email.py  # parser .pst → Firestore + GCS
│       │   ├── scrape.py       # web scraper CSV → Firestore
│       │   ├── vectorize.py    # BGE-M3 → Qdrant Cloud
│       │   └── enums.py
│       └── services/
│           ├── embedding_service.py  # FastAPI serwis modeli (BGE-M3 + reranker)
│           ├── embedding_client.py   # klient HTTP do embedding_service
│           ├── firestore.py
│           ├── gcs.py
│           ├── gdrive.py
│           ├── qdrant.py
│           └── groq_client.py        # klient Groq LLM (generowanie opisów)
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── SearchPage.tsx         # wyszukiwanie po tekście
│   │   │   ├── SearchByUrlPage.tsx    # wyszukiwanie po URL
│   │   │   ├── BulkSearchPage.tsx     # wyszukiwanie zbiorcze (Excel)
│   │   │   └── ProposalsPage.tsx      # propozycje nowych indeksów
│   │   ├── components/
│   │   │   ├── Sidebar.tsx            # nawigacja + przełącznik motywu
│   │   │   ├── Layout.tsx
│   │   │   ├── SearchResults.tsx      # lista wyników z checkboxami
│   │   │   ├── ResultCard.tsx         # pojedynczy wynik
│   │   │   ├── DescGenPanel.tsx       # panel generowania opisu (Groq LLM)
│   │   │   ├── DropZone.tsx           # drag & drop upload pliku
│   │   │   ├── OptionsPanel.tsx       # panel opcji (topK, reranking)
│   │   │   ├── SegmentForm.tsx        # formularz propozycji nowego indeksu
│   │   │   └── ProposalCard.tsx       # karta propozycji
│   │   ├── api/
│   │   │   ├── search.ts              # hooki TanStack Query (search, bulk, save)
│   │   │   └── segments.ts            # hooki (segments, proposals, approve/reject)
│   │   ├── hooks/
│   │   │   └── useTheme.ts            # przełącznik jasny/ciemny (localStorage)
│   │   ├── types/index.ts
│   │   └── styles/globals.css         # Tailwind + Solarized Light/Dark CSS vars
│   ├── vite.config.ts                 # proxy /api → localhost:8000
│   └── package.json
└── scripts/
    └── generate_presentation.py       # generator prezentacji PPTX
```

---

## Wymagania i instalacja

### Backend

```bash
python install.py
```

Skrypt automatycznie:
1. instaluje `uv` (jeśli brak)
2. instaluje zależności Python (`uv sync`)
3. pobiera przeglądarkę Chromium dla Playwright
4. pobiera modele HuggingFace: `BAAI/bge-m3` (~570 MB) i `BAAI/bge-reranker-v2-m3` (~1.1 GB)

#### Linux
Wymagany `xdotool`:
```bash
sudo apt install xdotool
```

#### macOS
Wymagany `yabai`:
```bash
brew tap koekeishiya/formulae && brew install yabai
```
Nadaj uprawnienia: System Settings → Privacy & Security → Accessibility → yabai.

### Obsługa plików `.pst` (parse-email)

`libpff` nie ma gotowych kół dla Windows — na wszystkich platformach instaluj z flagą `--with-pst`:

```bash
python install.py --with-pst
```

Bez flagi `--with-pst` komenda `parse-email` nie będzie dostępna; `scrape`, `vectorize`, `search`, `api-server` i `dashboard` działają normalnie.

#### Windows — wymagania wstępne przed `--with-pst`

**Visual C++ Build Tools:** https://visualstudio.microsoft.com/visual-cpp-build-tools/
(zaznacz pakiet „Programowanie aplikacji klasycznych w języku C++")

**CMake:** https://cmake.org/download/ (zaznacz „Add CMake to the system PATH")

> [!TIP]
> Na Windows zalecane jest WSL2 — instalacja bez dodatkowych narzędzi:
> ```bash
> python install.py --with-pst
> ```

### Frontend

```bash
cd frontend
npm install
```

---

## Konfiguracja

### GCP (jednorazowa)

1. **Service Account** → klucz JSON → `backend/service_account.json`
   - Role: `Cloud Datastore User`, `Storage Object Admin`, `Storage Legacy Bucket Reader`
2. **Firestore**: tryb Native, `europe-central2`
3. **Cloud Storage**: bucket `projekt-email-attachments`, `europe-central2`
4. **Google Drive**: folder udostępniony e-mailowi Service Account (rola Edytor)

> [!IMPORTANT]
> `backend/service_account.json` nie jest w repozytorium — otrzymasz go od właściciela projektu.

### Zmienne środowiskowe

Utwórz plik `backend/.env`:

```env
QDRANT_URL=https://<twoj-klaster>.qdrant.io
QDRANT_API_KEY=<twoj-klucz>
EMBEDDING_SERVICE_URL=http://localhost:8080   # domyślnie localhost:8080
GROQ_API_KEY=<twoj-klucz-groq>               # do generowania opisów LLM
GROQ_MODEL=llama-3.3-70b-versatile           # domyślny model Groq
```

> [!IMPORTANT]
> `backend/.env` nie jest w repozytorium — otrzymasz go od właściciela projektu.

---

## Uruchomienie

### Tryb deweloperski (pełny stack)

**1. Serwis embeddingów** (ładuje modele BGE-M3 + reranker):
```bash
uv run embed-server
# → http://localhost:8080
```

**2. Backend FastAPI:**
```bash
uv run uvicorn app.main:app --reload --port 8000
# → http://localhost:8000
```

**3. Frontend React:**
```bash
cd frontend
npm run dev
# → http://localhost:5173
```

Proxy Vite kieruje `/api/*` → `http://localhost:8000` — CORS nie jest wymagany w trybie dev.

---

## API — endpointy

| Metoda | Ścieżka | Opis |
|--------|---------|------|
| POST | `/api/search` | Wyszukiwanie po tekście |
| POST | `/api/search-url` | Wyszukiwanie po URL (scraping + search) |
| POST | `/api/search/save` | Zapis zaznaczonych wyników do Firestore |
| POST | `/api/search/bulk` | Wyszukiwanie zbiorcze (plik xlsx → JSON) |
| POST | `/api/search/bulk/download` | Wyszukiwanie zbiorcze (plik xlsx → xlsx) |
| POST | `/api/generate-description` | Generowanie opisu przez Groq LLM |
| GET  | `/api/segments` | Drzewo segmentów (3-poziomowa hierarchia) |
| POST | `/api/suggest` | Auto-sugestia segmentów dla nowego indeksu |
| POST | `/api/propose` | Dodanie propozycji nowego indeksu |
| GET  | `/api/proposals` | Lista propozycji (opcjonalny filtr statusu) |
| POST | `/api/proposals/{id}/approve` | Zatwierdzenie propozycji + upsert do Qdrant |
| POST | `/api/proposals/{id}/reject` | Odrzucenie propozycji |

---

## Komendy CLI

```bash
source .venv/bin/activate
# lub
uv run <komenda>
```

### parse-email

```bash
parse-email                        # pobierz .pst z Drive i importuj
parse-email --local plik.pst       # użyj lokalnego pliku
parse-email --no-attachments       # pomiń upload PDF do GCS
parse-email --dry-run              # parsuj bez zapisu
parse-email --reset                # wyczyść dane tego PST i reimportuj
parse-email --purge                # wyczyść WSZYSTKIE dane
parse-email --thread-mode keep     # domyślnie: wątek w polu signature
parse-email --thread-mode strip    # usuń cytowaną historię
parse-email --thread-mode split    # wątek jako thread_messages[]
```

### scrape

```bash
scrape                             # scrape wszystkich
scrape --sample 100                # 100 losowych wierszy (test)
scrape --limit 500                 # pierwsze N wierszy
scrape --domain allegro.pl         # tylko wybrana domena
scrape --resume                    # pomiń już zescrapowane
scrape --dry-run                   # bez zapisu do Firestore
scrape --concurrency 5             # liczba równoległych kart (domyślnie 5)
```

### vectorize

```bash
vectorize                          # wszystkie indeksy (~69k)
vectorize --limit 100              # test na 100 indeksach
vectorize --recreate               # usuń kolekcję i utwórz od nowa
vectorize --batch-size 32          # rozmiar batcha encodingu (domyślnie 32)
vectorize --skip-scraping          # nie wczytuj danych z Firestore
```

### search (CLI)

```bash
search "śruby M20 ocynkowane ogniowo"
search "kołnierz DN65 stal" --top-k 5
search "śruby M20" --rerank        # reranking cross-encoderem
```

### embed-server

```bash
embed-server
# → http://localhost:8080
# Endpointy: POST /encode, POST /rerank
```

### dashboard (legacy Streamlit)

```bash
dashboard
# → http://localhost:8501
```

---

## Moduły techniczne

### search.py — wyszukiwanie hybrydowe

**Normalizacja zapytania:**
- Kody techniczne → uppercase: `m20` → `M20`, `dn65` → `DN65`
- Synonimy: `ocynkowana ogniowo` → `OGNIOWO`, `nierdzewna`/`inox` → `A2`, `kwasoodporna` → `A4`

**Przepływ wyszukiwania:**
```
zapytanie
    │
    ├─ dense vec (BGE-M3 + instrukcja)  ─┐
    ├─ sparse vec (SPLADE)              ─┼─► Qdrant prefetch × 3
    └─ pomocniczy vec (BGE-M3 bez instr.)─┘
                                         │
                                    RRF Fusion
                                         │
                              [opcjonalnie] cross-encoder reranker
                              (normalize=False + temperature sigmoid T=2.5)
                                         │
                                    wyniki [{indeks, nazwa, score}]
```

**Użycie jako moduł:**
```python
from app.core.search import search
results = search("śruby M20 ocynkowane ogniowo", top_k=10)
results = search("śruby M20 ocynkowane ogniowo", top_k=10, rerank=True)
# → [{indeks, nazwa, komb_id, jdmr_nazwa, score}, ...]
```

### suggest.py — auto-sugestia segmentów

```
zapytanie → BGE-M3 embed → cosine top-3 seg1 → top-2 seg2 → top-2 seg3
→ SegmentProposal(seg1, seg2, seg3, score=avg_similarity)
```

### embedding_service.py + embedding_client.py

Modele BGE-M3 i BGE-reranker ładowane **raz przy starcie** — eliminuje cold-start.

| Endpoint | Opis |
|----------|------|
| `POST /encode` | Dense (1024) + sparse SPLADE z BGE-M3 |
| `POST /rerank` | Cross-encoder scores z BGE-reranker-v2-m3 |

### vectorize.py

**Tekst do wektoryzacji (4 warstwy):**
```
[segment_1] [segment_2] [segment_3] [NAZWA] [scraped_title] [spec_key: val ...]
```

**Wektory w kolekcji Qdrant `indeksy`:**

| Wektor | Rozmiar | Źródło |
|--------|---------|--------|
| `dense` | 1024 float | Pełny tekst (segmenty + nazwa + scraping) |
| `sparse` | ~100–300 wpisów | SPLADE weights z pełnego tekstu |
| `pomocniczy` | 1024 float | Tylko `NAZWA` z CSV |

---

## Struktura danych Firestore

### `emails`

| Pole | Typ | Opis |
|------|-----|------|
| `id` | string | UUID |
| `pst_source` | string | Nazwa pliku `.pst` |
| `subject` | string | Temat |
| `sender` | string | Nadawca |
| `recipients` | array | Lista adresatów |
| `date` | string | Data (ISO 8601) |
| `body_text` | string | Treść bez stopki |
| `signature` | string | Stopka nadawcy |
| `shop_urls` | array | URL-e do sklepów |
| `has_attachments` | bool | Czy są załączniki PDF |
| `attachments` | array | `{filename, gcs_path, size_bytes}` |
| `processed_at` | string | Czas przetworzenia (UTC) |

### `product_scrapes`

| Pole | Typ | Opis |
|------|-----|------|
| `indeks` | string | Kod indeksu materiałowego |
| `nazwa` | string | Nazwa z CSV |
| `link` | string | URL produktu |
| `title` | string | Tytuł ze strony |
| `description` | string | Opis produktu |
| `specifications` | map | `{klucz: wartość}` |
| `price` | string | Cena (jeśli dostępna) |
| `status` | string | `ok` / `error` / `blocked` |
| `scraped_at` | string | Czas scrapowania (UTC) |

### `search_selections`

Każde kliknięcie „Zapisz zaznaczone" w aplikacji webowej tworzy dokument:

| Pole | Opis |
|------|------|
| `query` | Zapytanie użytkownika |
| `source` | `text` / `url` |
| `indeks`, `nazwa`, `score` | Wybrany wynik |
| `groq_description` | Wygenerowany opis (opcjonalny) |
| `saved_at` | Czas zapisu (UTC) |

---

## Wyniki (2026-02-24)

| Zbiór | Liczba | Uwagi |
|-------|--------|-------|
| Maile (PST) | 100 | `split` thread mode, polskie znaki OK |
| Produkty (scraping) | 85 / 100 próbka | 82 OK, 21 ze specyfikacjami |
| Indeksy w Qdrant | 68 991 | Pełna wektoryzacja BGE-M3, hybrid search aktywny |
| Czas wyszukiwania | < 1 s | RRF fusion, opcjonalny reranking |
