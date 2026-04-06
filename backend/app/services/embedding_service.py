"""
embedding_service.py — Long-running serwis FastAPI ładujący BGE-M3 i BGE-reranker raz przy starcie.

Modele ładowane są przy starcie serwisu (nie przy każdym zapytaniu), co eliminuje
wielominutowy cold-start w vectorize/dashboard/search.

Uruchomienie:
    uv run uvicorn app.services.embedding_service:app --port 8080

Endpointy:
    POST /encode  — dense + sparse embeddingi (BGE-M3)
    POST /rerank  — cross-encoder scores (BGE-reranker-v2-m3)
"""

from fastapi import FastAPI
from pydantic import BaseModel
from FlagEmbedding import BGEM3FlagModel, FlagReranker

app = FastAPI(title="Embedding Service")

_model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=False, device="cpu")
_reranker = FlagReranker("BAAI/bge-reranker-v2-m3", use_fp16=False, device="cpu")


class EncodeRequest(BaseModel):
    texts: list[str]
    return_sparse: bool = True


class RerankRequest(BaseModel):
    query: str
    passages: list[str]
    normalize: bool = True


@app.post("/encode")
def encode(req: EncodeRequest):
    out = _model.encode(req.texts, return_dense=True, return_sparse=req.return_sparse)
    result: dict = {"dense_vecs": out["dense_vecs"].tolist()}
    if req.return_sparse:
        result["lexical_weights"] = [
            {k: float(v) for k, v in w.items()} for w in out["lexical_weights"]
        ]
    return result


@app.post("/rerank")
def rerank(req: RerankRequest):
    scores = _reranker.compute_score(
        [(req.query, p) for p in req.passages], normalize=req.normalize
    )
    if hasattr(scores, "tolist"):
        scores = scores.tolist()
    elif not isinstance(scores, list):
        scores = [scores]
    return {"scores": scores}


def main() -> None:
    import uvicorn
    uvicorn.run("app.services.embedding_service:app", host="0.0.0.0", port=8080)
