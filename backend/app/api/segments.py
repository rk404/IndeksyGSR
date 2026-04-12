"""Segments, suggestions, and proposals API endpoints."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from functools import lru_cache

from fastapi import APIRouter, Query, HTTPException

from app.api.models import (
    SegmentTreeResponse,
    SuggestRequest,
    SegmentProposalResponse,
    ProposeRequest,
    ProposeResponse,
    ProposalItem,
)

router = APIRouter(tags=["segments"])


@lru_cache(maxsize=1)
def _load_tree():
    from app.pipeline.vectorize import load_slownik
    from app.core.suggest import build_segment_tree
    return build_segment_tree(load_slownik())


def _tree_to_response(tree) -> SegmentTreeResponse:
    """Convert SegmentTree dataclass to JSON-serializable response."""
    return SegmentTreeResponse(
        pos1={str(k): v for k, v in tree.pos1.items()},
        pos1_kod={str(k): v for k, v in tree.pos1_kod.items()},
        pos2_by_parent={
            str(k): [[sid, text] for sid, text in children]
            for k, children in tree.pos2_by_parent.items()
        },
        pos3_by_parent={
            str(k): [[sid, text] for sid, text in children]
            for k, children in tree.pos3_by_parent.items()
        },
        pos2_kod={str(k): v for k, v in tree.pos2_kod.items()},
        pos3_kod={str(k): v for k, v in tree.pos3_kod.items()},
        pos4_values=tree.pos4_values,
        pos5_values=tree.pos5_values,
        pos6_values=tree.pos6_values,
    )


@router.get("/segments", response_model=SegmentTreeResponse)
def api_segments():
    tree = _load_tree()
    return _tree_to_response(tree)


@router.post("/suggest", response_model=list[SegmentProposalResponse])
def api_suggest(req: SuggestRequest):
    from app.core.suggest import suggest_segments
    from app.core.search import get_model

    tree = _load_tree()
    model = get_model()
    proposals = suggest_segments(req.query, tree, model, top_n=req.top_n)
    return [
        SegmentProposalResponse(
            seg1_slit_id=p.seg1_slit_id,
            seg1_text=p.seg1_text,
            seg2_slit_id=p.seg2_slit_id,
            seg2_text=p.seg2_text,
            seg3_slit_id=p.seg3_slit_id,
            seg3_text=p.seg3_text,
            score=round(p.score, 4),
        )
        for p in proposals
    ]


@router.post("/propose", response_model=ProposeResponse)
def api_propose(req: ProposeRequest):
    from app.services.firestore import get_client as get_db

    db = get_db()
    indeks = req.indeks or f"{req.kod1}-{req.kod2}-{req.kod3}-{req.seg4}-{req.seg5}-{req.seg6}-"
    _, doc_ref = db.collection("proposed_indexes").add({
        "query": req.query,
        "indeks": indeks,
        "seg1": req.seg1,
        "seg2": req.seg2,
        "seg3": req.seg3,
        "seg4": req.seg4,
        "seg5": req.seg5,
        "seg6": req.seg6,
        "kod1": req.kod1,
        "kod2": req.kod2,
        "kod3": req.kod3,
        "nazwa": req.nazwa,
        "proposed_at": datetime.now(timezone.utc).isoformat(),
        "status": "proposed",
    })
    return ProposeResponse(id=doc_ref.id)


@router.get("/proposals", response_model=list[ProposalItem])
def api_proposals(status: str | None = Query(None)):
    from app.services.firestore import get_client as get_db

    db = get_db()
    query = db.collection("proposed_indexes").order_by(
        "proposed_at", direction="DESCENDING"
    )
    docs = list(query.stream())

    items = []
    for doc in docs:
        data = doc.to_dict()
        doc_status = data.get("status", "proposed")
        if status and doc_status != status:
            continue
        items.append(ProposalItem(
            id=doc.id,
            query=data.get("query", ""),
            indeks=data.get("indeks", ""),
            nazwa=data.get("nazwa", ""),
            seg1=data.get("seg1", ""),
            seg2=data.get("seg2", ""),
            seg3=data.get("seg3", ""),
            seg4=data.get("seg4", ""),
            seg5=data.get("seg5", ""),
            seg6=data.get("seg6", ""),
            status=doc_status,
            proposed_at=str(data.get("proposed_at", "")),
        ))
    return items


@router.post("/proposals/{doc_id}/approve")
def api_approve_proposal(doc_id: str):
    from app.services.firestore import get_client as get_db
    from app.services.qdrant import get_client as get_qdrant
    from app.core.search import get_model
    from app.pipeline.vectorize import lexical_to_sparse
    from qdrant_client import models as qmodels

    db = get_db()
    doc_ref = db.collection("proposed_indexes").document(doc_id)
    doc = doc_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Proposal not found")

    data = doc.to_dict()
    if data.get("status") != "proposed":
        raise HTTPException(status_code=400, detail=f"Cannot approve proposal with status '{data.get('status')}'")

    model = get_model()
    qdrant = get_qdrant()

    text = " ".join(filter(None, [data.get("seg1", ""), data.get("seg2", ""), data.get("seg3", ""), data.get("nazwa", "")]))
    output = model.encode([text], return_dense=True, return_sparse=True, return_colbert_vecs=False)
    dense = output["dense_vecs"][0].tolist()
    sparse = lexical_to_sparse(output["lexical_weights"][0])

    point_id = int(hashlib.md5(doc_id.encode()).hexdigest()[:8], 16) + 10_000_000

    qdrant.upsert(
        collection_name="indeksy",
        points=[
            qmodels.PointStruct(
                id=point_id,
                vector={"dense": dense, "sparse": sparse, "pomocniczy": [0.0] * 1024},
                payload={
                    "indeks": f"PROP-{doc_id[:8].upper()}",
                    "nazwa": data.get("nazwa", ""),
                    "komb_id": "",
                    "jdmr_nazwa": "",
                    "link": "",
                    "seg1": data.get("seg1", ""),
                    "seg2": data.get("seg2", ""),
                    "seg3": data.get("seg3", ""),
                    "seg4": data.get("seg4", "0"),
                    "seg5": data.get("seg5", "0"),
                    "seg6": data.get("seg6", "0"),
                    "status": "proposed",
                },
            )
        ],
    )

    doc_ref.update({"status": "approved"})
    return {"status": "approved", "qdrant_id": f"PROP-{doc_id[:8].upper()}"}


@router.post("/proposals/{doc_id}/reject")
def api_reject_proposal(doc_id: str):
    from app.services.firestore import get_client as get_db

    db = get_db()
    doc_ref = db.collection("proposed_indexes").document(doc_id)
    doc = doc_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Proposal not found")

    doc_ref.update({"status": "rejected"})
    return {"status": "rejected"}
