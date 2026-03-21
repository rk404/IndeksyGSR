"""
vectorize.py — Buduje wektory BGE-M3 (dense + sparse) dla bazy indeksów i uploaduje do Qdrant.

Użycie:
    python vectorize.py                    # wszystkie indeksy (~69k)
    python vectorize.py --limit 100        # test na 100 indeksach
    python vectorize.py --recreate         # usuń kolekcję i utwórz od nowa
    python vectorize.py --batch-size 32    # rozmiar batcha encodingu (domyślnie 32)
    python vectorize.py --skip-scraping    # nie wczytuj danych z Firestore
    python vectorize.py --dry-run          # wektoryzuj bez zapisu do Qdrant

Wymaga pliku .env z:
    QDRANT_URL=https://xxx.qdrant.io
    QDRANT_API_KEY=abc123...
"""

from __future__ import annotations

import argparse
import logging
import math
import time
from pathlib import Path

import pandas as pd
from qdrant_client import QdrantClient, models

from app.services.gdrive import GoogleDriveClient
from app.services.firestore import get_client as get_db
from app.services.qdrant import get_client as get_qdrant
from app.services.embedding_client import EmbeddingModel

# ──────────────────────────────────────────────
# Konfiguracja
# ──────────────────────────────────────────────

BAZA_CSV = Path(__file__).parent.parent.parent / "data" / "baza_indeksow.csv"
SLOWNIK_CSV = Path(__file__).parent.parent.parent / "data" / "slownik_segmentow.csv"
BAZA_FILE_ID = "19y7cUBp8NfqW98NjoWptNLVyeeYZbEOH"
SLOWNIK_FILE_ID = "1uHCpQe9Yi1WNQ3Abn2LCit0fiHd92f1A"

COLLECTION_NAME = "indeksy"
DENSE_SIZE = 1024
PRODUCTS_COLLECTION = "product_scrapes"
DEFAULT_BATCH_SIZE = 32
QDRANT_UPLOAD_BATCH = 50

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# GCP
# ──────────────────────────────────────────────

# ──────────────────────────────────────────────
# Pliki CSV
# ──────────────────────────────────────────────

def _ensure_csv(local_path: Path, file_id: str, name: str) -> None:
    if not local_path.exists():
        log.info("Pobieranie %s z Google Drive...", name)
        client = GoogleDriveClient()
        client.download_file(file_id, local_path)


def load_baza() -> pd.DataFrame:
    _ensure_csv(BAZA_CSV, BAZA_FILE_ID, "baza_indeksow.csv")
    df = pd.read_csv(BAZA_CSV, sep=None, engine="python", encoding_errors="replace")
    log.info("Wczytano bazę: %d indeksów", len(df))
    return df


def load_slownik() -> pd.DataFrame:
    _ensure_csv(SLOWNIK_CSV, SLOWNIK_FILE_ID, "slownik_segmentow.csv")
    df = pd.read_csv(SLOWNIK_CSV, sep=None, engine="python", encoding_errors="replace")
    log.info("Wczytano słownik: %d wierszy", len(df))
    return df


# ──────────────────────────────────────────────
# Budowanie tekstu
# ──────────────────────────────────────────────

def build_segment_map(slownik_df: pd.DataFrame) -> dict[int, dict[int, str]]:
    """komb_id → {pozycja: wartosc} — poz. 1-3: OPIS_WARTOSC, poz. 4-6: KOD_WARTOSC."""
    # Obsługa obu wariantów nazwy kolumny (KOD_WARTOSC lub KOD_WAROSC)
    kod_col = "KOD_WARTOSC" if "KOD_WARTOSC" in slownik_df.columns else "KOD_WAROSC"

    result: dict[int, dict[int, str]] = {}
    for _, row in slownik_df.iterrows():
        pos = int(row["POZYCJA"])
        komb_id = int(row["KOMB_ID"])
        if komb_id not in result:
            result[komb_id] = {}
        if pos <= 3:
            val = row.get("OPIS_WARTOSC")
            if pd.notna(val):
                result[komb_id][pos] = str(val).strip()
        else:
            val = row.get(kod_col)
            if pd.notna(val):
                result[komb_id][pos] = str(val).strip()
    return result


def load_scrape_map(db: firestore.Client) -> dict[str, dict]:
    """indeks → {title, specifications} z Firestore product_scrapes."""
    log.info("Wczytywanie danych scrapingu z Firestore...")
    scrape_map: dict[str, dict] = {}
    for doc in db.collection(PRODUCTS_COLLECTION).stream():
        d = doc.to_dict()
        if d.get("status") == "ok":
            scrape_map[doc.id] = {
                "title": d.get("title", ""),
                "specifications": d.get("specifications", {}),
            }
    log.info("Wczytano dane scrapingu: %d indeksów", len(scrape_map))
    return scrape_map


def build_text(
    row: pd.Series,
    segment_map: dict[int, dict[int, str]],
    scrape_map: dict[str, dict],
) -> str:
    """Buduje bogaty tekst dla indeksu do wektoryzacji."""
    parts: list[str] = []

    # Zdekodowane segmenty (pozycje 1-3)
    komb_id_raw = row.get("KOMB_ID")
    if pd.notna(komb_id_raw):
        komb_id = int(komb_id_raw)
        seg = segment_map.get(komb_id, {}) if pd.notna(komb_id_raw) else {}
        for pos in [1, 2, 3]:
            val = seg.get(pos)
            if val:
                parts.append(val)

    # Nazwa z bazy
    nazwa = str(row.get("NAZWA", "")).strip()
    if nazwa:
        parts.append(nazwa)

    # Dane ze scrapingu
    indeks = str(row.get("INDEKS", "")).strip()
    scraped = scrape_map.get(indeks, {})
    title = scraped.get("title", "")
    if title and title.lower() != nazwa.lower():
        parts.append(title)

    specs = scraped.get("specifications", {})
    if specs:
        spec_text = " ".join(f"{k}: {v}" for k, v in list(specs.items())[:10])
        parts.append(spec_text)

    return " ".join(filter(None, parts))


# ──────────────────────────────────────────────
# Qdrant
# ──────────────────────────────────────────────

def ensure_collection(client: QdrantClient, recreate: bool) -> None:
    exists = client.collection_exists(COLLECTION_NAME)
    if exists and recreate:
        log.info("Usuwam istniejącą kolekcję '%s'...", COLLECTION_NAME)
        client.delete_collection(COLLECTION_NAME)
        exists = False
    if not exists:
        log.info("Tworzę kolekcję '%s' (dense 1024 + sparse + pomocniczy)...", COLLECTION_NAME)
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config={
                "dense": models.VectorParams(
                    size=DENSE_SIZE,
                    distance=models.Distance.COSINE,
                ),
                "pomocniczy": models.VectorParams(
                    size=DENSE_SIZE,
                    distance=models.Distance.COSINE,
                ),
            },
            sparse_vectors_config={
                "sparse": models.SparseVectorParams()
            },
        )
    else:
        log.info("Kolekcja '%s' już istnieje — dogrywam punkty.", COLLECTION_NAME)


def lexical_to_sparse(weights: dict) -> models.SparseVector:
    if not weights:
        return models.SparseVector(indices=[], values=[])
    items = sorted(weights.items())
    return models.SparseVector(
        indices=[int(k) for k, _ in items],
        values=[float(v) for _, v in items],
    )


def upload_batch(
    client: QdrantClient,
    id_offset: int,
    rows_batch: list[pd.Series],
    dense_vecs: list,
    lexical_weights: list,
    pomocniczy_vecs: list,
    segment_map: dict[int, dict[int, str]],
) -> None:
    points = []
    for i, (row, dense, lex, pomocniczy) in enumerate(zip(rows_batch, dense_vecs, lexical_weights, pomocniczy_vecs)):
        indeks = str(row.get("INDEKS", "")).strip()
        komb_id_raw = row.get("KOMB_ID")
        seg = segment_map.get(int(komb_id_raw), {}) if pd.notna(komb_id_raw) else {}
        points.append(
            models.PointStruct(
                id=id_offset + i,
                vector={
                    "dense": dense.tolist(),
                    "sparse": lexical_to_sparse(lex),
                    "pomocniczy": pomocniczy.tolist(),  # ← zamiast [0.0] * DENSE_SIZE
                },
                payload={
                    "indeks": indeks,
                    "nazwa": str(row.get("NAZWA", "")).strip(),
                    "komb_id": str(row.get("KOMB_ID", "")),
                    "jdmr_nazwa": str(row.get("JDMR_NAZWA", "")),
                    "link": "",  # baza nie ma linków — uzupełniane przez scraper
                    "seg1": seg.get(1, ""),
                    "seg2": seg.get(2, ""),
                    "seg3": seg.get(3, ""),
                    "seg4": seg.get(4, "0"),
                    "seg5": seg.get(5, "0"),
                    "seg6": seg.get(6, "0"),
                },
            )
        )
    client.upsert(collection_name=COLLECTION_NAME, points=points)


# ──────────────────────────────────────────────
# Główna logika
# ──────────────────────────────────────────────

def run(args: argparse.Namespace) -> None:
    # 1. Dane
    baza_df = load_baza()
    slownik_df = load_slownik()
    segment_map = build_segment_map(slownik_df)

    scrape_map: dict[str, dict] = {}
    if not args.skip_scraping:
        db = get_db()
        scrape_map = load_scrape_map(db)

    if args.limit:
        baza_df = baza_df.head(args.limit)
        log.info("Limit: %d indeksów", len(baza_df))

    # 2. Budowanie tekstów
    log.info("Budowanie tekstów dla %d indeksów...", len(baza_df))
    texts = [
        build_text(row, segment_map, scrape_map)
        for _, row in baza_df.iterrows()
    ]
    texts_pomocniczy = [
        str(row.get("NAZWA", "")).strip()
        for _, row in baza_df.iterrows()
    ]
    # 3. Klient embedding service (model załadowany w serwisie, nie tutaj)
    log.info("Łączenie z embedding service (http://localhost:8080)...")
    model = EmbeddingModel()

    # 4. Qdrant (pomijane przy --dry-run)
    qdrant = None
    if not args.dry_run:
        qdrant = get_qdrant()
        ensure_collection(qdrant, args.recreate)
    else:
        log.info("[DRY RUN] Pomijam połączenie z Qdrant.")

    # 5. Wektoryzacja i upload w batchach
    total = len(texts)
    batch_size = args.batch_size
    n_batches = math.ceil(total / batch_size)
    log.info("Wektoryzacja: %d indeksów, batch=%d, batche=%d", total, batch_size, n_batches)
    t0 = time.time()

    for batch_idx in range(n_batches):
        start = batch_idx * batch_size
        end = min(start + batch_size, total)
        batch_texts = texts[start:end]
        batch_rows = [baza_df.iloc[i] for i in range(start, end)]

        output = model.encode(
            batch_texts,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False,
        )
        dense_vecs = output["dense_vecs"]
        lexical_weights = output["lexical_weights"]
        batch_pomocniczy_texts = texts_pomocniczy[start:end]
        output_pomocniczy = model.encode(
            batch_pomocniczy_texts,
            return_dense=True,
            return_sparse=False,
            return_colbert_vecs=False,
        )
        pomocniczy_vecs = output_pomocniczy["dense_vecs"]
        if not args.dry_run:
            # Upload do Qdrant partiami po QDRANT_UPLOAD_BATCH
            for up_start in range(0, len(batch_rows), QDRANT_UPLOAD_BATCH):
                up_end = min(up_start + QDRANT_UPLOAD_BATCH, len(batch_rows))
                upload_batch(
                    qdrant,
                    id_offset=start + up_start,
                    rows_batch=batch_rows[up_start:up_end],
                    dense_vecs=dense_vecs[up_start:up_end],
                    lexical_weights=lexical_weights[up_start:up_end],
                    pomocniczy_vecs=pomocniczy_vecs[up_start:up_end],
                    segment_map=segment_map,
                )

        elapsed = time.time() - t0
        done = end
        eta = elapsed / done * (total - done) if done > 0 else 0
        log.info(
            "Batch %d/%d  [%d/%d]  %.1fs  ETA: %.0fs",
            batch_idx + 1, n_batches, done, total, elapsed, eta,
        )

    elapsed_total = time.time() - t0
    dry_label = "  [DRY RUN — brak zapisu]\n" if args.dry_run else ""
    print(f"\n{'='*50}")
    print(f"  Zwektoryzowano : {total} indeksów")
    print(f"  Kolekcja       : {COLLECTION_NAME}")
    print(f"  Czas           : {elapsed_total:.0f}s ({elapsed_total/max(total,1):.2f}s/indeks)")
    print(dry_label + f"{'='*50}\n")


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="Wektoryzacja bazy indeksów → Qdrant (BGE-M3 hybrid)")
    ap.add_argument("--limit", type=int, help="Pierwsze N indeksów (test)")
    ap.add_argument("--recreate", action="store_true",
                    help="Usuń kolekcję Qdrant i utwórz od nowa")
    ap.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
                    help=f"Rozmiar batcha encodingu (domyślnie {DEFAULT_BATCH_SIZE})")
    ap.add_argument("--skip-scraping", action="store_true",
                    help="Nie wczytuj danych z Firestore product_scrapes")
    ap.add_argument("--dry-run", action="store_true",
                    help="Wektoryzuj bez zapisu do Qdrant")
    args = ap.parse_args()
    run(args)


if __name__ == "__main__":
    main()
