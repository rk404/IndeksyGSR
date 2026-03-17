# Plan: Frontend wyszukiwarki indeksów GSR (GCP-native, z auth)

## Kontekst

Projekt używa już: Firestore (`studia-488119`, `europe-central2`), Cloud Storage, Service Account. Brakuje: Dockera, CI/CD, deploymentu i warstwy API. Celem jest właściwa aplikacja webowa z autentykacją użytkowników, gotowa do hostowania w GCP — z możliwością rozbudowy (zarządzanie użytkownikami, uprawnienia, historia zapytań).

---

## Stack (GCP-native)

```
┌──────────────────────────────────────────────────────────┐
│  Firebase Hosting                                        │
│  React SPA (Vite)                                        │
│  ├─ Firebase Auth SDK   ← login / register               │
│  └─ fetch → FastAPI                                      │
└──────────────────────────────────────────────────────────┘
           ↓ HTTP + Bearer token (Firebase ID Token)
┌──────────────────────────────────────────────────────────┐
│  Cloud Run — FastAPI (backend/app/main.py)               │
│  ├─ Middleware: weryfikacja Firebase ID Token            │
│  ├─ POST /api/search                                     │
│  ├─ POST /api/search-url                                 │
│  ├─ GET  /api/segments                                   │
│  ├─ POST /api/suggest                                    │
│  └─ POST /api/propose  → Firestore "proposed_indexes"    │
└──────────────────────────────────────────────────────────┘
           ↓ HTTP                        ↓ gRPC
┌─────────────────────┐      ┌──────────────────────────┐
│  Cloud Run          │      │  Qdrant Cloud            │
│  embedding_service  │      │  europe-west3            │
│  /encode  /rerank   │      │  collection: "indeksy"   │
└─────────────────────┘      └──────────────────────────┘
                                         ↑
                              search.py, suggest.py
                              (bez zmian — jako biblioteka)
```

**Dlaczego ten stack:**
- Firebase Auth → naturalnie paruje z Firestore (`studia-488119`) — ten sam projekt GCP
- Cloud Run → idealny dla kontenerowego FastAPI, skaluje do 0, prosty billing
- React na Firebase Hosting → darmowy CDN, jeden projekt GCP
- Cały istniejący kod logiki (search.py, suggest.py) staje się biblioteką — **zero przepisywania**

---

## Pliki do stworzenia

### Backend (FastAPI API)
| Plik | Opis |
|---|---|
| `backend/app/main.py` | FastAPI app: routing, CORS, Firebase auth middleware |
| `backend/app/api/search.py` | Endpointy /search, /search-url |
| `backend/app/api/segments.py` | Endpointy /segments, /suggest |
| `backend/app/api/propose.py` | Endpoint /propose → Firestore |
| `backend/app/api/auth.py` | Firebase ID token verification (middleware) |
| `Dockerfile` | Container dla Cloud Run (backend + embed-server) |

### Frontend (React)
| Plik | Opis |
|---|---|
| `frontend/` | Nowy katalog — Vite + React |
| `frontend/src/App.tsx` | Router: /login, /search, /proposals |
| `frontend/src/pages/Search.tsx` | Główna strona: input + wyniki + formularz propozycji |
| `frontend/src/pages/Login.tsx` | Firebase Auth UI |
| `frontend/src/pages/Proposals.tsx` | Historia propozycji użytkownika |
| `frontend/firebase.json` | Firebase Hosting config |
| `frontend/.firebaserc` | Projekt: `studia-488119` |

### Infrastruktura
| Plik | Opis |
|---|---|
| `.dockerignore` | Wykluczenia dla Dockera |
| `pyproject.toml` | Dodać `firebase-admin` jako dependency |

---

## API Endpoints (FastAPI)

```python
# Autentykacja — Bearer token w każdym żądaniu
# Middleware weryfikuje Firebase ID Token przez firebase-admin

POST /api/search
  body: {query: str, top_k: int = 10, rerank: bool = false}
  → [{indeks, nazwa, jdmr_nazwa, score}]

POST /api/search-url
  body: {url: str, top_k: int = 10, rerank: bool = false}
  → {query: str, results: [{indeks, nazwa, jdmr_nazwa, score}]}

GET /api/segments
  → {pos1: [...], pos2_by_parent: {...}, pos3_by_parent: {...},
     pos4_values: [...], pos5_values: [...], pos6_values: [...]}

POST /api/suggest
  body: {query: str}
  → [{seg1_text, seg2_text, seg3_text, score}]

POST /api/propose
  body: {query, seg1, seg2, seg3, seg4, seg5, seg6, nazwa}
  → {id: str}  (Firestore doc ID)
  zapis do: db.collection("proposed_indexes").add({..., user_email: token.email})

GET /api/proposals/me
  → lista propozycji zalogowanego użytkownika
```

---

## Funkcje do reużycia (bez zmian)

| Funkcja | Plik |
|---|---|
| `search(query, top_k, rerank)` | `app/core/search.py` |
| `normalize_query()` | `app/core/search.py` |
| `build_segment_tree()` | `app/core/suggest.py` |
| `suggest_segments()` | `app/core/suggest.py` |
| `load_slownik()` | `app/pipeline/vectorize.py` |
| `_scrape_url()` | wydzielić z `app/dashboard.py` |
| `get_db()` | `app/services/firestore.py` |
| `EmbeddingModel` | `app/services/embedding_client.py` |

---

## Zarządzanie użytkownikami

Firebase Authentication (wbudowane):
- Email + hasło (start)
- Google OAuth (opcjonalne — naturalny fit z GCP)
- Każda propozycja w Firestore ma pole `user_email` / `user_uid`
- Przyszłe rozszerzenie: role w Firestore (`users` collection) → admin/user

---

## Obsługa modeli ML w chmurze

### Problem
BGE-M3 (~570 MB model) i BGE-reranker (~1.1 GB) potrzebują dużo RAM lub GPU. Cloud Run nie wspiera GPU w `europe-central2`.

### Porównanie opcji

| Opcja | Cold start | Koszt | GPU | Złożoność |
|---|---|---|---|---|
| **Cloud Run (CPU, min-inst=1)** | ~0s (ciepły) | ~$50-80/mies | ❌ | niska |
| **Compute Engine VM (e2-highmem-8)** | brak | ~$80/mies | ❌ | średnia |
| **Cloud Run GPU (us-central1, L4)** | ~30s cold | ~$0.50/h | ✅ NVIDIA L4 | niska |
| **Vertex AI Prediction** | auto | pay-per-req | ✅ | wysoka |

### Rekomendacja: **Cloud Run (CPU) z `min-instances=1`**

Uzasadnienie:
- BGE-M3 z fp16 działa poprawnie na CPU (wektoryzacja ~0.3s/query w search, ~10s/batch-32 w vectorize)
- `min-instances=1` → brak cold startu (model zawsze załadowany w pamięci)
- `europe-central2` — ten sam region co Firestore i Cloud Storage
- Najprostszy deployment bez konieczności zmiany kodu

```yaml
# Parametry Cloud Run dla embed-server
memory: 16Gi       # BGE-M3 (1.1GB) + reranker (2.2GB) + overhead
cpu: 4             # fp16 inference na CPU
min-instances: 1   # zawsze ciepły, modele załadowane
max-instances: 2   # rzadko potrzebny drugi
concurrency: 4     # kolejka requestów (encode jest synchroniczne)
```

### Alternatywa na przyszłość: GPU
Gdy projekt wyjdzie poza fazę studencką — migracja `embed-server` do Cloud Run GPU (`us-central1`, NVIDIA L4):
- Czas encode: ~300ms → ~30ms
- Koszt: ~$0.50/h (tylko gdy używany, jeśli `min-instances=0`)
- Wymaga zmiany regionu lub VPC peering do `europe-central2`

### Środowisko lokalne (dev)
Bez zmian — `uv run embed-server` lokalnie jak dotychczas. Env var `EMBEDDING_SERVICE_URL` przełącza między lokalnym a cloudowym serwisem.

---

## Deployment

```bash
# 1. Backend API na Cloud Run
gcloud builds submit --tag gcr.io/studia-488119/indeksygsr-api ./backend
gcloud run deploy indeksygsr-api \
  --image gcr.io/studia-488119/indeksygsr-api \
  --region europe-central2 \
  --memory 2Gi \
  --set-secrets QDRANT_URL=qdrant-url:latest,QDRANT_API_KEY=qdrant-key:latest \
  --set-env-vars EMBEDDING_SERVICE_URL=https://embed-server-xxx-ew.a.run.app

# 2. Embedding service na Cloud Run (CPU, zawsze ciepły)
gcloud run deploy embed-server \
  --image gcr.io/studia-488119/embed-server \
  --region europe-central2 \
  --memory 16Gi \
  --cpu 4 \
  --min-instances 1 \
  --max-instances 2 \
  --concurrency 4

# 3. Frontend na Firebase Hosting
cd frontend && npm run build
firebase deploy --only hosting --project studia-488119
```

---

## Weryfikacja

1. `firebase login && firebase use studia-488119`
2. `npm run dev` (frontend) + `uv run embed-server` + `uv run uvicorn app.main:app --port 8000`
3. Otwórz `localhost:5173` → zaloguj się przez Firebase Auth
4. Wpisz "śruby M10 nierdzewne" → fetch do `localhost:8000/api/search` → wyniki
5. Wklej URL sklepu → wyniki ze scrapingu
6. Odrzuć wyniki → formularz z seg1→seg2→seg3 (kaskadowo) → [Wyślij propozycję]
7. Firestore: sprawdź nowy dokument w `proposed_indexes` z `user_uid`
8. Strona `/proposals` → widać tylko własne propozycje
