"""
scrape.py — Web scraper produktów z linki_sklepy_indeksy.csv → Firestore.

Użycie:
    python scrape.py                       # scrape wszystkich (8064)
    python scrape.py --limit 100           # pierwsze N wierszy
    python scrape.py --sample 100          # 100 losowych wierszy
    python scrape.py --domain allegro.pl   # tylko wybrana domena
    python scrape.py --resume              # pomiń już zescrapowane
    python scrape.py --dry-run             # bez zapisu do Firestore
    python scrape.py --concurrency 3       # równoległe karty (domyślnie 5)
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import (
    async_playwright,
    TimeoutError as PWTimeout,
    Error as PWError,
)
from google.cloud import firestore

from app.services.gdrive import GoogleDriveClient
from app.services.firestore import get_client as get_db
from app.core.extractors import extract

# ──────────────────────────────────────────────
# Konfiguracja
# ──────────────────────────────────────────────
CSV_FILENAME = "linki_sklepy_indeksy.csv"
LOCAL_CSV = Path(__file__).parent.parent.parent / "data" / CSV_FILENAME
COLLECTION = "product_scrapes"
DEFAULT_CONCURRENCY = 5
PAGE_TIMEOUT_MS = 30_000

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Firestore
# ──────────────────────────────────────────────

def already_scraped(db: firestore.Client) -> set[str]:
    """Zwraca zbiór INDEKS-ów już zescrapowanych (status ok lub error)."""
    done = set()
    for doc in db.collection(COLLECTION).stream():
        d = doc.to_dict()
        if d.get("status") in ("ok", "blocked"):
            done.add(doc.id)
    return done


# ──────────────────────────────────────────────
# CSV
# ──────────────────────────────────────────────

def load_csv() -> list[dict]:
    if not LOCAL_CSV.exists():
        log.info("Pobieranie %s z Google Drive...", CSV_FILENAME)
        client = GoogleDriveClient()
        files = client.list_files_recursive()
        file_map = {f["name"]: f["id"] for f in files}
        fid = file_map.get(CSV_FILENAME)
        if not fid:
            raise FileNotFoundError(f"Nie znaleziono {CSV_FILENAME} na Drive")
        client.download_file(fid, LOCAL_CSV)

    rows = []
    with open(LOCAL_CSV, encoding="utf-8-sig", errors="replace") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            url = (row.get("LINK") or "").strip().strip('"')
            if url.startswith("http"):
                rows.append({
                    "indeks":    (row.get("INDEKS") or "").strip(),
                    "nazwa":     (row.get("NAZWA") or "").strip(),
                    "link":      url,
                    "komb_id":   row.get("KOMB_ID", ""),
                    "jdmr_nazwa": row.get("JDMR_NAZWA", ""),
                })
    log.info("Wczytano %d wierszy z CSV", len(rows))
    return rows


# ──────────────────────────────────────────────
# Scraping
# ──────────────────────────────────────────────

async def scrape_one(
    page,
    row: dict,
    dry_run: bool,
    db: firestore.Client | None,
) -> dict:
    url = row["link"]
    indeks = row["indeks"]
    log.info("  → %s  %s", indeks, url[:70])

    result = {
        "indeks": indeks,
        "nazwa": row["nazwa"],
        "link": url,
        "komb_id": row["komb_id"],
        "jdmr_nazwa": row["jdmr_nazwa"],
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "status": "error",
        "error": None,
        "title": "",
        "description": "",
        "specifications": {},
        "price": "",
    }

    try:
        # Randomowy UA
        await page.set_extra_http_headers({
            "User-Agent": random.choice(USER_AGENTS),
            "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8",
        })
        await page.goto(url, timeout=PAGE_TIMEOUT_MS, wait_until="load")
        await page.wait_for_timeout(random.randint(2000, 3000))  # dodatkowy czas na JS

        extracted = await extract(page, url)

        # Fallback: jeśli nic nie udało się wyciągnąć, zapisz surowy tekst strony
        if not extracted.get("title") and not extracted.get("description"):
            body_text = await page.evaluate("() => document.body?.innerText || ''")
            extracted["description"] = body_text[:3000].strip()
            extracted["title"] = (await page.title()) or ""

        result.update(extracted)
        result["status"] = "ok"

    except (PWTimeout, PWError) as exc:
        result["error"] = type(exc).__name__
        result["status"] = "error"
        log.warning("    BŁĄD: %s — %s", url[:50], type(exc).__name__)
    except Exception as exc:
        result["error"] = str(exc)[:200]
        result["status"] = "error"
        log.warning("    BŁĄD: %s — %s", url[:50], exc)

    if not dry_run and db:
        db.collection(COLLECTION).document(indeks).set(result)

    return result


async def run_scraping(
    rows: list[dict],
    concurrency: int,
    dry_run: bool,
    db: firestore.Client | None,
) -> list[dict]:
    results = []
    semaphore = asyncio.Semaphore(concurrency)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)

        async def worker(row: dict):
            async with semaphore:
                try:
                    ctx = await browser.new_context(
                        viewport={"width": 1280, "height": 800},
                        locale="pl-PL",
                    )
                    page = await ctx.new_page()
                    try:
                        r = await scrape_one(page, row, dry_run, db)
                        results.append(r)
                    finally:
                        try:
                            await ctx.close()
                        except Exception:
                            pass
                except Exception as exc:
                    log.warning("Worker error dla %s: %s", row.get("indeks"), exc)
                # delay poza semaforem — nie blokuje innych tasków
                try:
                    await asyncio.sleep(random.uniform(1.0, 2.5))
                except asyncio.CancelledError:
                    pass

        await asyncio.gather(*[worker(row) for row in rows])
        await browser.close()

    return results


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Web scraper produktów → Firestore")
    ap.add_argument("--limit", type=int, help="Pierwsze N wierszy z CSV")
    ap.add_argument("--sample", type=int, help="N losowych wierszy z CSV")
    ap.add_argument("--domain", help="Filtruj po domenie (np. allegro.pl)")
    ap.add_argument("--resume", action="store_true", help="Pomiń już zescrapowane")
    ap.add_argument("--dry-run", action="store_true", help="Bez zapisu do Firestore")
    ap.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY,
                    help=f"Równoległe karty (domyślnie {DEFAULT_CONCURRENCY})")
    args = ap.parse_args()

    rows = load_csv()

    # Filtrowanie
    if args.domain:
        domain = args.domain.lower().removeprefix("www.")
        rows = [r for r in rows if urlparse(r["link"]).netloc.lower().removeprefix("www.") == domain]
        log.info("Po filtrze domeny '%s': %d wierszy", args.domain, len(rows))

    db = None if args.dry_run else get_db()

    if args.resume and db:
        done = already_scraped(db)
        before = len(rows)
        rows = [r for r in rows if r["indeks"] not in done]
        log.info("Pomijam %d już zescrapowanych, zostało %d", before - len(rows), len(rows))

    if args.sample:
        rows = random.sample(rows, min(args.sample, len(rows)))
        log.info("Losowa próbka: %d wierszy", len(rows))
    elif args.limit:
        rows = rows[: args.limit]
        log.info("Limit: %d wierszy", len(rows))

    log.info("Start scrapowania: %d URL-i, concurrency=%d%s",
             len(rows), args.concurrency, " [DRY RUN]" if args.dry_run else "")
    t0 = time.time()

    results = asyncio.run(run_scraping(rows, args.concurrency, args.dry_run, db))

    ok = sum(1 for r in results if r["status"] == "ok")
    err = sum(1 for r in results if r["status"] == "error")
    elapsed = time.time() - t0

    print(f"\n{'='*50}")
    print(f"  Łącznie     : {len(results)}")
    print(f"  OK          : {ok}")
    print(f"  Błędy       : {err}")
    print(f"  Czas        : {elapsed:.0f}s ({elapsed/max(len(results),1):.1f}s/strona)")
    if args.dry_run:
        print("  [DRY RUN — brak zapisu]")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
