"""
scrape_new.py — Web scraper produktów (httpx + BeautifulSoup) z linki_sklepy_indeksy.csv → Firestore.

ALTERNATYWA DO PLAYWRIGHT:
  - httpx: nowoczesny async HTTP client (szybszy niż Playwright)
  - BeautifulSoup4: parser HTML (wystarczy dla statycznych danych produktów)
  - ~10x szybciej, mniej RAM, identyczne wyniki dla większości sklepy

Użycie:
    python scrape_new.py                   # scrape wszystkich (8064)
    python scrape_new.py --limit 100       # pierwsze N wierszy
    python scrape_new.py --sample 100      # 100 losowych wierszy
    python scrape_new.py --domain allegro.pl  # tylko wybrana domena
    python scrape_new.py --resume          # pomiń już zescrapowane
    python scrape_new.py --dry-run         # bez zapisu do Firestore
    python scrape_new.py --concurrency 10  # równoległe requesty (domyślnie 10)
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import random
import time
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urljoin

import httpx
from bs4 import BeautifulSoup
from google.cloud import firestore

from app.services.gdrive import GoogleDriveClient
from app.services.firestore import get_client as get_db

# ──────────────────────────────────────────────
# Konfiguracja
# ──────────────────────────────────────────────
CSV_FILENAME = "linki_sklepy_indeksy.csv"
LOCAL_CSV = Path(__file__).parent.parent.parent / "data" / CSV_FILENAME
COLLECTION = "product_scrapes_beautifulsoup"  # oddzielna kolekcja dla BS4 vs Playwright
DEFAULT_CONCURRENCY = 10  # httpx daje radę więcej równoczesnych połączeń niż Playwright
REQUEST_TIMEOUT = 15.0    # timeOut na pobranie strony (w sekundach)

# User-Agenty (obejście podstawowych blokad robotów)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Firestore — status produktów
# ──────────────────────────────────────────────

def already_scraped(db: firestore.Client) -> set[str]:
    """
    Zwraca zbiór INDEKS-ów już zescrapowanych (status 'ok' lub 'blocked').
    Używane w trybie --resume żeby nie robić tej samej pracy dwa razy.
    """
    done = set()
    for doc in db.collection(COLLECTION).stream():
        d = doc.to_dict()
        if d.get("status") in ("ok", "blocked"):
            done.add(doc.id)
    return done


# ──────────────────────────────────────────────
# CSV — wczytanie listy linków produktów
# ──────────────────────────────────────────────

def load_csv() -> list[dict]:
    """
    Wczytuje CSV z Google Drive lub lokalnie.
    Struktura spodziewana: INDEKS, NAZWA, LINK, KOMB_ID, JDMR_NAZWA
    """
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
            # Filtrujemy tylko poprawne URLs
            if url.startswith("http"):
                rows.append({
                    "indeks":     (row.get("INDEKS") or "").strip(),
                    "nazwa":      (row.get("NAZWA") or "").strip(),
                    "link":       url,
                    "komb_id":    row.get("KOMB_ID", ""),
                    "jdmr_nazwa": row.get("JDMR_NAZWA", ""),
                })
    log.info("Wczytano %d wierszy z CSV", len(rows))
    return rows


# ──────────────────────────────────────────────
# HTML Parsing — BeautifulSoup
# ──────────────────────────────────────────────

def _clean(text: str) -> str:
    """Czyści whitespace z tekstu."""
    return re.sub(r"\s+", " ", text).strip()


def _extract_title(soup: BeautifulSoup) -> str:
    """
    Szuka tytułu produktu — priorytet:
    1. og:title (Open Graph meta tag) — najbardziej wiarygodny
    2. <h1> — nagłówek strony
    3. page title — zwłaszcza na Allegro, GMarket
    """
    # Open Graph (większość sklepów implementuje)
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        return _clean(og_title["content"])

    # H1 — główny nagłówek
    h1 = soup.find("h1")
    if h1:
        return _clean(h1.get_text())

    # Page title (tag <title>)
    title = soup.find("title")
    if title:
        text = _clean(title.get_text())
        # Zwłaszcza Allegro, GMarket: "nazwa — strona" — bierzemy tylko część
        if " — " in text or " | " in text:
            text = text.split(" — ")[0].split(" | ")[0]
        return text[:200]  # limit na długość

    return ""


def _extract_description(soup: BeautifulSoup) -> str:
    """
    Szuka opisu produktu — priorytet:
    1. og:description (Open Graph meta)
    2. meta description
    3. <p> z opisem
    """
    # Open Graph description
    og_desc = soup.find("meta", property="og:description")
    if og_desc and og_desc.get("content"):
        return _clean(og_desc["content"])

    # Meta description
    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc and meta_desc.get("content"):
        return _clean(meta_desc["content"])

    # Pierwszy <p> (zwłaszcza w sekcji opisowej)
    for p in soup.find_all("p"):
        text = p.get_text()
        if len(text) > 50:  # musi być „rzeczywistym" opisem, nie linkiem
            return _clean(text)[:500]  # limit 500 znaków

    return ""


def _extract_price(soup: BeautifulSoup) -> str:
    """
    Szuka ceny produktu.
    Priorytet: og:price (Open Graph) lub tagi z klasami 'price', 'cena' (regex).
    """
    # Open Graph price
    og_price = soup.find("meta", property="og:price:amount")
    if og_price and og_price.get("content"):
        return _clean(og_price["content"])

    # CSS klasy — szukamy elementów z 'price' w klasie
    price_patterns = [
        soup.find(class_=re.compile("price|cena|cost|rate", re.IGNORECASE)),
        soup.find(class_=re.compile("product-price", re.IGNORECASE)),
    ]
    for elem in price_patterns:
        if elem:
            text = elem.get_text()
            # Wyciągnij pierwszą liczbę (cena)
            match = re.search(r"[\d\s,\.]+", text)
            if match:
                return _clean(match.group())[:30]

    return ""


def _extract_specifications(soup: BeautifulSoup) -> dict[str, str]:
    """
    Wyciąga specyfikacje produktu z tabeli lub listy.
    Szuka: <table>, <dl> (definition list), <ul> z parami klucz-wartość.
    """
    specs = {}

    # Tabela z specyfikacjami (Allegro, GMarket, itp.)
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if len(cells) >= 2:
                key = _clean(cells[0].get_text())
                val = _clean(cells[1].get_text())
                if key and val and len(key) < 80 and len(val) < 200:
                    specs[key] = val

    # Definition list <dl> (semantyczne HTML)
    for dl in soup.find_all("dl"):
        dts = dl.find_all("dt")
        dds = dl.find_all("dd")
        for dt, dd in zip(dts, dds):
            key = _clean(dt.get_text())
            val = _clean(dd.get_text())
            if key and val and len(key) < 80 and len(val) < 200:
                specs[key] = val

    # Lista z ikonami + tekstem (mniej wiarygodne, ale zbieramy)
    for ul in soup.find_all("ul", limit=5):  # tylko pierwsze 5 list
        for li in ul.find_all("li"):
            text = _clean(li.get_text())
            # Jeśli zawiera ':', potraktuj jako klucz:wartość
            if ":" in text:
                parts = text.split(":", 1)
                if len(parts) == 2:
                    key, val = _clean(parts[0]), _clean(parts[1])
                    if key and val and len(key) < 80:
                        specs[key] = val

    return specs


async def scrape_one(
    client: httpx.AsyncClient,
    row: dict,
    dry_run: bool,
    db: firestore.Client | None,
) -> dict:
    """
    Scrapeuje jeden produkt ze strony.
    
    Zwraca dict z:
    - indeks, nazwa, link, komb_id, jdmr_nazwa
    - title, description, specifications, price
    - status ("ok" lub "error"), error message
    - scraped_at (timestamp ISO)
    """
    url = row["link"]
    indeks = row["indeks"]
    log.info("  → %s  %s", indeks, url[:70])

    # Przygotuj wynik z wartościami domyślnymi
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
        # Headers z randomowym User-Agentem
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://www.google.com/",
        }

        # Pobierz stronę HTTP GET (szybko!)
        response = await client.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()  # Wyrzuć wyjątek na 4xx/5xx

        # Parse HTML ze strony
        soup = BeautifulSoup(response.text, "html.parser")

        # Wyciągnij dane — każda funkcja szuka w priorytetach
        result["title"] = _extract_title(soup)
        result["description"] = _extract_description(soup)
        result["price"] = _extract_price(soup)
        result["specifications"] = _extract_specifications(soup)

        # Fallback: jeśli nic się nie wyciągnęło, zbierz tekst strony
        if not result["title"] and not result["description"]:
            result["description"] = _clean(soup.get_text())[:3000]
            result["title"] = url  # At least URL

        result["status"] = "ok"
        log.info("    ✓ Scrapowano: '%s'", result["title"][:60])

    except httpx.TimeoutException:
        result["error"] = "TimeoutError"
        result["status"] = "error"
        log.warning("    ✗ TIMEOUT: %s", url[:50])

    except httpx.HTTPStatusError as exc:
        # 403 Forbidden, 429 Rate Limited, 404 Not Found, itd.
        result["error"] = f"HTTP {exc.response.status_code}"
        result["status"] = "blocked" if exc.response.status_code == 403 else "error"
        log.warning("    ✗ HTTP %d: %s", exc.response.status_code, url[:50])

    except Exception as exc:
        result["error"] = str(exc)[:200]
        result["status"] = "error"
        log.warning("    ✗ BŁĄD: %s — %s", url[:50], type(exc).__name__)

    # Zapisz do Firestore (jeśli nie dry-run)
    if not dry_run and db:
        db.collection(COLLECTION).document(indeks).set(result)

    return result


async def run_scraping(
    rows: list[dict],
    concurrency: int,
    dry_run: bool,
    db: firestore.Client | None,
) -> list[dict]:
    """
    Scrapeuje wszystkie produkty równolegle (async).
    
    Szybkość:
    - Playwright: ~10 produktów/min (musi otworzyć przeglądarkę)
    - httpx+BS4: ~100-200 produktów/min (tylko HTTP GET + parse HTML)
    """
    results = []
    semaphore = asyncio.Semaphore(concurrency)

    async def worker(row: dict):
        """Worker thread — scrapeuje jeden produkt z semaforem."""
        async with semaphore:
            async with httpx.AsyncClient(
                limits=httpx.Limits(keepalive_expiry=5.0),
                follow_redirects=True,
            ) as client:
                result = await scrape_one(client, row, dry_run, db)
                results.append(result)
                # Drobny delay żeby nie robić DDoS
                await asyncio.sleep(random.uniform(0.1, 0.5))

    # Uruchom wszystkie workery równocześnie
    log.info("Startuje scraping %d produktów (concurrency=%d)...", len(rows), concurrency)
    start_time = time.time()
    await asyncio.gather(*[worker(row) for row in rows])
    elapsed = time.time() - start_time

    # Statystyka
    ok_count = sum(1 for r in results if r["status"] == "ok")
    error_count = len(results) - ok_count
    rate = len(results) / elapsed if elapsed > 0 else 0
    log.info(
        "Zakończono: %d OK, %d błędów (%.1f produktów/min)",
        ok_count,
        error_count,
        rate * 60,
    )

    return results


# ──────────────────────────────────────────────
# Główna funkcja CLI
# ──────────────────────────────────────────────

def main():
    """CLI interface do scrapingu — argumenty i logika."""
    parser = argparse.ArgumentParser(
        description="Scrapeuj produkty z CSV → Firestore (httpx + BeautifulSoup)"
    )
    parser.add_argument("--limit", type=int, default=None, help="Scrapeuj tylko N wierszy")
    parser.add_argument(
        "--sample",
        type=int,
        default=None,
        help="Scrapeuj losowych N wierszy (zamiast --limit)",
    )
    parser.add_argument(
        "--domain",
        type=str,
        default=None,
        help="Filtruj tylko domenę (np. allegro.pl)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Pomiń już zescrapowane (status ok/blocked w Firestore)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scrapeuj bez zapisu do Firestore (test)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=DEFAULT_CONCURRENCY,
        help=f"Równoczesne połączenia HTTP (domyślnie {DEFAULT_CONCURRENCY})",
    )

    args = parser.parse_args()

    # Wczytaj CSV
    log.info("Wczytywanie CSV...")
    rows = load_csv()

    # Opcja: resume (pomiń już zescrapowane)
    if args.resume:
        if not args.dry_run:
            db = get_db()
            already_done = already_scraped(db)
            before = len(rows)
            rows = [r for r in rows if r["indeks"] not in already_done]
            log.info("--resume: pominięto %d już zescrapowanych", before - len(rows))
        else:
            log.warning("--resume ignorowany w trybie --dry-run")

    # Opcja: domain (filtruj po domenie)
    if args.domain:
        before = len(rows)
        rows = [r for r in rows if args.domain in urlparse(r["link"]).netloc]
        log.info("--domain %s: %d → %d wierszy", args.domain, before, len(rows))

    # Opcja: sample (losowe)
    if args.sample:
        rows = random.sample(rows, min(args.sample, len(rows)))
        log.info("--sample: losowo wybrano %d wierszy", len(rows))

    # Opcja: limit (pierwsze N)
    elif args.limit:
        rows = rows[: args.limit]
        log.info("--limit: bierzemy %d wierszy", len(rows))

    # Firestore client
    db = None if args.dry_run else get_db()

    # Runuj scraping
    try:
        results = asyncio.run(
            run_scraping(rows, args.concurrency, args.dry_run, db)
        )

        # Podsumowanie
        log.info("\n" + "=" * 60)
        log.info("PODSUMOWANIE")
        log.info("=" * 60)
        ok = [r for r in results if r["status"] == "ok"]
        errors = [r for r in results if r["status"] == "error"]
        blocked = [r for r in results if r["status"] == "blocked"]
        log.info("✓ Sukces (ok):       %d", len(ok))
        if errors:
            log.info("✗ Błędy (error):     %d", len(errors))
        if blocked:
            log.info("🚫 Zablokowane (403, 429): %d", len(blocked))

        if ok:
            log.info("\nPróbka wyników:")
            for r in ok[:3]:
                log.info(
                    "  • %s: '%s' [%d specs]",
                    r["indeks"],
                    r["title"][:60],
                    len(r["specifications"]),
                )

    except KeyboardInterrupt:
        log.info("\nPrzerwano przez użytkownika")
    except Exception as exc:
        log.error("BŁĄD KRYTYCZNY: %s", exc, exc_info=True)
        raise


if __name__ == "__main__":
    main()
