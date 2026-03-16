# Plan: Proponowanie nowych indeksów materiałowych

## Kontekst

Użytkownik szuka indeksu materiałowego przez interfejs Streamlit (`dashboard.py → view_search()`).
Gdy żaden wynik nie pasuje, system powinien zaproponować **nowy indeks** zbudowany z istniejących segmentów, zachowując ich hierarchiczne zależności.

### Struktura indeksu — wszystkie 6 segmentów

| Pozycja | Nazwa | Wartość z CSV | Zależność |
|---------|-------|---------------|-----------|
| 1 | Typ indeksu | `OPIS_WARTOSC` | niezależna |
| 2 | Grupa asortymentowa | `OPIS_WARTOSC` | zależy od poz. 1 (`ZALEZNY_OD_SLIT_ID`) |
| 3 | Podgrupa | `OPIS_WARTOSC` | zależy od poz. 2 (`ZALEZNY_OD_SLIT_ID`) |
| 4 | Cecha główna | `KOD_WARTOSC` (np. M20, DN65) | **niezależna** — płaska lista |
| 5 | Materiał | `KOD_WARTOSC` (np. CYNK, S235) | **niezależna** — płaska lista |
| 6 | Odbiór | `KOD_WARTOSC` (np. OGNIOWO, 6) | **niezależna** — płaska lista |

Hierarchia przez `ZALEZNY_OD_SLIT_ID` dotyczy **wyłącznie pozycji 1-3**.
Pozycje 4-6 to niezależne płaskie listy dostępnych wartości `KOD_WARTOSC`.

Każda propozycja nowego indeksu musi zawierać pełny komplet 6 segmentów (lub `0` gdy dana pozycja nie dotyczy).

---

## Wybrane rozwiązanie: Opcja D — Hybrid (BGE-M3 + kaskadowe dropdowny)

### Kluczowa zmiana architektoniczna: segmenty w payloadzie Qdrant

Zamiast dekodować `KOMB_ID → segmenty` w runtime dashboardu, segmenty 1-6 są **zapisane bezpośrednio w payloadzie** każdego punktu Qdrant podczas wektoryzacji.

**Obecny payload:**
```json
{"indeks": "...", "nazwa": "...", "komb_id": "...", "jdmr_nazwa": "..."}
```

**Nowy payload:**
```json
{
  "indeks": "...", "nazwa": "...", "komb_id": "...", "jdmr_nazwa": "...",
  "seg1": "ZŁĄCZKI",
  "seg2": "ŚRUBY I NAKRĘTKI",
  "seg3": "ŚRUBY",
  "seg4": "M20",
  "seg5": "CYNK",
  "seg6": "OGNIOWO"
}
```

Wartości poz. 4-6 wypełniane jako `"0"` gdy pozycja nie dotyczy danego indeksu.

---

### Schemat działania

```
Użytkownik wpisuje zapytanie
         ↓
   Wyniki wyszukiwania — każdy wynik ma w payloadzie seg1..seg6
         ↓
   [❌ Żadna odpowiedź nie jest prawidłowa]
         ↓
   Auto-sugestia (BGE-M3) dla pozycji 1-3 (opisy semantyczne):
     1. Embedduj opisy poz.1 → top-3 zbliżone do zapytania
     2. Embedduj dzieci poz.2 dla wybranych → top-2
     3. Embedduj dzieci poz.3 dla wybranych → top-2
         ↓
   Dla pozycji 4-6: defaulty z results[0].payload["seg4/5/6"]
   (najlepszy wynik jest bliski — jego poz.4-6 to dobry punkt startowy)
         ↓
   UI z kaskadowymi dropdownami (6 poziomów):
     [Poz.1] → [Poz.2] → [Poz.3]  ← auto-sugestia BGE-M3
     [Poz.4] [Poz.5] [Poz.6]       ← default z results[0], user może zmienić
     NAZWA [pole tekstowe z auto-sugestią]
         ↓
   [💾 Zapisz propozycję] → Firestore: kolekcja `proposed_indexes`
```

---

## Architektura implementacji

### 1. Zmiany w `backend/app/pipeline/vectorize.py`

#### Rozszerzyć `build_segment_map()` (linia 88) o poz. 4-6

```python
def build_segment_map(slownik_df: pd.DataFrame) -> dict[int, dict[int, str]]:
    """komb_id → {pozycja: wartosc} — pozycje 1-3: OPIS_WARTOSC, 4-6: KOD_WARTOSC."""
    result: dict[int, dict[int, str]] = {}
    for _, row in slownik_df.iterrows():
        pos = int(row["POZYCJA"])
        komb_id = int(row["KOMB_ID"])
        if komb_id not in result:
            result[komb_id] = {}
        # Poz. 1-3: OPIS_WARTOSC (opisy semantyczne)
        if pos <= 3 and pd.notna(row.get("OPIS_WARTOSC")):
            result[komb_id][pos] = str(row["OPIS_WARTOSC"]).strip()
        # Poz. 4-6: KOD_WARTOSC (kody techniczne)
        elif pos > 3 and pd.notna(row.get("KOD_WARTOSC")):
            result[komb_id][pos] = str(row["KOD_WARTOSC"]).strip()
    return result
```

#### Rozszerzyć `upload_batch()` (linia 193) — dodać seg1-6 do payloadu

```python
def upload_batch(
    client: QdrantClient,
    id_offset: int,
    rows_batch: list[pd.Series],
    dense_vecs: list,
    lexical_weights: list,
    segment_map: dict[int, dict[int, str]],   # ← nowy parametr
) -> None:
    points = []
    for i, (row, dense, lex) in enumerate(zip(rows_batch, dense_vecs, lexical_weights)):
        indeks = str(row.get("INDEKS", "")).strip()
        komb_id_raw = row.get("KOMB_ID")
        seg = segment_map.get(int(komb_id_raw), {}) if pd.notna(komb_id_raw) else {}
        points.append(
            models.PointStruct(
                id=id_offset + i,
                vector={
                    "dense": dense.tolist(),
                    "sparse": lexical_to_sparse(lex),
                },
                payload={
                    "indeks": indeks,
                    "nazwa": str(row.get("NAZWA", "")).strip(),
                    "komb_id": str(row.get("KOMB_ID", "")),
                    "jdmr_nazwa": str(row.get("JDMR_NAZWA", "")),
                    "link": "",
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
```

Przekazać `segment_map` z `run()` do `upload_batch()`.

**Wymagane po zmianach:** re-wektoryzacja: `vectorize --recreate`

---

### 2. Nowy plik: `backend/app/core/suggest.py`

```python
@dataclass
class SegmentTree:
    """Drzewo hierarchii segmentów 1-3 do filtrowania dropdownów."""
    pos1: dict[int, str]                              # slit_id → opis_wartosc
    pos2_by_parent: dict[int, list[tuple[int, str]]]  # parent_slit_id → [(slit_id, opis)]
    pos3_by_parent: dict[int, list[tuple[int, str]]]

    # Płaskie listy poz. 4-6 (do dropdownów — pełna lista dostępnych wartości)
    pos4_values: list[str]
    pos5_values: list[str]
    pos6_values: list[str]


@dataclass
class SegmentProposal:
    seg1_slit_id: int;  seg1_text: str   # auto-sugestia BGE-M3
    seg2_slit_id: int;  seg2_text: str
    seg3_slit_id: int;  seg3_text: str
    score: float


def build_segment_tree(slownik_df: pd.DataFrame) -> SegmentTree:
    """
    Buduje hierarchię poz. 1-3 + płaskie listy poz. 4-6.
    """
    ...


def suggest_segments(
    query: str,
    tree: SegmentTree,
    model,           # FlagModel (BGE-M3) — singleton z dashboardu
    top_n: int = 3,
) -> list[SegmentProposal]:
    """
    Auto-sugestia seg1-3 przez BGE-M3 cosine similarity.
    Embeddingi opisów poz.1-3 są cache'owane (dane statyczne).
    """
    ...
```

**Algorytm `suggest_segments` (poz. 1-3):**
1. Embedduj query: `query_vec = model.encode(query)["dense_vecs"]`
2. Embedduj wszystkie opisy POZYCJA=1 → cosine sim → top-3 slit_ids (cache embeddingi)
3. Dla każdego seg1 → embedduj dzieci POZYCJA=2 → top-2
4. Dla każdego seg2 → embedduj dzieci POZYCJA=3 → top-2
5. Zwróć `SegmentProposal` z wypełnionymi seg1-3

---

### 3. Zmiany w `backend/app/dashboard.py`

#### Nowe funkcje pomocnicze

```python
@st.cache_data
def _load_segment_tree() -> SegmentTree:
    from app.pipeline.vectorize import load_slownik
    from app.core.suggest import build_segment_tree
    return build_segment_tree(load_slownik())
```

#### Modyfikacja `view_search()` — po linii ~561

```python
st.markdown("---")
if st.button("❌ Żadna odpowiedź nie jest prawidłowa — zaproponuj nowy indeks"):
    st.session_state["suggest_mode"] = True
    st.session_state["suggest_query"] = query
    st.session_state["suggest_results"] = results   # wyniki wyszukiwania z payloadami seg1-6

if st.session_state.get("suggest_mode") and st.session_state.get("suggest_query") == query:
    _suggest_new_index(query, st.session_state.get("suggest_results", []))
```

#### Implementacja `_suggest_new_index()`

```python
def _suggest_new_index(query: str, results: list[dict]) -> None:
    st.markdown("### Propozycja nowego indeksu")

    tree = _load_segment_tree()
    model = get_search_model()

    # Auto-sugestia poz. 1-3
    with st.spinner("Szukam pasujących segmentów..."):
        proposals = suggest_segments(query, tree, model, top_n=1)
    best = proposals[0] if proposals else None

    # Defaulty poz. 4-6 z najlepszego wyniku wyszukiwania
    top_result = results[0] if results else {}
    default_seg4 = top_result.get("seg4", "0")
    default_seg5 = top_result.get("seg5", "0")
    default_seg6 = top_result.get("seg6", "0")

    # ── Pozycje 1-3: semantyczne (auto-sugestia) ──────────────────────
    col1, col2, col3 = st.columns(3)

    with col1:
        seg1_opts = list(tree.pos1.values())
        sel1 = st.selectbox("Typ indeksu (poz. 1)", seg1_opts,
                            index=seg1_opts.index(best.seg1_text) if best else 0)

    seg1_slit_id = next(k for k, v in tree.pos1.items() if v == sel1)
    seg2_opts = [t for _, t in tree.pos2_by_parent.get(seg1_slit_id, [])]

    with col2:
        def_idx2 = seg2_opts.index(best.seg2_text) if best and best.seg2_text in seg2_opts else 0
        sel2 = st.selectbox("Grupa (poz. 2)", seg2_opts or ["—"], index=def_idx2)

    seg2_slit_id = next((k for k, v in tree.pos2_by_parent.get(seg1_slit_id, []) if v == sel2), None)
    seg3_opts = [t for _, t in tree.pos3_by_parent.get(seg2_slit_id, [])] if seg2_slit_id else []

    with col3:
        def_idx3 = seg3_opts.index(best.seg3_text) if best and best.seg3_text in seg3_opts else 0
        sel3 = st.selectbox("Podgrupa (poz. 3)", seg3_opts or ["—"], index=def_idx3)

    # ── Pozycje 4-6: techniczne (default z top wyniku, lista ze słownika) ──
    col4, col5, col6 = st.columns(3)

    pos4_opts = ["0"] + tree.pos4_values
    pos5_opts = ["0"] + tree.pos5_values
    pos6_opts = ["0"] + tree.pos6_values

    with col4:
        def_idx4 = pos4_opts.index(default_seg4) if default_seg4 in pos4_opts else 0
        sel4 = st.selectbox("Cecha główna (poz. 4)", pos4_opts, index=def_idx4)
    with col5:
        def_idx5 = pos5_opts.index(default_seg5) if default_seg5 in pos5_opts else 0
        sel5 = st.selectbox("Materiał (poz. 5)", pos5_opts, index=def_idx5)
    with col6:
        def_idx6 = pos6_opts.index(default_seg6) if default_seg6 in pos6_opts else 0
        sel6 = st.selectbox("Odbiór (poz. 6)", pos6_opts, index=def_idx6)

    # ── Nazwa i zapis ────────────────────────────────────────────────
    auto_name = " ".join(filter(lambda x: x != "0", [sel1, sel2, sel3, sel4, sel5, sel6]))
    nazwa = st.text_input("Nazwa nowego indeksu (NAZWA)", value=auto_name.upper())

    st.info(f"Segmenty: `{sel1}` / `{sel2}` / `{sel3}` / `{sel4}` / `{sel5}` / `{sel6}`")

    if st.button("💾 Zapisz propozycję"):
        db = _get_firestore()
        if db:
            db.collection("proposed_indexes").add({
                "query": query,
                "seg1": sel1, "seg2": sel2, "seg3": sel3,
                "seg4": sel4, "seg5": sel5, "seg6": sel6,
                "nazwa": nazwa,
                "proposed_at": datetime.utcnow().isoformat(),
                "status": "proposed",
            })
            st.success("Propozycja zapisana do Firestore.")
        else:
            st.warning("Brak połączenia z Firestore.")
```

---

## Pliki do modyfikacji

| Plik | Zmiana |
|------|--------|
| `backend/app/pipeline/vectorize.py` | Rozszerzyć `build_segment_map()` (poz.4-6) i `upload_batch()` (seg1-6 w payload) |
| `backend/app/core/suggest.py` | NOWY — drzewo hierarchii + auto-sugestia BGE-M3 |
| `backend/app/dashboard.py` | Przycisk + panel 6 dropdownów w `view_search()` |

## Funkcje do reuse (bez zmian)

| Funkcja | Lokalizacja |
|---------|-------------|
| `build_segment_map()` | `backend/app/pipeline/vectorize.py:88` (rozszerzona) |
| `load_slownik()` | `backend/app/pipeline/vectorize.py:77` |
| `get_search_model()` | `backend/app/dashboard.py:480` |
| `_get_firestore()` | `backend/app/dashboard.py` |

---

## Kluczowe uwagi implementacyjne

1. **Poz. 1-3** — auto-sugestia przez BGE-M3 cosine similarity (opisy semantyczne); embeddingi cache'owane przez `@st.cache_data`
2. **Poz. 4-6** — defaulty z `results[0].payload["seg4/5/6"]` (payload Qdrant); pełna lista wartości z `SegmentTree.pos4/5/6_values` (ze slownik_segmentow)
3. **Re-wektoryzacja wymagana** po zmianie `build_segment_map` + `upload_batch` → `vectorize --recreate`
4. **Wartość "0"** — "nie dotyczy"; zawsze pierwsza opcja w dropdownach poz. 4-6
5. **Zależności kaskadowe tylko poz. 1-3** — zmiana poz.1 filtruje poz.2 i poz.3 (Streamlit reruns)

---

## Weryfikacja end-to-end

1. Uruchom `vectorize --recreate` → sprawdź czy nowe punkty mają `seg1`..`seg6` w payload
2. `dashboard` → 🔍 Wyszukiwanie → wpisz zapytanie
3. Kliknij **"❌ Żadna odpowiedź nie jest prawidłowa"**
4. Sprawdź czy dropdowny 1-3 mają auto-sugestię z BGE-M3
5. Sprawdź czy dropdowny 4-6 mają wartości z `results[0]` jako default
6. Zmień poz.1 → sprawdź czy poz.2 i poz.3 filtrują się poprawnie
7. Kliknij **"💾 Zapisz"** → sprawdź Firestore `proposed_indexes`
