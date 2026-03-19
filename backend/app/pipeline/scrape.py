"""
scrape.py — Web scraper produktów z linki_sklepy_indeksy.csv → Firestore.
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
from .enums import BotSecuredPages

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
    # "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    # "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36",
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
                    "indeks": (row.get("INDEKS") or "").strip(),
                    "nazwa": (row.get("NAZWA") or "").strip(),
                    "link": url,
                    "komb_id": row.get("KOMB_ID", ""),
                    "jdmr_nazwa": row.get("JDMR_NAZWA", ""),
                })

    log.info("Wczytano %d wierszy z CSV", len(rows))
    return rows


# ──────────────────────────────────────────────
# Human behaviour
# ──────────────────────────────────────────────

async def human_scroll(page):
    for _ in range(random.randint(2, 4)):
        await page.mouse.wheel(0, random.randint(400, 900))
        await asyncio.sleep(random.uniform(0.125, 0.73))

async def human_delay():
    await asyncio.sleep(random.uniform(0.3, 1.5))


# ──────────────────────────────────────────────
# Scraping
# ──────────────────────────────────────────────

async def scrape_one(page, row, dry_run, db):
    url = row["link"]
    indeks = row["indeks"]
    log.info("→ %s %s", indeks, url[:80])

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
        await page.goto(url, timeout=PAGE_TIMEOUT_MS)

        if any(securedPage in url for securedPage in BotSecuredPages):
            await human_delay()
            await human_scroll(page)

        extracted = await extract(page, url)

        if not extracted.get("title"):
            body_text = await page.evaluate(
                "() => document.body?.innerText || ''"
            )
            extracted["description"] = body_text[:3000]
            extracted["title"] = await page.title()
        result.update(extracted)
        result["status"] = "ok"

    except (PWTimeout, PWError) as exc:
        result["error"] = type(exc).__name__
        log.warning("Błąd: %s %s", url[:50], exc)

    except Exception as exc:
        result["error"] = str(exc)[:200]
        log.warning("Błąd: %s %s", url[:50], exc)

    if not dry_run and db:
        db.collection(COLLECTION).document(indeks).set(result)

    return result


# ──────────────────────────────────────────────
# Scraping runner
# ──────────────────────────────────────────────

async def run_scraping(rows, concurrency, dry_run, db):
    results = []

    storage_file = "storage.json"
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            slow_mo=150,
        )
        ua = random.choice(USER_AGENTS)
        context_args = dict(
            user_agent=ua,
            locale="pl-PL",
            viewport={"width": 1400, "height": 900},
        )

        if Path(storage_file).exists():
            context_args["storage_state"] = storage_file

        context = await browser.new_context(**context_args)
        page = await context.new_page()

        for row in rows:
            r = await scrape_one(page, row, dry_run, db)
            results.append(r)
            await context.storage_state(path=storage_file)
            await asyncio.sleep(random.uniform(0.5, 5))
        await browser.close()

    return results


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--sample", type=int)
    ap.add_argument("--domain")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)

    args = ap.parse_args()

    rows = load_csv()

    if args.domain:
        domain = args.domain.lower().removeprefix("www.")
        rows = [
            r for r in rows
            if urlparse(r["link"]).netloc.lower().removeprefix("www.") == domain
        ]
        log.info("Po filtrze domeny '%s': %d", args.domain, len(rows))

    db = None if args.dry_run else get_db()

    if args.resume and db:
        done = already_scraped(db)
        before = len(rows)
        rows = [r for r in rows if r["indeks"] not in done]
        log.info("Pomijam %d już zescrapowanych", before - len(rows))

    if args.sample:
        rows = random.sample(rows, min(args.sample, len(rows)))

    elif args.limit:
        rows = rows[: args.limit]

    log.info("Start scrapowania: %d URL", len(rows))
    t0 = time.time()

    results = asyncio.run(
        run_scraping(rows, args.concurrency, args.dry_run, db)
    )

    ok = sum(1 for r in results if r["status"] == "ok")
    err = sum(1 for r in results if r["status"] != "ok")
    elapsed = time.time() - t0

    print()
    print("=" * 50)
    print("Łącznie :", len(results))
    print("OK :", ok)
    print("Błędy :", err)
    print("Czas :", int(elapsed), "s")
    print("=" * 50)


if __name__ == "__main__":
    main()