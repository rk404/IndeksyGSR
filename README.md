# IndeksyGSR — Dokumentacja

## Przegląd

System przetwarzania zgłoszeń mailowych z prośbami o założenie nowych indeksów materiałowych. Dane są pobierane z Google Drive, parsowane z pliku `.pst` i zapisywane do Google Cloud (Firestore + Cloud Storage). Uzupełnieniem są dane scrapowane ze stron sklepów (opisy, specyfikacje). Baza ~69 000 indeksów materiałowych jest zwektoryzowana (BGE-M3) i przechowywana w Qdrant Cloud — umożliwia to wyszukiwanie semantyczne po opisie produktu. Wszystko dostępne przez Streamlit dashboard.

## Architektura

```
Google Drive (.pst, CSV)
        │
        ├──────────────────────────────────┬───────────────────────────────┐
        ▼                                  ▼                               ▼
  parse_email.py                      scrape.py                    vectorize.py
        │                                  │                               │
   ┌────┴───────────────┐         ┌────────┴────────┐              ┌───────┴──────┐
   │                    │         │                 │              │              │
   ▼                    ▼         ▼                 ▼              ▼              ▼
Firestore           Cloud      Firestore         Cloud         Qdrant       BGE-M3
(emails)           Storage   (product_scrapes)  Storage        Cloud       (wektory)
                (attachments)
        └──────────────────────────────────┴───────────────────────────────┘
                                           │
                                           ▼
                                     dashboard.py (Streamlit)
                              📧 Maile │ 📦 Produkty │ 🔍 Wyszukiwanie
```

---

## Pliki projektu

| Plik | Opis |
|---|---|
| `gdrive.py` | Klient Google Drive (Service Account) |
| `parse_email.py` | Parser `.pst` → Firestore + GCS |
| `scrape.py` | Web scraper produktów z CSV → Firestore |
| `extractors.py` | Ekstraktory per domena (Allegro, TME, Generic) |
| `vectorize.py` | Wektoryzacja ~69k indeksów (BGE-M3) → Qdrant Cloud |
| `search.py` | Wyszukiwanie semantyczne (hybrid dense+sparse, RRF) |
| `dashboard.py` | Streamlit dashboard (maile + produkty + wyszukiwanie) |
| `requirements.txt` | Zależności Python |
| `service_account.json` | **Klucz GCP — nie commitować!** |
| `.env` | **Klucze Qdrant — nie commitować!** |

---

## Wymagania i instalacja

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install "transformers<5.0"   # wymagane przez FlagEmbedding
playwright install chromium      # tylko dla scrape.py
```

---

## Konfiguracja GCP (jednorazowa)

1. **Service Account** → pobierz klucz JSON → `service_account.json`
   - Role: `Cloud Datastore User`, `Storage Object Admin`, `Storage Legacy Bucket Reader`
2. **Firestore**: tryb Native, `europe-central2`
3. **Cloud Storage**: bucket `projekt-email-attachments`, `europe-central2`
4. **Google Drive**: folder udostępniony e-mailowi Service Account (rola Edytor)

> [!IMPORTANT]
> Plik `service_account.json` nie jest w repozytorium — otrzymasz go od właściciela projektu i umieść w głównym folderze projektu.

## Konfiguracja Qdrant (jednorazowa)

Utwórz plik `.env` w głównym katalogu projektu:

```
QDRANT_URL=https://<twoj-klaster>.qdrant.io
QDRANT_API_KEY=<twoj-klucz>
```

> [!IMPORTANT]
> Plik `.env` nie jest w repozytorium — otrzymasz go od właściciela projektu.

---

## Moduł: `parse_email.py`

### CLI

```bash
python parse_email.py                      # pobierz .pst z Drive i importuj
python parse_email.py --local plik.pst     # użyj lokalnego pliku
python parse_email.py --no-attachments     # pomiń upload PDF do GCS
python parse_email.py --dry-run            # parsuj bez zapisu
python parse_email.py --reset              # wyczyść dane tego PST i reimportuj
python parse_email.py --purge              # wyczyść WSZYSTKIE dane

# Obsługa cytowanej korespondencji w wątku
python parse_email.py --thread-mode keep   # domyślnie: wątek w polu signature
python parse_email.py --thread-mode strip  # usuń cytowaną historię
python parse_email.py --thread-mode split  # wątek jako thread_messages[]
```

### Pola Firestore (`emails`)

| Pole | Typ | Opis |
|---|---|---|
| `id` | string | UUID |
| `pst_source` | string | Nazwa pliku `.pst` |
| `subject` | string | Temat |
| `sender` | string | Nadawca |
| `recipients` | array | Lista adresatów |
| `date` | string | Data (ISO 8601) |
| `body_text` | string | Treść — bez stopki |
| `signature` | string | Stopka nadawcy |
| `thread_messages` | array | Wiadomości z wątku (tryb `split`) |
| `shop_urls` | array | URL-e do sklepów |
| `has_attachments` | bool | Czy są załączniki PDF |
| `attachments` | array | Lista PDF: `filename`, `gcs_path`, `size_bytes` |
| `processed_at` | string | Czas przetworzenia (UTC) |

---

## Moduł: `scrape.py` + `extractors.py`

Jednorazowy web scraper pobierający opisy i specyfikacje produktów z URL-i w pliku `linki_sklepy_indeksy.csv` (Google Drive).

**Dane wejściowe:** 8 064 wierszy CSV (kolumny: `INDEKS`, `NAZWA`, `LINK`, `KOMB_ID`, `JDMR_NAZWA`)
**Dominująca domena:** allegro.pl (1 308 linków), tme.eu (295), tim.pl (97)
**Technologia:** async Playwright (Chromium headless)

### CLI

```bash
python scrape.py                       # scrape wszystkich
python scrape.py --sample 100          # 100 losowych wierszy (test)
python scrape.py --limit 500           # pierwsze N wierszy
python scrape.py --domain allegro.pl   # tylko wybrana domena
python scrape.py --resume              # pomiń już zescrapowane
python scrape.py --dry-run             # bez zapisu do Firestore
python scrape.py --concurrency 5       # liczba równoległych kart (domyślnie 5)
```

### Pola Firestore (`product_scrapes`, klucz = `INDEKS`)

| Pole | Typ | Opis |
|---|---|---|
| `indeks` | string | Kod indeksu materiałowego |
| `nazwa` | string | Nazwa z CSV |
| `link` | string | URL produktu |
| `title` | string | Tytuł ze strony |
| `description` | string | Opis produktu |
| `specifications` | map | Specyfikacje techniczne `{klucz: wartość}` |
| `price` | string | Cena (jeśli dostępna) |
| `status` | string | `ok` / `error` / `blocked` |
| `scraped_at` | string | Czas scrapowania (UTC) |

### Ekstraktory (`extractors.py`)

| Domena | Ekstraktor |
|---|---|
| `allegro.pl` | `AllegroExtractor` — sekcja Parametry, dedykowane selektory |
| `tme.eu` | `TmeExtractor` — tabela params-table |
| inne | `GenericExtractor` — heurystyczny (dl/dt/dd, tabele ≥3 wierszy, sekcja przy nagłówku spec) |

---

## Moduł: `vectorize.py`

Jednorazowa wektoryzacja całej bazy indeksów (~69k) modelem BGE-M3 i upload do Qdrant Cloud.

**Dane wejściowe:**
- `baza_indeksow.csv` (68 991 indeksów) — pobierane automatycznie z Google Drive
- `slownik_segmentow.csv` (372 505 wierszy, dekodowanie KOMB_ID) — pobierane automatycznie z Google Drive
- Firestore `product_scrapes` — opcjonalne uzupełnienie (tytuły i specyfikacje ze scrapingu)

**Model:** `BAAI/bge-m3` (dense 1024-dim + sparse SPLADE-like, ~570 MB)
**Kolekcja Qdrant:** `indeksy` (dense COSINE + sparse)
**Czas wektoryzacji:** ~68 min dla 68 991 indeksów (GPU/CPU)

### Budowanie tekstu do wektoryzacji

Dla każdego indeksu budowany jest tekst z 4 warstw (funkcja `build_text()`):

```
[segment_1] [segment_2] [segment_3] [NAZWA] [scraped_title] [spec_key: spec_val ...]
```

| Warstwa | Źródło | Opis |
|---|---|---|
| `segment_1` | `slownik_segmentow.csv` poz. 1 | TYP INDEKSU (np. `ZŁĄCZKI`, `ARMATURA`) |
| `segment_2` | `slownik_segmentow.csv` poz. 2 | GRUPA ASORTYMENTOWA (np. `ŚRUBY I NAKRĘTKI`) |
| `segment_3` | `slownik_segmentow.csv` poz. 3 | PODGRUPA (np. `ŚRUBY`) |
| `NAZWA` | `baza_indeksow.csv` | Nazwa indeksu z bazy |
| `scraped_title` | Firestore `product_scrapes` | Tytuł ze strony sklepu (jeśli różny od NAZWY) |
| `specs` | Firestore `product_scrapes` | Specyfikacje techniczne (max 10 par `klucz: wartość`) |

**Przykład — indeks ze scrapingiem (~8k indeksów):**
```
ZŁĄCZKI ŚRUBY I NAKRĘTKI ŚRUBY ŚRUBA M20 DIN 931 8.8 CYNK
Śruba metryczna M20 DIN 931 klasa 8.8 cynkowana ogniowo
Gwint: M20 Długość: 100mm Klasa wytrzymałości: 8.8 Powłoka: cynk ogniowy Norma: DIN 931
```

**Przykład — indeks bez scrapingu (~61k indeksów):**
```
ARMATURA KOŁNIERZE KOŁNIERZE PŁASKIE KOŁNIERZ WZMACNIAJĄCY B DN65 PN6 S235JR
```

> [!NOTE]
> Segmenty na pozycjach 4–6 (CECHA GŁÓWNA, MATERIAŁ, ODBIÓR) zawierają wyłącznie kody techniczne bez opisu tekstowego i nie są włączane do tekstu embeddingu.

### Jak działa wektoryzacja BGE-M3 — kolejność zdarzeń

```
tekst (string)
    │
    ▼  tokenizer XLM-RoBERTa (BPE, słownik 250k tokenów)
[CLS] [ZŁĄ][CZKI] [ŚRU][BY] [M][20] [DIN] ... [SEP]
    │
    ▼  transformer 24 warstwy (self-attention)
       każdy token "widzi" cały kontekst
hidden states [seq_len × 1024]
    │
    ├──── CLS pooling + L2-norm ──→  dense_vec [1024]     → wyszukiwanie COSINE
    │
    └──── SPLADE head + max-pool → sparse_vec {id: waga}  → wyszukiwanie dot-product
```

**Krok 1 — tokenizacja (CPU):** tekst dzielony na subwordy BPE. `M20` może być tokenizowane jako `[M][20]` — stąd kody techniczne muszą być uppercase (case-sensitive na poziomie tokenów).

**Krok 2 — forward pass (GPU/CPU):** 24 warstwy self-attention. Token `M20` "widzi" `ŚRUBA` i `CYNK` i buduje swój wektor z uwzględnieniem kontekstu.

**Krok 3 — dense vector:** token `[CLS]` po poolingu i L2-normalizacji → wektor 1024 float32 reprezentujący semantykę całego tekstu.

**Krok 4 — sparse vector (SPLADE head):** każdy token → projekcja na rozmiar słownika (250k) → ReLU → `log(1 + x)` → max-pooling po sekwencji → słownik `{token_id: waga}` z ~100–300 niezerowymi wpisami. Działa jak TF-IDF ważony przez model.

**Krok 5 — upload do Qdrant:** oba wektory + payload (`indeks`, `nazwa`, `komb_id`, `jdmr_nazwa`) zapisywane jako punkt w kolekcji.

> [!NOTE]
> `batch_size=32` oznacza że transformer przetwarza 32 teksty równolegle w jednym forward pass — tensor `[32, seq_len, 1024]`. Większy batch = szybciej, ale więcej RAM.

### CLI

```bash
python vectorize.py                    # wszystkie indeksy (~69k)
python vectorize.py --limit 100        # test na 100 indeksach
python vectorize.py --recreate         # usuń kolekcję i utwórz od nowa
python vectorize.py --batch-size 32    # rozmiar batcha encodingu (domyślnie 32)
python vectorize.py --skip-scraping    # nie wczytuj danych z Firestore
```

### Payload punktu w Qdrant

| Pole | Opis |
|---|---|
| `indeks` | Kod indeksu materiałowego |
| `nazwa` | Nazwa z bazy |
| `komb_id` | ID kombinacji segmentów |
| `jdmr_nazwa` | Jednostka miary |

---

## Moduł: `search.py`

Wyszukiwanie semantyczne w kolekcji Qdrant — hybrid search (dense + sparse) z RRF fusion.

### Użycie jako moduł

```python
from search import search
results = search("śruby M20 ocynkowane ogniowo", top_k=10)
# → [{indeks, nazwa, komb_id, jdmr_nazwa, score}, ...]
```

### CLI

```bash
python search.py "śruby M20 ocynkowane ogniowo"
python search.py "kołnierz DN65 stal" --top-k 5
```

---

## Dashboard (Streamlit)

```bash
source .venv/bin/activate
streamlit run dashboard.py
# → http://localhost:8501
```

### Widoki

**📧 Maile**
- Wyszukiwarka i filtry (linki, PDF-y, plik PST)
- Lista maili z typem i datą
- Panel szczegółów: treść, stopka, linki, pobieranie PDF z GCS

**📦 Produkty (scraping)**
- Metryki: łączna liczba, OK/błędy, ze specyfikacjami
- Lista produktów z indeksem, tytułem, ceną
- Panel szczegółów: tabela specyfikacji, opis, link do sklepu
- Filtry: tylko z specyfikacjami, tylko poprawne, wyszukiwarka

**🔍 Wyszukiwanie**
- Pole tekstowe z opisem produktu
- Wybór liczby wyników (5 / 10 / 20)
- Wyniki z indeksem, nazwą, jednostką miary i score RRF

---

## Wyniki (2026-02-24)

| Zbiór | Liczba | Uwagi |
|---|---|---|
| Maile (PST) | 100 | `split` thread mode, polskie znaki OK |
| Produkty (scraping) | 85 / 100 próbka | 82 OK, 21 ze specyfikacjami |
| Indeksy w Qdrant | 68 991 | Pełna wektoryzacja BGE-M3, hybrid search aktywny |
