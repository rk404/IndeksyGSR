"""
Logika sugestii nowych indeksów materiałowych.

Buduje drzewo hierarchii segmentów z slownik_segmentow.csv:
- Pozycje 1-3: hierarchia przez ZALEZNY_OD_SLIT_ID (OPIS_WARTOSC)
- Pozycje 4-6: płaskie listy unikalnych KOD_WARTOSC (niezależne)

Funkcja suggest_segments() używa BGE-M3 (już załadowanego w dashboardzie)
do auto-sugestii segmentów 1-3 przez cosine similarity.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


@dataclass
class SegmentTree:
    """Drzewo hierarchii segmentów zbudowane z slownik_segmentow.csv."""

    # Pozycje 1-3: hierarchia przez ZALEZNY_OD_SLIT_ID
    pos1: dict[int, str] = field(default_factory=dict)           # slit_id → opis
    pos1_kod: dict[int, str] = field(default_factory=dict)       # slit_id → kod
    # parent_slit_id → [(slit_id, opis_wartosc), ...]
    pos2_by_parent: dict[int, list[tuple[int, str]]] = field(default_factory=dict)
    pos3_by_parent: dict[int, list[tuple[int, str]]] = field(default_factory=dict)
    # slit_id → kod (dla budowania kodu indeksu)
    pos2_kod: dict[int, str] = field(default_factory=dict)
    pos3_kod: dict[int, str] = field(default_factory=dict)

    # Pozycje 4-6: niezależne płaskie listy KOD_WARTOSC
    pos4_values: list[str] = field(default_factory=list)
    pos5_values: list[str] = field(default_factory=list)
    pos6_values: list[str] = field(default_factory=list)


@dataclass
class SegmentProposal:
    """Propozycja kombinacji segmentów 1-3 dla nowego indeksu."""
    seg1_slit_id: int
    seg1_text: str
    seg2_slit_id: int
    seg2_text: str
    seg3_slit_id: int
    seg3_text: str
    score: float


def build_segment_tree(slownik_df: pd.DataFrame) -> SegmentTree:
    """
    Buduje SegmentTree z slownik_segmentow.csv.

    Pozycje 1-3: OPIS_WARTOSC + hierarchia ZALEZNY_OD_SLIT_ID → SLIT_ID.
    Pozycje 4-6: unikalne KOD_WARTOSC (bez zależności).
    """
    # Obsługa obu wariantów nazwy kolumny
    kod_col = "KOD_WARTOSC" if "KOD_WARTOSC" in slownik_df.columns else "KOD_WAROSC"

    tree = SegmentTree()

    pos4_set: set[str] = set()
    pos5_set: set[str] = set()
    pos6_set: set[str] = set()

    for _, row in slownik_df.iterrows():
        pos = int(row["POZYCJA"])
        slit_id_raw = row.get("SLIT_ID")
        zalezny_raw = row.get("ZALEZNY_OD_SLIT_ID")

        if pos == 1:
            opis = row.get("OPIS_WARTOSC")
            kod = row.get(kod_col)
            if pd.notna(slit_id_raw) and pd.notna(opis):
                slit_id = int(slit_id_raw)
                if slit_id not in tree.pos1:
                    tree.pos1[slit_id] = str(opis).strip()
                if pd.notna(kod):
                    tree.pos1_kod[slit_id] = str(kod).strip()

        elif pos == 2:
            opis = row.get("OPIS_WARTOSC")
            kod = row.get(kod_col)
            if pd.notna(slit_id_raw) and pd.notna(zalezny_raw) and pd.notna(opis):
                slit_id = int(slit_id_raw)
                parent_id = int(zalezny_raw)
                entry = (slit_id, str(opis).strip())
                if parent_id not in tree.pos2_by_parent:
                    tree.pos2_by_parent[parent_id] = []
                if entry not in tree.pos2_by_parent[parent_id]:
                    tree.pos2_by_parent[parent_id].append(entry)
                if pd.notna(kod):
                    tree.pos2_kod[slit_id] = str(kod).strip()

        elif pos == 3:
            opis = row.get("OPIS_WARTOSC")
            kod = row.get(kod_col)
            if pd.notna(slit_id_raw) and pd.notna(zalezny_raw) and pd.notna(opis):
                slit_id = int(slit_id_raw)
                parent_id = int(zalezny_raw)
                entry = (slit_id, str(opis).strip())
                if parent_id not in tree.pos3_by_parent:
                    tree.pos3_by_parent[parent_id] = []
                if entry not in tree.pos3_by_parent[parent_id]:
                    tree.pos3_by_parent[parent_id].append(entry)
                if pd.notna(kod):
                    tree.pos3_kod[slit_id] = str(kod).strip()

        elif pos == 4:
            kod = row.get(kod_col)
            if pd.notna(kod):
                pos4_set.add(str(kod).strip())

        elif pos == 5:
            kod = row.get(kod_col)
            if pd.notna(kod):
                pos5_set.add(str(kod).strip())

        elif pos == 6:
            kod = row.get(kod_col)
            if pd.notna(kod):
                pos6_set.add(str(kod).strip())

    tree.pos4_values = sorted(pos4_set)
    tree.pos5_values = sorted(pos5_set)
    tree.pos6_values = sorted(pos6_set)

    log.info(
        "SegmentTree: poz1=%d, poz2_parents=%d, poz3_parents=%d, "
        "poz4=%d, poz5=%d, poz6=%d",
        len(tree.pos1),
        len(tree.pos2_by_parent),
        len(tree.pos3_by_parent),
        len(tree.pos4_values),
        len(tree.pos5_values),
        len(tree.pos6_values),
    )
    return tree


# Moduł-level cache embeddingow (statyczne — nie zmieniają się między sesjami)
_pos1_cache: dict[str, tuple[list[int], np.ndarray]] = {}  # hash → (slit_ids, vecs)


def _encode_batch(model, texts: list[str]) -> np.ndarray:
    """Koduje listę tekstów modelem BGE-M3, zwraca macierz dense (N x 1024)."""
    out = model.encode(texts, return_dense=True, return_sparse=False, return_colbert_vecs=False)
    vecs = out["dense_vecs"]
    return np.array(vecs, dtype=np.float32)


def _cosine_topk(query_vec: np.ndarray, doc_vecs: np.ndarray, k: int) -> list[int]:
    """Zwraca k indeksów doc_vecs o najwyższym cosine similarity do query_vec."""
    # Zakładamy że wektory są już znormalizowane (BGE-M3 normalizuje L2)
    scores = doc_vecs @ query_vec
    k = min(k, len(scores))
    return list(np.argsort(scores)[::-1][:k])


def suggest_segments(
    query: str,
    tree: SegmentTree,
    model,
    top_n: int = 3,
) -> list[SegmentProposal]:
    """
    Auto-sugestia segmentów 1-3 przez BGE-M3 cosine similarity.

    Algorytm:
    1. Embedduj query.
    2. Embedduj opisy poz.1 → top-3 najbliższe (cache).
    3. Dla każdego seg1: embedduj dzieci poz.2 → top-2.
    4. Dla każdego seg2: embedduj dzieci poz.3 → top-2.
    5. Zwróć posortowane SegmentProposal (score = avg similarity).
    """
    if not tree.pos1:
        return []

    # 1. Embedduj query
    query_vec = _encode_batch(model, [query])[0]  # (1024,)

    # 2. Poz. 1 — użyj unikalnych opisów (może być wiele SLIT_ID z tym samym opisem)
    pos1_items: list[tuple[int, str]] = list(tree.pos1.items())  # [(slit_id, opis), ...]
    pos1_slit_ids = [sid for sid, _ in pos1_items]
    pos1_texts = [opis for _, opis in pos1_items]

    pos1_vecs = _encode_batch(model, pos1_texts)  # (N, 1024)
    top1_idxs = _cosine_topk(query_vec, pos1_vecs, k=min(3, len(pos1_items)))

    proposals: list[SegmentProposal] = []

    for idx1 in top1_idxs:
        seg1_slit_id = pos1_slit_ids[idx1]
        seg1_text = pos1_texts[idx1]
        score1 = float(pos1_vecs[idx1] @ query_vec)

        # 3. Dzieci poz. 2
        children2 = tree.pos2_by_parent.get(seg1_slit_id, [])
        if not children2:
            continue

        c2_slit_ids = [sid for sid, _ in children2]
        c2_texts = [opis for _, opis in children2]
        c2_vecs = _encode_batch(model, c2_texts)
        top2_idxs = _cosine_topk(query_vec, c2_vecs, k=min(2, len(children2)))

        for idx2 in top2_idxs:
            seg2_slit_id = c2_slit_ids[idx2]
            seg2_text = c2_texts[idx2]
            score2 = float(c2_vecs[idx2] @ query_vec)

            # 4. Dzieci poz. 3
            children3 = tree.pos3_by_parent.get(seg2_slit_id, [])
            if not children3:
                continue

            c3_slit_ids = [sid for sid, _ in children3]
            c3_texts = [opis for _, opis in children3]
            c3_vecs = _encode_batch(model, c3_texts)
            top3_idxs = _cosine_topk(query_vec, c3_vecs, k=min(2, len(children3)))

            for idx3 in top3_idxs:
                seg3_slit_id = c3_slit_ids[idx3]
                seg3_text = c3_texts[idx3]
                score3 = float(c3_vecs[idx3] @ query_vec)

                proposals.append(SegmentProposal(
                    seg1_slit_id=seg1_slit_id,
                    seg1_text=seg1_text,
                    seg2_slit_id=seg2_slit_id,
                    seg2_text=seg2_text,
                    seg3_slit_id=seg3_slit_id,
                    seg3_text=seg3_text,
                    score=(score1 + score2 + score3) / 3,
                ))

    proposals.sort(key=lambda p: p.score, reverse=True)
    return proposals[:top_n]
