"""
dashboard.py — Streamlit dashboard do przeglądania maili i danych scrapowanych.

Uruchomienie:
    streamlit run dashboard.py
"""

import asyncio
import html as html_module
import os
import random

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

from app.core.search import search as _qdrant_search, get_model, get_reranker

# ──────────────────────────────────────────────
# Konfiguracja
# ──────────────────────────────────────────────
COLLECTION = "emails"
PRODUCTS_COLLECTION = "product_scrapes"
GCS_BUCKET_NAME = "projekt-email-attachments"

st.set_page_config(
    page_title="IndeksyGSR",
    page_icon="📧",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ──────────────────────────────────────────────
# CSS
# ──────────────────────────────────────────────
st.markdown("""
<style>
    [data-testid="stSidebar"] { background: #1a1a2e; }
    [data-testid="stSidebar"] * { color: #e0e0f0 !important; }

    /* Sticky prawa kolumna */
    div[data-testid="stHorizontalBlock"] > div:nth-child(2) > div {
        position: sticky;
        top: 3.5rem;
        max-height: calc(100vh - 4.5rem);
        overflow-y: auto;
        padding-right: 4px;
    }

    .badge {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 20px;
        font-size: 0.75rem;
        font-weight: 600;
        margin-right: 4px;
    }
    .badge-url  { background:#0f3460; color:#4cc9f0; }
    .badge-att  { background:#2d0f60; color:#c77dff; }
    .badge-ok   { background:#0f3d20; color:#4caf79; }
    .badge-err  { background:#3d0f0f; color:#f44336; }
    .badge-spec { background:#1a3040; color:#a8dadc; }

    .url-chip {
        display: inline-block;
        background: #0f3460;
        color: #4cc9f0;
        border-radius: 6px;
        padding: 3px 10px;
        font-size: 0.8rem;
        margin: 2px;
        word-break: break-all;
    }
    .url-chip a { color: #4cc9f0; text-decoration: none; }
    .url-chip a:hover { text-decoration: underline; }

    .detail-box {
        background: #0d1117;
        border: 1px solid #30363d;
        border-radius: 8px;
        padding: 1rem 1.2rem;
        white-space: pre-wrap;
        font-family: monospace;
        font-size: 0.85rem;
        max-height: 380px;
        overflow-y: auto;
        color: #c9d1d9;
    }

    .att-row {
        display: flex;
        align-items: center;
        gap: 10px;
        background: #161b22;
        border: 1px solid #30363d;
        border-radius: 8px;
        padding: 8px 12px;
        margin: 4px 0;
    }
    .att-row a { color: #c77dff; font-weight: 600; text-decoration: none; }
    .att-row a:hover { text-decoration: underline; }
    .att-size { color: #8b949e; font-size: 0.8rem; }

    .spec-table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
    .spec-table tr:nth-child(even) { background: #161b22; }
    .spec-table td { padding: 4px 8px; border-bottom: 1px solid #21262d; vertical-align: top; }
    .spec-table td:first-child { color: #8b949e; width: 40%; }
    .spec-table td:last-child { color: #e6edf3; }

    .product-card {
        background: #161b22;
        border: 1px solid #30363d;
        border-radius: 10px;
        padding: 1rem 1.2rem;
        margin-bottom: 0.5rem;
    }
</style>
""", unsafe_allow_html=True)

# ──────────────────────────────────────────────
# GCP klienty
# ──────────────────────────────────────────────

@st.cache_resource
def get_db():
    from app.services.firestore import get_client
    return get_client()


@st.cache_resource
def get_storage():
    from app.services.gcs import get_client
    return get_client()


@st.cache_data(ttl=3600)
def get_signed_url(gcs_path: str) -> str:
    client = get_storage()
    blob = client.bucket(GCS_BUCKET_NAME).blob(gcs_path)
    return blob.generate_signed_url(expiration=timedelta(hours=1), method="GET", version="v4")

# ──────────────────────────────────────────────
# Dane z Firestore
# ──────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_emails() -> pd.DataFrame:
    db = get_db()
    rows = []
    for doc in db.collection(COLLECTION).stream():
        d = doc.to_dict()
        rows.append({
            "id":              d.get("id", doc.id),
            "pst_source":      d.get("pst_source", ""),
            "subject":         d.get("subject", "(brak tematu)"),
            "sender":          d.get("sender", ""),
            "date":            d.get("date", ""),
            "body_text":       d.get("body_text", ""),
            "signature":       d.get("signature", ""),
            "shop_urls":       d.get("shop_urls", []),
            "has_attachments": d.get("has_attachments", False),
            "attachments":     d.get("attachments", []),
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df["date_parsed"] = pd.to_datetime(df["date"], errors="coerce", utc=True)
        df = df.sort_values("date_parsed", ascending=False, na_position="last")
    return df


@st.cache_data(ttl=60)
def load_products() -> pd.DataFrame:
    db = get_db()
    rows = []
    for doc in db.collection(PRODUCTS_COLLECTION).stream():
        d = doc.to_dict()
        rows.append({
            "indeks":         doc.id,
            "nazwa":          d.get("nazwa", ""),
            "link":           d.get("link", ""),
            "title":          d.get("title", ""),
            "description":    d.get("description", ""),
            "specifications": d.get("specifications", {}),
            "price":          d.get("price", ""),
            "status":         d.get("status", ""),
            "scraped_at":     d.get("scraped_at", ""),
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df["has_specs"] = df["specifications"].apply(lambda x: bool(x))
        df["spec_count"] = df["specifications"].apply(lambda x: len(x) if x else 0)
    return df

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def fmt_date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d.%m.%Y %H:%M")
    except Exception:
        return iso or "—"

# ──────────────────────────────────────────────
# Widok MAILE
# ──────────────────────────────────────────────

def sidebar_filters_emails(df: pd.DataFrame) -> pd.DataFrame:
    st.sidebar.markdown("---")
    search    = st.sidebar.text_input("🔍 Szukaj (temat / nadawca / treść)", "")
    only_urls = st.sidebar.checkbox("Tylko z linkami sklepów")
    only_att  = st.sidebar.checkbox("Tylko z załącznikami PDF")
    sources = sorted(df["pst_source"].dropna().unique().tolist())
    if len(sources) > 1:
        sel = st.sidebar.multiselect("Plik PST", sources, default=sources)
        df = df[df["pst_source"].isin(sel)]
    if only_urls:
        df = df[df["shop_urls"].apply(len) > 0]
    if only_att:
        df = df[df["has_attachments"]]
    if search:
        mask = (
            df["subject"].str.contains(search, case=False, na=False)
            | df["sender"].str.contains(search, case=False, na=False)
            | df["body_text"].str.contains(search, case=False, na=False)
        )
        df = df[mask]
    return df


def email_list(df: pd.DataFrame):
    for _, row in df.iterrows():
        badges = ""
        if row["shop_urls"]:
            badges += f'<span class="badge badge-url">🔗 {len(row["shop_urls"])} URL</span>'
        if row["has_attachments"]:
            badges += f'<span class="badge badge-att">📎 {len(row["attachments"])} PDF</span>'

        c0, c1, c2 = st.columns([6, 2, 1])
        with c0:
            st.markdown(
                f'<div style="font-weight:600">{html_module.escape(row["subject"] or "(brak tematu)")}</div>'
                f'<div style="color:#8b949e;font-size:.85rem">{html_module.escape(row["sender"])}</div>',
                unsafe_allow_html=True,
            )
        with c1:
            st.markdown(
                f'<div style="color:#8b949e;font-size:.85rem;text-align:right">{fmt_date(row["date"])}</div>',
                unsafe_allow_html=True,
            )
        with c2:
            if st.button("👁", key=f"btn_{row['id']}", help="Podgląd maila"):
                st.session_state["selected"] = row["id"]
        if badges:
            st.markdown(f'<div style="margin:2px 0 6px">{badges}</div>', unsafe_allow_html=True)
        st.divider()


def email_detail(df: pd.DataFrame):
    sel_id = st.session_state.get("selected")
    if not sel_id:
        st.info("Kliknij 👁 przy mailu żeby zobaczyć szczegóły.")
        return
    rows = df[df["id"] == sel_id]
    if rows.empty:
        st.warning("Mail nie znaleziony.")
        return
    row = rows.iloc[0]

    if st.button("✖ Zamknij"):
        del st.session_state["selected"]
        st.rerun()

    st.subheader(row["subject"] or "(brak tematu)")
    c1, c2 = st.columns(2)
    c1.markdown(f"**Nadawca:** {html_module.escape(row['sender'])}")
    c1.markdown(f"**Data:** {fmt_date(row['date'])}")
    c2.markdown(f"**Plik PST:** `{row['pst_source']}`")
    st.markdown("---")

    st.markdown("**📄 Treść maila**")
    body_escaped = html_module.escape(row["body_text"] or "(brak treści)")
    st.markdown(f'<div class="detail-box">{body_escaped}</div>', unsafe_allow_html=True)

    if row.get("signature"):
        with st.expander("📋 Stopka / podpis", expanded=False):
            sig_escaped = html_module.escape(row["signature"])
            st.markdown(f'<div class="detail-box" style="max-height:200px">{sig_escaped}</div>',
                        unsafe_allow_html=True)

    if row["shop_urls"]:
        st.markdown("---")
        st.markdown(f"**🔗 Linki do sklepów ({len(row['shop_urls'])})**")
        chips = "".join(
            f'<span class="url-chip"><a href="{u}" target="_blank">{html_module.escape(u)}</a></span>'
            for u in row["shop_urls"]
        )
        st.markdown(chips, unsafe_allow_html=True)

    if row["has_attachments"] and row["attachments"]:
        st.markdown("---")
        st.markdown(f"**📎 Załączniki PDF ({len(row['attachments'])})**")
        for att in row["attachments"]:
            fname = att.get("filename", "plik.pdf")
            size  = att.get("size_bytes", 0)
            size_str = f"{size / 1024:.1f} KB" if size else ""
            gcs_path = att.get("gcs_path", "")
            if gcs_path:
                try:
                    url = get_signed_url(gcs_path)
                    link_html = f'<a href="{url}" target="_blank">⬇ {html_module.escape(fname)}</a>'
                except Exception:
                    link_html = html_module.escape(fname)
            else:
                link_html = html_module.escape(fname)
            st.markdown(
                f'<div class="att-row">{link_html}<span class="att-size">{size_str}</span></div>',
                unsafe_allow_html=True,
            )


def view_emails():
    df_all = load_emails()
    if df_all.empty:
        st.error("Brak danych w Firestore. Uruchom najpierw `python parse_email.py`.")
        return

    df = sidebar_filters_emails(df_all)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("📧 Maile", len(df),
              delta=f"z {len(df_all)} łącznie" if len(df) != len(df_all) else None)
    m2.metric("🔗 Z linkami", df["shop_urls"].apply(len).gt(0).sum())
    m3.metric("📎 Z PDF-ami", df["has_attachments"].sum())
    m4.metric("🌐 Unikalnych URL-i", len({u for urls in df["shop_urls"] for u in urls}))
    st.markdown("---")

    if st.session_state.get("selected"):
        left, right = st.columns([2, 3])
        with left:
            st.markdown(f"### {len(df)} wiadomości")
            email_list(df)
        with right:
            st.markdown("### Szczegóły")
            email_detail(df)
    else:
        st.markdown(f"### {len(df)} wiadomości")
        email_list(df)

# ──────────────────────────────────────────────
# Widok PRODUKTY
# ──────────────────────────────────────────────

def spec_table_html(specs: dict) -> str:
    if not specs:
        return "<em style='color:#8b949e'>Brak specyfikacji</em>"
    rows = "".join(
        f"<tr><td>{html_module.escape(str(k))}</td>"
        f"<td>{html_module.escape(str(v))}</td></tr>"
        for k, v in specs.items()
    )
    return f'<table class="spec-table">{rows}</table>'


def product_detail(row: pd.Series):
    if st.button("✖ Zamknij produkt", key="close_prod"):
        del st.session_state["selected_product"]
        st.rerun()

    status_badge = (
        '<span class="badge badge-ok">✅ ok</span>'
        if row["status"] == "ok"
        else '<span class="badge badge-err">❌ błąd</span>'
    )
    st.markdown(f"### {html_module.escape(row['title'] or row['nazwa'])} {status_badge}",
                unsafe_allow_html=True)

    c1, c2, c3 = st.columns(3)
    c1.markdown(f"**Indeks:** `{row['indeks']}`")
    c2.markdown(f"**Cena:** {row['price'] or '—'}")
    c3.markdown(f"**Scraped:** {fmt_date(row['scraped_at'])}")
    st.markdown(
        f"🔗 [Otwórz stronę produktu]({row['link']})", unsafe_allow_html=False
    )

    st.markdown("---")

    # Specyfikacje
    st.markdown(f"**⚙️ Specyfikacje ({row['spec_count']})**")
    st.markdown(spec_table_html(row["specifications"]), unsafe_allow_html=True)

    # Opis
    if row["description"]:
        st.markdown("---")
        st.markdown("**📄 Opis produktu**")
        desc_escaped = html_module.escape(row["description"])
        st.markdown(f'<div class="detail-box">{desc_escaped}</div>', unsafe_allow_html=True)


def view_products():
    df = load_products()
    if df.empty:
        st.warning("Brak danych scrapowanych. Uruchom najpierw `python scrape.py`.")
        return

    # Filtry w sidebarze
    st.sidebar.markdown("---")
    search = st.sidebar.text_input("🔍 Szukaj (indeks / nazwa)", "")
    only_specs = st.sidebar.checkbox("Tylko z specyfikacjami")
    only_ok = st.sidebar.checkbox("Tylko poprawnie zescrapowane", value=True)

    df_f = df.copy()
    if only_ok:
        df_f = df_f[df_f["status"] == "ok"]
    if only_specs:
        df_f = df_f[df_f["has_specs"]]
    if search:
        mask = (
            df_f["indeks"].str.contains(search, case=False, na=False)
            | df_f["nazwa"].str.contains(search, case=False, na=False)
            | df_f["title"].str.contains(search, case=False, na=False)
        )
        df_f = df_f[mask]

    # Metryki
    ok_count   = (df["status"] == "ok").sum()
    err_count  = (df["status"] == "error").sum()
    spec_count = df["has_specs"].sum()

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("📦 Produkty", len(df_f),
              delta=f"z {len(df)} łącznie" if len(df_f) != len(df) else None)
    m2.metric("✅ Poprawnie", ok_count)
    m3.metric("❌ Błędy", err_count)
    m4.metric("⚙️ Ze spec.", spec_count)
    st.markdown("---")

    sel_id = st.session_state.get("selected_product")
    if sel_id:
        rows = df_f[df_f["indeks"] == sel_id]
        if not rows.empty:
            left, right = st.columns([2, 3])
            with left:
                _product_list(df_f)
            with right:
                st.markdown("### Szczegóły produktu")
                product_detail(rows.iloc[0])
            return

    st.markdown(f"### {len(df_f)} produktów")
    _product_list(df_f)


def _product_list(df: pd.DataFrame):
    for _, row in df.iterrows():
        status_badge = (
            '<span class="badge badge-ok">✅</span>'
            if row["status"] == "ok"
            else '<span class="badge badge-err">❌</span>'
        )
        spec_badge = (
            f'<span class="badge badge-spec">⚙️ {row["spec_count"]}</span>'
            if row["spec_count"] > 0 else ""
        )
        price_str = f" · <b>{html_module.escape(row['price'])}</b>" if row["price"] else ""

        c0, c1 = st.columns([7, 1])
        with c0:
            st.markdown(
                f'{status_badge} {spec_badge} '
                f'<span style="font-weight:600">{html_module.escape(row["title"] or row["nazwa"] or row["indeks"])}</span>'
                f'<div style="color:#8b949e;font-size:.8rem">'
                f'`{html_module.escape(row["indeks"])}` {price_str}</div>',
                unsafe_allow_html=True,
            )
        with c1:
            if st.button("👁", key=f"prod_{row['indeks']}", help="Podgląd produktu"):
                st.session_state["selected_product"] = row["indeks"]
        st.divider()

# ──────────────────────────────────────────────
# Wyszukiwanie semantyczne (BGE-M3 + Qdrant)
# ──────────────────────────────────────────────

@st.cache_resource
def get_search_model():
    return get_model()


@st.cache_resource
def _get_qdrant():
    try:
        from app.services.qdrant import get_client
        return get_client()
    except RuntimeError:
        return None


def _toggle_search_selection(item_id: str, key: str) -> None:
    """Callback aktualizujący zestaw zaznaczonych wyników przy zmianie checkboxa."""
    if st.session_state[key]:
        st.session_state["search_selections"].add(item_id)
    else:
        st.session_state["search_selections"].discard(item_id)


def view_search():
    st.markdown("## 🔍 Wyszukiwanie semantyczne indeksów")

    qdrant = _get_qdrant()
    if qdrant is None:
        st.error("Brak konfiguracji Qdrant. Dodaj `QDRANT_URL` i `QDRANT_API_KEY` do pliku `.env`.")
        return

    # Pre-load modelu przy pierwszym otwarciu zakładki
    if "search_model_ready" not in st.session_state:
        with st.spinner("Ładowanie modelu BGE-M3 (pierwsze uruchomienie, ~30s)..."):
            get_search_model()
        st.session_state["search_model_ready"] = True

    # Inicjalizacja stanu zaznaczenia
    if "search_selections" not in st.session_state:
        st.session_state["search_selections"] = set()

    col1, col2, col3 = st.columns([5, 1, 2])
    with col1:
        query = st.text_input(
            "Opis produktu",
            placeholder="np. śruby M20 ocynkowane ogniowo",
            label_visibility="collapsed",
        )
    with col2:
        top_k = st.selectbox("Top", [5, 10, 20], index=1, label_visibility="collapsed")
    with col3:
        use_reranker = st.checkbox("Cross-encoder reranking", value=False)

    if not query:
        st.info("Wpisz opis produktu aby wyszukać pasujące indeksy materiałowe.")
        return

    spinner_msg = "Wyszukiwanie + reranking..." if use_reranker else "Wyszukiwanie..."
    with st.spinner(spinner_msg):
        try:
            results = _qdrant_search(query, top_k=top_k, rerank=use_reranker)
        except Exception as e:
            st.error(f"Błąd wyszukiwania: {e}")
            return

    if not results:
        st.warning("Brak wyników. Sprawdź czy kolekcja Qdrant jest zwektoryzowana (`python vectorize.py`).")
        return

    # Nagłówek wyników z licznikiem zaznaczonych
    header_col1, header_col2 = st.columns([7, 3])
    with header_col1:
        st.markdown(f"**{len(results)} wyników** dla: *{html_module.escape(query)}*")
    with header_col2:
        num_selected = len(st.session_state["search_selections"])
        if num_selected > 0:
            st.markdown(
                f'<div style="text-align:right;color:#4cc9f0;font-weight:600">✓ {num_selected} zaznaczonych</div>',
                unsafe_allow_html=True,
            )
    st.markdown("---")

    # CSS dla zaznaczonych wierszy
    st.markdown(
        """
        <style>
        .search-result-selected {
            border-left: 4px solid #4cc9f0;
            background-color: #1a2744;
            padding-left: 8px;
            border-radius: 4px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    for i, r in enumerate(results, 1):
        item_id = r["indeks"]
        is_selected = item_id in st.session_state["search_selections"]
        score_pct = min(int(r["score"] * 100), 100)

        row_style = "search-result-selected" if is_selected else ""
        c_check, c_info, c_score = st.columns([0.8, 8.2, 2])

        with c_check:
            cb_key = f"sel_{item_id}"
            st.checkbox(
                label="",
                value=is_selected,
                key=cb_key,
                label_visibility="collapsed",
                on_change=_toggle_search_selection,
                args=(item_id, cb_key),
            )

        with c_info:
            st.markdown(
                f'<div class="{row_style}">'
                f'<span style="color:#4cc9f0;font-weight:700;margin-right:8px">{i}.</span>'
                f'<span style="font-weight:600">{html_module.escape(r["nazwa"])}</span>'
                f'<div style="color:#8b949e;font-size:.8rem;margin-top:2px">'
                f'<code>{html_module.escape(r["indeks"])}</code>'
                f' · {html_module.escape(r["jdmr_nazwa"])}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        with c_score:
            st.progress(score_pct, text=f"score: {r['score']}")

        st.divider()

    # Przyciski akcji – widoczne tylko gdy coś zaznaczono
    if st.session_state["search_selections"]:
        st.markdown("---")
        results_by_id = {r["indeks"]: r for r in results}
        btn_col1, btn_col2, btn_col3 = st.columns(3)

        with btn_col1:
            if st.button("🔍 Wyświetl szczegóły", use_container_width=True):
                selected_ids = sorted(st.session_state["search_selections"])
                st.markdown("**Zaznaczone indeksy:**")
                for idx in selected_ids:
                    matched = results_by_id.get(idx)
                    if matched:
                        st.markdown(
                            f'- `{html_module.escape(matched["indeks"])}` – '
                            f'{html_module.escape(matched["nazwa"])}'
                        )
                    else:
                        st.markdown(f"- `{html_module.escape(idx)}`")

        with btn_col2:
            if st.button("📋 Skopiuj do schowka", use_container_width=True):
                selected_ids = sorted(st.session_state["search_selections"])
                clipboard_text = "\n".join(selected_ids)
                st.code(clipboard_text, language=None)
                st.info("Skopiuj powyższy tekst do schowka (Ctrl+A, Ctrl+C).")

        with btn_col3:
            if st.button("✖ Wyczyść zaznaczenia", use_container_width=True):
                st.session_state["search_selections"] = set()
                st.rerun()


# ──────────────────────────────────────────────
# Wyszukiwanie po URL sklepu
# ──────────────────────────────────────────────

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.3 Safari/605.1.15",
]


async def _async_scrape_url(url: str) -> dict:
    from playwright.async_api import async_playwright, TimeoutError as PWTimeout  # noqa: PLC0415
    from app.core.extractors import extract  # noqa: PLC0415

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1280, "height": 800}, locale="pl-PL")
        page = await ctx.new_page()
        await page.set_extra_http_headers({
            "User-Agent": random.choice(_USER_AGENTS),
            "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8",
        })
        try:
            await page.goto(url, timeout=30_000, wait_until="load")
            await page.wait_for_timeout(2000)
            extracted = await extract(page, url)
            if not extracted.get("title") and not extracted.get("description"):
                body = await page.evaluate("() => document.body?.innerText || ''")
                extracted["description"] = body[:3000].strip()
                extracted["title"] = (await page.title()) or ""
        finally:
            await browser.close()
    return extracted


def _scrape_url(url: str) -> dict:
    return asyncio.run(_async_scrape_url(url))


def _build_query_from_scraped(data: dict) -> str:
    parts = []
    if data.get("title"):
        parts.append(data["title"])
    specs = data.get("specifications") or {}
    if specs:
        parts.append(" ".join(f"{k} {v}" for k, v in list(specs.items())[:20]))
    if data.get("description"):
        parts.append(data["description"][:500])
    return " ".join(parts)[:1000]


def view_search_by_url():
    st.markdown("## 🌐 Wyszukiwanie po URL sklepu")

    qdrant = _get_qdrant()
    if qdrant is None:
        st.error("Brak konfiguracji Qdrant. Dodaj `QDRANT_URL` i `QDRANT_API_KEY` do pliku `.env`.")
        return

    if "search_model_ready" not in st.session_state:
        with st.spinner("Ładowanie modelu BGE-M3 (pierwsze uruchomienie, ~30s)..."):
            get_search_model()
        st.session_state["search_model_ready"] = True

    col1, col2, col3 = st.columns([5, 1, 2])
    with col1:
        url = st.text_input(
            "URL produktu",
            placeholder="np. https://allegro.pl/oferta/...",
            label_visibility="collapsed",
        )
    with col2:
        top_k = st.selectbox("Top", [5, 10, 20], index=1, label_visibility="collapsed", key="url_top_k")
    with col3:
        use_reranker = st.checkbox("Cross-encoder reranking", value=False, key="url_reranker")

    if not url or not url.startswith("http"):
        st.info("Wklej link do produktu w sklepie internetowym.")
        return

    scrape_key = f"scraped_{url}"
    if st.button("🔍 Scrapuj i wyszukaj"):
        with st.spinner("Scrapowanie strony..."):
            try:
                scraped = _scrape_url(url)
                st.session_state[scrape_key] = scraped
            except Exception as e:
                st.error(f"Błąd scrapowania: {e}")
                return

    if scrape_key not in st.session_state:
        return

    scraped = st.session_state[scrape_key]

    with st.expander("📄 Dane ze strony", expanded=False):
        if scraped.get("title"):
            st.markdown(f"**Tytuł:** {scraped['title']}")
        if scraped.get("price"):
            st.markdown(f"**Cena:** {scraped['price']}")
        if scraped.get("specifications"):
            st.markdown("**Specyfikacje:**")
            for k, v in scraped["specifications"].items():
                st.markdown(f"- {k}: {v}")
        if scraped.get("description"):
            st.markdown(f"**Opis (fragment):** {scraped['description'][:300]}...")

    query = _build_query_from_scraped(scraped)
    if not query.strip():
        st.warning("Nie udało się wyciągnąć danych ze strony.")
        return

    spinner_msg = "Wyszukiwanie + reranking..." if use_reranker else "Wyszukiwanie w Qdrant..."
    with st.spinner(spinner_msg):
        try:
            results = _qdrant_search(query, top_k=top_k, rerank=use_reranker)
        except Exception as e:
            st.error(f"Błąd wyszukiwania: {e}")
            return

    if not results:
        st.warning("Brak wyników.")
        return

    st.markdown(f"**{len(results)} pasujących indeksów**")
    st.markdown("---")

    for i, r in enumerate(results, 1):
        score_pct = min(int(r["score"] * 100), 100)
        c1, c2 = st.columns([9, 2])
        with c1:
            st.markdown(
                f'<span style="color:#4cc9f0;font-weight:700;margin-right:8px">{i}.</span>'
                f'<span style="font-weight:600">{html_module.escape(r["nazwa"])}</span>'
                f'<div style="color:#8b949e;font-size:.8rem;margin-top:2px">'
                f'<code>{html_module.escape(r["indeks"])}</code>'
                f' · {html_module.escape(r["jdmr_nazwa"])}</div>',
                unsafe_allow_html=True,
            )
        with c2:
            st.progress(score_pct, text=f"score: {r['score']}")
        st.divider()


# ──────────────────────────────────────────────
# Główna aplikacja
# ──────────────────────────────────────────────

def main():
    # Nawigacja
    st.sidebar.title("IndeksyGSR")
    view = st.sidebar.radio(
        "Widok",
        ["📧 Maile", "📦 Produkty (scraping)", "🔍 Wyszukiwanie", "🌐 Po URL sklepu"],
        label_visibility="collapsed",
    )

    st.sidebar.markdown("---")
    if st.sidebar.button("🔄 Odśwież dane"):
        st.cache_data.clear()
        st.rerun()

    if view == "📧 Maile":
        view_emails()
    elif view == "📦 Produkty (scraping)":
        view_products()
    elif view == "🔍 Wyszukiwanie":
        view_search()
    else:
        view_search_by_url()


if __name__ == "__main__":
    main()
