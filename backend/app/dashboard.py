"""
dashboard.py — Streamlit dashboard do przeglądania maili i danych scrapowanych.

Uruchomienie:
    streamlit run dashboard.py
"""

import asyncio
import html as html_module
import os
import random
import sys
import json

import platform
import subprocess

from playwright.sync_api import ViewportSize

from app.pipeline.enums import BotSecuredPages
from app.pipeline.scrape import human_delay
from app.pipeline.scrape import human_scroll

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
from datetime import datetime, timedelta

# Apply nest_asyncio early to fix Windows asyncio subprocess issues
try:
    import nest_asyncio
    nest_asyncio.apply()
except RuntimeError:
    pass

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


@st.cache_data(show_spinner=False)
def _load_segment_tree():
    from app.pipeline.vectorize import load_slownik
    from app.core.suggest import build_segment_tree
    return build_segment_tree(load_slownik())


def _suggest_new_index(query: str, results: list[dict]) -> None:
    from app.core.suggest import suggest_segments

    st.markdown("### Propozycja nowego indeksu")

    with st.spinner("Ładowanie drzewa segmentów..."):
        tree = _load_segment_tree()

    model = get_search_model()

    with st.spinner("Szukam pasujących segmentów (1-3)..."):
        proposals = suggest_segments(query, tree, model, top_n=1)

    best = proposals[0] if proposals else None

    # Defaulty poz. 4-6 z najlepszego wyniku wyszukiwania
    top_result = results[0] if results else {}
    default_seg4 = top_result.get("seg4", "0") or "0"
    default_seg5 = top_result.get("seg5", "0") or "0"
    default_seg6 = top_result.get("seg6", "0") or "0"

    st.markdown("**Pozycje 1–3** — dobrane automatycznie (możesz zmienić):")
    col1, col2, col3 = st.columns(3)

    seg1_opts = sorted(set(tree.pos1.values()))
    with col1:
        def_idx1 = seg1_opts.index(best.seg1_text) if best and best.seg1_text in seg1_opts else 0
        sel1 = st.selectbox("Typ indeksu (poz. 1)", seg1_opts, index=def_idx1, key="sug_seg1")

    seg1_slit_id = next((k for k, v in tree.pos1.items() if v == sel1), None)
    seg2_children = tree.pos2_by_parent.get(seg1_slit_id, []) if seg1_slit_id else []
    seg2_opts = sorted(set(t for _, t in seg2_children))

    with col2:
        def_idx2 = seg2_opts.index(best.seg2_text) if best and best.seg2_text in seg2_opts else 0
        sel2 = st.selectbox("Grupa (poz. 2)", seg2_opts or ["—"], index=def_idx2, key="sug_seg2")

    seg2_slit_id = next((sid for sid, t in seg2_children if t == sel2), None)
    seg3_children = tree.pos3_by_parent.get(seg2_slit_id, []) if seg2_slit_id else []
    seg3_opts = sorted(set(t for _, t in seg3_children))

    with col3:
        def_idx3 = seg3_opts.index(best.seg3_text) if best and best.seg3_text in seg3_opts else 0
        sel3 = st.selectbox("Podgrupa (poz. 3)", seg3_opts or ["—"], index=def_idx3, key="sug_seg3")

    st.markdown("**Pozycje 4–6** — kody techniczne (domyślnie z najlepszego wyniku):")
    col4, col5, col6 = st.columns(3)

    pos4_opts = ["0"] + tree.pos4_values
    pos5_opts = ["0"] + tree.pos5_values
    pos6_opts = ["0"] + tree.pos6_values

    with col4:
        def_idx4 = pos4_opts.index(default_seg4) if default_seg4 in pos4_opts else 0
        sel4 = st.selectbox("Cecha główna (poz. 4)", pos4_opts, index=def_idx4, key="sug_seg4")
    with col5:
        def_idx5 = pos5_opts.index(default_seg5) if default_seg5 in pos5_opts else 0
        sel5 = st.selectbox("Materiał (poz. 5)", pos5_opts, index=def_idx5, key="sug_seg5")
    with col6:
        def_idx6 = pos6_opts.index(default_seg6) if default_seg6 in pos6_opts else 0
        sel6 = st.selectbox("Odbiór (poz. 6)", pos6_opts, index=def_idx6, key="sug_seg6")

    seg3_slit_id = next((sid for sid, t in seg3_children if t == sel3), None)

    # Buduj kod indeksu z KOD_WAROSC dla poz. 1-3 i wartości dla poz. 4-6
    kod1 = tree.pos1_kod.get(seg1_slit_id, "") if seg1_slit_id else ""
    kod2 = tree.pos2_kod.get(seg2_slit_id, "") if seg2_slit_id else ""
    kod3 = tree.pos3_kod.get(seg3_slit_id, "") if seg3_slit_id else ""
    index_code = f"{kod1}-{kod2}-{kod3}-{sel4}-{sel5}-{sel6}-"

    st.markdown(f"**Kod indeksu:** `{index_code}`")

    # Auto-aktualizacja nazwy przy zmianie segmentów
    auto_name = " ".join(s for s in [sel1, sel2, sel3, sel4, sel5, sel6] if s and s != "0").upper()
    if st.session_state.get("sug_last_auto") != auto_name:
        st.session_state["sug_nazwa"] = auto_name
        st.session_state["sug_last_auto"] = auto_name
    nazwa = st.text_input("Nazwa nowego indeksu (NAZWA)", key="sug_nazwa")

    if st.button("💾 Zapisz propozycję do bazy", key="sug_save"):
        db = get_db()
        if db:
            db.collection("proposed_indexes").add({
                "query": query,
                "indeks": index_code,
                "seg1": sel1, "seg2": sel2, "seg3": sel3,
                "seg4": sel4, "seg5": sel5, "seg6": sel6,
                "kod1": kod1, "kod2": kod2, "kod3": kod3,
                "nazwa": nazwa,
                "proposed_at": datetime.utcnow().isoformat(),
                "status": "proposed",
            })
            st.success(f"Propozycja `{index_code}` zapisana w Firestore (kolekcja: proposed_indexes).")
        else:
            st.warning("Brak połączenia z Firestore — propozycja nie została zapisana.")

def _update_pomocniczy_vector(query: str, sel_results: list[dict]) -> None:
    """Aktualizuje wektor 'pomocniczy' w Qdrant dla zaznaczonych indeksów — treść = query użytkownika."""
    qdrant = _get_qdrant()
    if qdrant is None:
        return
    model = get_search_model()
    output = model.encode(
        [query],
        return_dense=True,
        return_sparse=False,
        return_colbert_vecs=False,
    )
    vec = output["dense_vecs"][0].tolist()

    from qdrant_client import models as qmodels
    points = [
        qmodels.PointVectors(
            id=r["qdrant_id"],
            vector={"pomocniczy": vec},
        )
        for r in sel_results
        if r.get("qdrant_id") is not None
    ]
    if points:
        qdrant.update_vectors(collection_name="indeksy", points=points)
        
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
        use_reranker = st.checkbox("Cross-encoder reranking", value=True)

    if not query:
        st.info("Wpisz opis produktu aby wyszukać pasujące indeksy materiałowe.")
        return

    spinner_msg = "Wyszukiwanie + reranking..." if use_reranker else "Wyszukiwanie..."
    _cache_key = f"_search_results_{query}_{top_k}_{use_reranker}"
    if _cache_key not in st.session_state:
        with st.spinner(spinner_msg):
            try:
                st.session_state[_cache_key] = _qdrant_search(query, top_k=top_k, rerank=use_reranker)
            except Exception as e:
                st.error(f"Błąd wyszukiwania: {e}")
                return
    results = st.session_state[_cache_key]

    if not results:
        st.warning("Brak wyników. Sprawdź czy kolekcja Qdrant jest zwektoryzowana (`python vectorize.py`).")
        return

    st.markdown(f"**{len(results)} wyników** dla: *{html_module.escape(query)}*")
    st.markdown("---")

    for i, r in enumerate(results, 1):
        score_pct = min(int(r["score"] * 100), 100)
        c0, c1, c2 = st.columns([1, 8, 2])
        with c0:
            st.checkbox("", key=f"sel_search_{r['indeks']}", label_visibility="collapsed")
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
            st.progress(score_pct, text=f"score: {r['score']:.2f}")
        st.divider()

    sel_results = [r for r in results if st.session_state.get(f"sel_search_{r['indeks']}")]
    if sel_results:
        if st.button(f"💾 Zapisz zaznaczone ({len(sel_results)})", key="save_sel_search"):
            db = get_db()
            if db:
                for r in sel_results:
                    db.collection("search_selections").add({
                        "query": query,
                        "source": "text",
                        "qdrant_id": r.get("qdrant_id"),        # ← dodaj
                        "indeks": r["indeks"],
                        "nazwa": r["nazwa"],
                        "jdmr_nazwa": r.get("jdmr_nazwa", ""),
                        "score": float(r["score"]),
                        "saved_at": datetime.utcnow().isoformat(),
                    })
                st.success(f"Zapisano {len(sel_results)} indeks(ów) do Firestore (kolekcja: search_selections).")
                try:
                    _update_pomocniczy_vector(query, sel_results)
                except Exception as e:
                    st.warning(f"Zapis do Firestore OK, ale aktualizacja wektora pomocniczego nie powiodła się: {e}")
            else:
                st.warning("Brak połączenia z Firestore.")

    st.markdown("---")
    if st.button("❌ Żadna odpowiedź nie jest prawidłowa — zaproponuj nowy indeks", key="suggest_btn"):
        st.session_state["url_suggest_mode"] = True
        st.session_state["url_suggest_query"] = query
        st.session_state["url_suggest_results"] = results

    if (
        st.session_state.get("url_suggest_mode")
        and st.session_state.get("url_suggest_query") == query
    ):
        _suggest_new_index(query, st.session_state.get("url_suggest_results", []))


# ──────────────────────────────────────────────
# Wyszukiwanie po URL sklepu
# ──────────────────────────────────────────────

_USER_AGENTS = [
    # "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    # "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    # "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    # "(KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36",
]


async def _async_scrape_url(url: str) -> dict:
    from playwright.async_api import async_playwright, TimeoutError as PWTimeout  # noqa: PLC0415
    from app.core.extractors import extract  # noqa: PLC0415

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        ctx = await browser.new_context(viewport=ViewportSize({"width": 1400, "height": 900}), locale="pl-PL")
        page = await ctx.new_page()

        await page.set_extra_http_headers({
            "User-Agent": random.choice(_USER_AGENTS),
            "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8",
        })

        try:
            hide_browser_window()
            await page.goto(url, timeout=20_000, wait_until="load")

            if any(securedPage in url for securedPage in BotSecuredPages):
                await human_delay()
                await human_scroll(page)

            # await page.wait_for_timeout(2000)
            extracted = await extract(page, url)
            if not extracted.get("title") and not extracted.get("description"):
                body = await page.evaluate("() => document.body?.innerText || ''")
                extracted["description"] = body[:3000].strip()
                extracted["title"] = (await page.title()) or ""
        finally:
            await browser.close()
    return extracted

def hide_browser_window():
    system = platform.system()

    try:
        if system == "Linux":
            # wymaga: sudo apt install xdotool
            result = subprocess.check_output(
                ["xdotool", "search", "--onlyvisible", "--class", "Chromium"]
            )
            window_ids = result.decode().split()

            for wid in window_ids:
                subprocess.call(["xdotool", "windowminimize", wid])
                # lub:
                # subprocess.call(["xdotool", "windowmove", wid, "-2000", "-2000"])

        elif system == "Windows":
            import win32gui
            import win32con

            def callback(hwnd, _):
                title = win32gui.GetWindowText(hwnd)
                if "Chrome" in title or "Chromium" in title:
                    win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)

            win32gui.EnumWindows(callback, None)

        elif system == "Darwin":  # macOS
            # AppleScript – minimalizuje wszystkie okna Chrome
            script = """
            tell application "Google Chrome"
                repeat with w in windows
                    set miniaturized of w to true
                end repeat
            end tell
            """
            subprocess.call(["osascript", "-e", script])

    except Exception as e:
        print(f"[WARN] Nie udało się ukryć okna: {e}")


def _scrape_url(url: str) -> dict:
    """Wrapper that runs async scraping in isolated subprocess to avoid asyncio issues on Windows."""
    code = f"""
import asyncio
from app.core.extractors import extract
from playwright.async_api import async_playwright
import random

async def scrape():
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    ]
    
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={{"width": 1280, "height": 800}}, locale="pl-PL")
        page = await ctx.new_page()
        await page.set_extra_http_headers({{
            "User-Agent": random.choice(user_agents),
            "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8",
        }})
        extracted = {{"title": "", "description": "", "specifications": {{}}, "price": ""}}
        try:
            await page.goto("{url}", wait_until="networkidle", timeout=30000)
            extracted = await extract(page, "{url}")
        except Exception as e:
            extracted["error"] = str(e)
        finally:
            await browser.close()
        return extracted

result = asyncio.run(scrape())
import json
print(json.dumps(result))
"""
    
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.returncode == 0:
            return json.loads(proc.stdout.strip())
        else:
            return {"error": f"Subprocess error: {proc.stderr}"}
    except subprocess.TimeoutExpired:
        return {"error": "Scraping timeout"}
    except Exception as e:
        return {"error": str(e)}


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


def _upsert_proposed_to_qdrant(doc_id: str, proposal: dict) -> None:
    """Wektoryzuje zatwierdzony indeks i upsertuje do Qdrant."""
    import hashlib
    from qdrant_client import models as qmodels
    from app.pipeline.vectorize import lexical_to_sparse

    model = get_search_model()
    qdrant = _get_qdrant()
    if qdrant is None:
        raise RuntimeError("Brak połączenia z Qdrant.")

    seg1 = proposal.get("seg1", "")
    seg2 = proposal.get("seg2", "")
    seg3 = proposal.get("seg3", "")
    seg4 = proposal.get("seg4", "0")
    seg5 = proposal.get("seg5", "0")
    seg6 = proposal.get("seg6", "0")
    nazwa = proposal.get("nazwa", "")

    text = " ".join(filter(None, [seg1, seg2, seg3, nazwa]))
    output = model.encode(
        [text],
        return_dense=True,
        return_sparse=True,
        return_colbert_vecs=False,
    )
    dense = output["dense_vecs"][0].tolist()
    sparse = lexical_to_sparse(output["lexical_weights"][0])

    # ID: deterministyczny hash doc_id → unikalne int64 poza zakresem sekwencyjnych (offset 10M)
    point_id = int(hashlib.md5(doc_id.encode()).hexdigest()[:8], 16) + 10_000_000

    qdrant.upsert(
        collection_name="indeksy",
        points=[
            qmodels.PointStruct(
                id=point_id,
                vector={"dense": dense, "sparse": sparse, "pomocniczy": [0.0] * 1024},
                payload={
                    "indeks": f"PROP-{doc_id[:8].upper()}",
                    "nazwa": nazwa,
                    "komb_id": "",
                    "jdmr_nazwa": "",
                    "link": "",
                    "seg1": seg1, "seg2": seg2, "seg3": seg3,
                    "seg4": seg4, "seg5": seg5, "seg6": seg6,
                    "status": "proposed",
                },
            )
        ],
    )


def view_proposed_indexes():
    st.markdown("## 📝 Propozycje nowych indeksów")

    db = get_db()
    if db is None:
        st.error("Brak połączenia z Firestore.")
        return

    qdrant = _get_qdrant()

    docs = list(db.collection("proposed_indexes").order_by(
        "proposed_at", direction="DESCENDING"
    ).stream())

    if not docs:
        st.info("Brak propozycji. Użyj wyszukiwania i kliknij '❌ Żadna odpowiedź nie jest prawidłowa'.")
        return

    # Filtry
    col_f1, col_f2 = st.columns([2, 1])
    with col_f1:
        filter_status = st.selectbox(
            "Status", ["wszystkie", "proposed", "approved", "rejected"], index=0
        )

    total = len(docs)
    if filter_status != "wszystkie":
        docs = [d for d in docs if d.to_dict().get("status") == filter_status]

    st.markdown(f"**{len(docs)}** / {total} propozycji")
    st.markdown("---")

    for doc in docs:
        data = doc.to_dict()
        status = data.get("status", "proposed")
        query = data.get("query", "")
        nazwa = data.get("nazwa", "")
        seg_str = " / ".join(filter(
            lambda s: s and s != "0",
            [data.get(f"seg{i}", "") for i in range(1, 7)]
        ))

        status_color = {"proposed": "#f0a500", "approved": "#2ea44f", "rejected": "#cf222e"}.get(status, "#888")
        status_label = {"proposed": "oczekuje", "approved": "zatwierdzone", "rejected": "odrzucone"}.get(status, status)

        c_main, c_btn = st.columns([8, 2])
        with c_main:
            st.markdown(
                f'<span style="background:{status_color};color:#fff;padding:2px 8px;'
                f'border-radius:4px;font-size:.75rem">{status_label}</span> '
                f'<span style="font-weight:600;margin-left:8px">{html_module.escape(nazwa)}</span>'
                f'<div style="color:#8b949e;font-size:.8rem;margin-top:4px">'
                f'Segmenty: <code>{html_module.escape(seg_str)}</code></div>'
                f'<div style="color:#6e7681;font-size:.75rem">Zapytanie: <em>{html_module.escape(query)}</em>'
                f' · {data.get("proposed_at", "")[:10]}</div>',
                unsafe_allow_html=True,
            )

        with c_btn:
            if status == "proposed":
                if qdrant and st.button("✅ Zatwierdź", key=f"app_{doc.id}", type="primary"):
                    try:
                        _upsert_proposed_to_qdrant(doc.id, data)
                        db.collection("proposed_indexes").document(doc.id).update({"status": "approved"})
                        st.success(f"Dodano do Qdrant jako `PROP-{doc.id[:8].upper()}`.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Błąd: {e}")
                if st.button("❌ Odrzuć", key=f"rej_{doc.id}"):
                    db.collection("proposed_indexes").document(doc.id).update({"status": "rejected"})
                    st.rerun()
            elif status == "approved":
                st.caption(f"`PROP-{doc.id[:8].upper()}`")

        st.divider()


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
        use_reranker = st.checkbox("Cross-encoder reranking", value=True, key="url_reranker")

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
    _cache_key = f"_search_results_{query}_{top_k}_{use_reranker}"
    if _cache_key not in st.session_state:
        with st.spinner(spinner_msg):
            try:
                st.session_state[_cache_key] = _qdrant_search(query, top_k=top_k, rerank=use_reranker)
            except Exception as e:
                st.error(f"Błąd wyszukiwania: {e}")
                return
    results = st.session_state[_cache_key]

    if not results:
        st.warning("Brak wyników.")
        return

    st.markdown(f"**{len(results)} pasujących indeksów**")
    st.markdown("---")

    for i, r in enumerate(results, 1):
        score_pct = min(int(r["score"] * 100), 100)
        c0, c1, c2 = st.columns([1, 8, 2])
        with c0:
            st.checkbox("", key=f"sel_url_{r['indeks']}", label_visibility="collapsed")
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
            st.progress(score_pct, text=f"score: {r['score']:.2f}")
        st.divider()

    sel_results = [r for r in results if st.session_state.get(f"sel_url_{r['indeks']}")]
    if sel_results:
        if st.button(f"💾 Zapisz zaznaczone ({len(sel_results)})", key="save_sel_url"):
            db = get_db()
            if db:
                for r in sel_results:
                    db.collection("search_selections").add({
                        "query": query,
                        "source": "url",
                        "source_url": url,
                        "qdrant_id": r.get("qdrant_id"),   # ← dodaj tę linię
                        "indeks": r["indeks"],
                        "nazwa": r["nazwa"],
                        "jdmr_nazwa": r.get("jdmr_nazwa", ""),
                        "score": float(r["score"]),
                        "saved_at": datetime.utcnow().isoformat(),
                    })
                st.success(f"Zapisano {len(sel_results)} indeks(ów) do Firestore (kolekcja: search_selections).")
                try:
                    _update_pomocniczy_vector(query, sel_results)
                except Exception as e:
                    st.warning(f"Zapis do Firestore OK, ale aktualizacja wektora pomocniczego nie powiodła się: {e}")
            else:
                st.warning("Brak połączenia z Firestore.")

    st.markdown("---")
    if st.button("❌ Żadna odpowiedź nie jest prawidłowa — zaproponuj nowy indeks", key="suggest_btn"):
        st.session_state["url_suggest_mode"] = True
        st.session_state["url_suggest_query"] = query
        st.session_state["url_suggest_results"] = results

    if (
        st.session_state.get("url_suggest_mode")
        and st.session_state.get("url_suggest_query") == query
    ):
        _suggest_new_index(query, st.session_state.get("url_suggest_results", []))


# ──────────────────────────────────────────────
# Główna aplikacja
# ──────────────────────────────────────────────

def main():
    # Nawigacja
    st.sidebar.title("IndeksyGSR")
    view = st.sidebar.radio(
        "Widok",
        ["📧 Maile", "📦 Produkty (scraping)", "🔍 Wyszukiwanie", "🌐 Po URL sklepu", "📝 Propozycje indeksów"],
        label_visibility="collapsed",
    )

    st.sidebar.markdown("---")
    if st.sidebar.button("🔄 Odśwież dane"):
        st.cache_data.clear()
        for key in list(st.session_state.keys()):
            if key.startswith("_search_results_"):
                del st.session_state[key]
        st.rerun()

    if view == "📧 Maile":
        view_emails()
    elif view == "📦 Produkty (scraping)":
        view_products()
    elif view == "🔍 Wyszukiwanie":
        view_search()
    elif view == "🌐 Po URL sklepu":
        view_search_by_url()
    else:
        view_proposed_indexes()


if __name__ == "__main__":
    main()
