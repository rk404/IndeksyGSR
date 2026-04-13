"""Search API endpoints."""

from __future__ import annotations

import io
from datetime import datetime, timezone

from fastapi import APIRouter, UploadFile, File, Query, HTTPException
from fastapi.responses import StreamingResponse

from app.api.models import (
    SearchRequest,
    SearchResponse,
    SearchResult,
    SearchUrlRequest,
    SearchUrlResponse,
    ScrapedData,
    SaveSelectionRequest,
    GenerateDescriptionRequest,
    GenerateDescriptionResponse,
)

router = APIRouter(tags=["search"])


def _to_search_results(candidates: list[dict]) -> list[SearchResult]:
    return [
        SearchResult(
            qdrant_id=c.get("qdrant_id"),
            indeks=c["indeks"],
            nazwa=c["nazwa"],
            komb_id=c.get("komb_id", ""),
            jdmr_nazwa=c.get("jdmr_nazwa", ""),
            score=c["score"],
        )
        for c in candidates
    ]


@router.post("/search", response_model=SearchResponse)
def api_search(req: SearchRequest):
    from app.core.search import search

    candidates = search(req.query, top_k=req.top_k, rerank=req.rerank)
    return SearchResponse(query=req.query, results=_to_search_results(candidates))


@router.post("/search-url", response_model=SearchUrlResponse)
def api_search_url(req: SearchUrlRequest):
    from app.core.search import search
    from app.core.scraper import scrape_url, build_query_from_scraped

    scraped = scrape_url(req.url)
    query = build_query_from_scraped(scraped)
    candidates = search(query, top_k=req.top_k, rerank=req.rerank)

    return SearchUrlResponse(
        scraped=ScrapedData(**{
            k: scraped.get(k, "" if k != "specifications" else {})
            for k in ("title", "price", "specifications", "description")
        }),
        query=query,
        results=_to_search_results(candidates),
    )


@router.post("/search/save")
def api_save_selection(req: SaveSelectionRequest):
    from app.services.firestore import get_client as get_db
    from app.core.search import get_model

    db = get_db()
    for r in req.results:
        doc = {
            "query": req.query,
            "source": req.source,
            "qdrant_id": r.qdrant_id,
            "indeks": r.indeks,
            "nazwa": r.nazwa,
            "jdmr_nazwa": r.jdmr_nazwa,
            "score": float(r.score),
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        desc = req.groq_descriptions.get(r.indeks, "")
        if desc:
            doc["groq_description"] = desc
        db.collection("search_selections").add(doc)

    # Update pomocniczy vector
    try:
        from app.services.qdrant import get_client as get_qdrant
        from qdrant_client import models as qmodels

        model = get_model()
        # Use first available description, fall back to query
        text = next((d for d in req.groq_descriptions.values() if d), req.query)
        output = model.encode(
            [text], return_dense=True, return_sparse=False, return_colbert_vecs=False,
        )
        vec = output["dense_vecs"][0].tolist()

        qdrant = get_qdrant()
        points = [
            qmodels.PointVectors(id=r.qdrant_id, vector={"pomocniczy": vec})
            for r in req.results
            if r.qdrant_id is not None
        ]
        if points:
            qdrant.update_vectors(collection_name="indeksy", points=points)
    except Exception:
        pass  # non-critical

    return {"saved": len(req.results)}


@router.post("/search/bulk")
async def api_bulk_search(
    file: UploadFile = File(...),
    rerank: bool = Query(False),
):
    import pandas as pd
    from app.core.search import search

    contents = await file.read()
    try:
        df_input = pd.read_excel(io.BytesIO(contents))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Błąd odczytu pliku Excel: {e}")

    if "opis_materialu" not in df_input.columns:
        raise HTTPException(
            status_code=400,
            detail=f"Plik musi zawierać kolumnę `opis_materialu`. Znalezione: {list(df_input.columns)}",
        )

    descriptions = df_input["opis_materialu"].astype(str).tolist()
    rows = []
    for desc in descriptions:
        try:
            hits = search(desc, top_k=1, rerank=rerank)
            if hits:
                rows.append({
                    "opis_materialu": desc,
                    "indeks": hits[0]["indeks"],
                    "nazwa": hits[0]["nazwa"],
                    "score": round(float(hits[0]["score"]), 4),
                })
            else:
                rows.append({"opis_materialu": desc, "indeks": "", "nazwa": "", "score": 0.0})
        except Exception as e:
            rows.append({"opis_materialu": desc, "indeks": "BŁĄD", "nazwa": str(e), "score": 0.0})

    return {"results": rows, "total": len(rows)}


@router.post("/search/bulk/download")
async def api_bulk_download(
    file: UploadFile = File(...),
    rerank: bool = Query(False),
):
    import pandas as pd
    from app.core.search import search

    contents = await file.read()
    df_input = pd.read_excel(io.BytesIO(contents))
    if "opis_materialu" not in df_input.columns:
        raise HTTPException(status_code=400, detail="Brak kolumny `opis_materialu`.")

    descriptions = df_input["opis_materialu"].astype(str).tolist()
    rows = []
    for desc in descriptions:
        try:
            hits = search(desc, top_k=1, rerank=rerank)
            if hits:
                rows.append({"opis_materialu": desc, "indeks": hits[0]["indeks"], "nazwa": hits[0]["nazwa"], "score": round(float(hits[0]["score"]), 4)})
            else:
                rows.append({"opis_materialu": desc, "indeks": "", "nazwa": "", "score": 0.0})
        except Exception as e:
            rows.append({"opis_materialu": desc, "indeks": "BŁĄD", "nazwa": str(e), "score": 0.0})

    df_result = pd.DataFrame(rows, columns=["opis_materialu", "indeks", "nazwa", "score"])
    df_result.columns = ["Opis materiału", "Indeks", "Nazwa materiału", "Prawdopodobieństwo poprawności"]
    buf = io.BytesIO()
    df_result.to_excel(buf, index=False, engine="openpyxl")
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=wyniki_indeksow.xlsx"},
    )


@router.post("/generate-description", response_model=GenerateDescriptionResponse)
def api_generate_description(req: GenerateDescriptionRequest):
    from app.services.groq_client import generate_index_description

    scraped = {
        "title": req.nazwa,
        "description": req.query,
        "specifications": {},
    }
    result = generate_index_description(
        scraped, nazwa=req.nazwa, indeks=req.indeks, model=req.model,
    )
    is_error = result.startswith("BŁĄD:")
    return GenerateDescriptionResponse(description=result, error=is_error)
