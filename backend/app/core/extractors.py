"""
extractors.py — Ekstrakcja tytułu, opisu i specyfikacji ze stron produktowych.
"""

from __future__ import annotations
import re
from urllib.parse import urlparse

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


# Słowa kluczowe typowe dla koszyka/nawigacji — odrzucamy takie pary
_JUNK_KEYS = re.compile(
    r"(koszyk|cart|wartość|suma|łącznie|rabat|podatek|vat|dostawa|shipping|"
     r"newsletter|copyright|menu|nawigacja|kategori|breadcrumb|sort|filtr|"
     r"zaloguj|zarejestruj|regulamin|polityka|cookie|zgoda|checkbox|button|"
     r"dodaj do|kup teraz|qty|ilość produktów|page|strona główna)",
    re.IGNORECASE,
)

# Nagłówki sekcji specyfikacji
_SPEC_HEADINGS = re.compile(
    r"(specyfikacj|parametr|dane technic|właściwości|charakterystyk|"
     r"specification|technical|features|details|wymiar|rozmiar)",
    re.IGNORECASE,
)


async def _text(page, selector: str, default: str = "") -> str:
    try:
        el = await page.query_selector(selector)
        if el:
            return _clean(await el.inner_text())
    except Exception:
        pass
    return default


async def _all_pairs(page, row_sel: str, cell_sel: str) -> dict[str, str]:
    """Wyciąga pary klucz-wartość z wierszy tabeli/listy."""
    specs: dict[str, str] = {}
    try:
        rows = await page.query_selector_all(row_sel)
        for row in rows:
            cells = await row.query_selector_all(cell_sel)
            texts = [_clean(await c.inner_text()) for c in cells]
            texts = [t for t in texts if t]
            if len(texts) >= 2:
                key, val = texts[0], texts[1]
                if _is_valid_spec(key, val):
                    specs[key] = val
    except Exception:
        pass
    return specs


def _is_valid_spec(key: str, val: str) -> bool:
    """Sprawdza czy para klucz-wartość wygląda jak specyfikacja produktu."""
    if not key or not val:
        return False
    if len(key) > 80 or len(val) > 300:   # za długie klucze = nawigacja/opis
        return False
    if _JUNK_KEYS.search(key):
        return False
    if key == val:                          # duplikaty
        return False
    if re.match(r"^\d+$", key):            # klucz to sama liczba
        return False
    return True


def _merge(*dicts: dict) -> dict:
    """Łączy słowniki, wcześniejsze mają priorytet."""
    result: dict[str, str] = {}
    for d in reversed(dicts):
        result.update(d)
    return result


async def _find_specs_near_heading(page) -> dict[str, str]:
    """Szuka sekcji z nagłówkiem 'specyfikacje/parametry' i wyciąga z niej pary."""
    specs: dict[str, str] = {}
    try:
        headings = await page.query_selector_all("h1, h2, h3, h4, h5, strong, b")
        for h in headings:
            text = _clean(await h.inner_text())
            if _SPEC_HEADINGS.search(text):
                # Szukaj dalszej sekcji — sibling lub parent
                parent = await h.evaluate_handle("el => el.closest('section, div, article, table') || el.parentElement")
                if parent:
                    rows = await parent.query_selector_all("tr, li")
                    for row in rows:
                        cells = await row.query_selector_all("td, th, span, dt, dd")
                        texts = [_clean(await c.inner_text()) for c in cells]
                        texts = [t for t in texts if t]
                        if len(texts) >= 2 and _is_valid_spec(texts[0], texts[1]):
                            specs[texts[0]] = texts[1]
                if specs:
                    break
    except Exception:
        pass
    return specs


async def _dl_specs(page) -> dict[str, str]:
    """Wyciąga specyfikacje z elementów dl/dt/dd."""
    specs: dict[str, str] = {}
    try:
        dls = await page.query_selector_all("dl")
        for dl in dls:
            dts = await dl.query_selector_all("dt")
            dds = await dl.query_selector_all("dd")
            for dt, dd in zip(dts, dds):
                k = _clean(await dt.inner_text())
                v = _clean(await dd.inner_text())
                if _is_valid_spec(k, v):
                    specs[k] = v
    except Exception:
        pass
    return specs


async def _best_description(page) -> str:
    """Zwraca najlepszy opis ze strony."""
    candidates = [
        "[itemprop='description']",
        ".product-description", ".product-desc",
        "[class*='description']", "[class*='desc']",
        "article", ".content", "main",
    ]
    best = ""
    for sel in candidates:
        try:
            els = await page.query_selector_all(sel)
            for el in els:
                t = _clean(await el.inner_text())
                # Odrzuć zbyt krótkie i zbyt długie (prawdop. cała strona)
                if 50 < len(t) < 5000 and len(t) > len(best):
                    best = t
        except Exception:
            pass
    return best[:3000]


# ──────────────────────────────────────────────
# Allegro
# ──────────────────────────────────────────────

async def extract_allegro(page) -> dict:
    result: dict = {}

    # Tytuł
    result["title"] = await _text(page, "h1") or await page.title()

    # Cena
    try:
        price_el = await page.query_selector(
            "[data-testid='price-value'], [aria-label*='Cena'], [class*='price-value']"
        )
        if price_el:
            result["price"] = _clean(await price_el.inner_text())
    except Exception:
        pass

    # Specyfikacje — Allegro używa sekcji "Parametry"
    specs = await _all_pairs(
        page,
        "[data-box-name='Parameters'] li, [data-testid='parameters'] li",
        "span, div",
    )
    if not specs:
        specs = await _find_specs_near_heading(page)
    if not specs:
        specs = await _dl_specs(page)
    result["specifications"] = specs

    # Opis
    desc = await _text(page, "[data-box-name='Description'], [data-testid='description']")
    if not desc:
        desc = await _best_description(page)
    result["description"] = desc[:3000]

    return result


# ──────────────────────────────────────────────
# TME
# ──────────────────────────────────────────────

async def extract_tme(page) -> dict:
    result: dict = {}
    result["title"] = await _text(page, "h1.product-name, .product-title, h1")

    specs = await _all_pairs(page, "#parameters tr, .params-table tr", "td, th")
    if not specs:
        specs = await _find_specs_near_heading(page)
    result["specifications"] = specs

    result["description"] = await _text(
        page, ".product-description, #description, .description-content"
    ) or await _best_description(page)
    return result


# ──────────────────────────────────────────────
# Generic (fallback)
# ──────────────────────────────────────────────

async def extract_generic(page) -> dict:
    result: dict = {}

    result["title"] = await _text(page, "h1") or await page.title()

    # Cena — heurystycznie
    try:
        candidates = await page.query_selector_all(
            "[class*='price'], [itemprop='price'], [class*='Price'], "
            "[data-price], .cena, .price"
        )
        for el in candidates[:5]:
            t = _clean(await el.inner_text())
            if re.search(r"\d[\d\s,.]+\s*(zł|PLN|EUR|USD|€|\$)", t, re.IGNORECASE) and len(t) < 30:
                result["price"] = t
                break
    except Exception:
        pass

    # Specyfikacje — w kolejności priorytetu
    specs = await _find_specs_near_heading(page)
    if not specs:
        specs = await _dl_specs(page)
    if not specs:
        # Tabele — tylko z więcej niż 2 wierszami (odrzuca mini-tabelki koszyka)
        all_specs: dict[str, str] = {}
        try:
            tables = await page.query_selector_all("table")
            for table in tables:
                rows = await table.query_selector_all("tr")
                if len(rows) < 3:   # za mała tabelka — raczej nie spec
                    continue
                candidate: dict[str, str] = {}
                for row in rows:
                    cells = await row.query_selector_all("td, th")
                    texts = [_clean(await c.inner_text()) for c in cells]
                    texts = [t for t in texts if t]
                    if len(texts) == 2 and _is_valid_spec(texts[0], texts[1]):
                        candidate[texts[0]] = texts[1]
                # Uznaj tabelę za spec tylko jeśli >= 2 par pasuje
                if len(candidate) >= 2:
                    all_specs.update(candidate)
        except Exception:
            pass
        specs = all_specs

    result["specifications"] = specs

    result["description"] = await _best_description(page)
    if not result["description"]:
        # Ostateczny fallback: tekst body
        try:
            body = await page.evaluate("() => document.body?.innerText || ''")
            result["description"] = _clean(body)[:2000]
        except Exception:
            pass

    return result


# ──────────────────────────────────────────────
# Dispatch
# ──────────────────────────────────────────────

_EXTRACTORS = {
    "allegro.pl": extract_allegro,
    "tme.eu": extract_tme,
}


async def extract(page, url: str) -> dict:
    domain = urlparse(url).netloc.lower().removeprefix("www.")
    fn = _EXTRACTORS.get(domain, extract_generic)
    return await fn(page)
