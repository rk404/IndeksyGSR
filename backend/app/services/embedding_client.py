"""
embedding_client.py — Klient HTTP do serwisu embedding_service.

Dostarcza proxy-obiekty (EmbeddingModel, EmbeddingReranker) z interfejsem
identycznym jak FlagEmbedding, dzięki czemu search.py, vectorize.py
i suggest.py nie wymagają zmian logiki.

Serwis musi być uruchomiony wcześniej:
    uv run uvicorn app.services.embedding_service:app --port 8080
"""

from __future__ import annotations

import os

import httpx
import numpy as np

EMBEDDING_SERVICE_URL = os.getenv("EMBEDDING_SERVICE_URL", "http://localhost:8080")

_HTTP_TIMEOUT = 120.0  # sekundy — duże batche mogą być wolne


class EmbeddingModel:
    """
    Proxy BGE-M3 przez HTTP.

    Interfejs zgodny z BGEM3FlagModel.encode():
        out = model.encode(texts, return_dense=True, return_sparse=True, ...)
        out["dense_vecs"]       → np.ndarray (N, 1024)
        out["lexical_weights"]  → list[dict[str, float]]
    """

    def __init__(self, base_url: str = EMBEDDING_SERVICE_URL) -> None:
        self._url = base_url.rstrip("/") + "/encode"

    def encode(
        self,
        texts: list[str],
        return_dense: bool = True,
        return_sparse: bool = True,
        return_colbert_vecs: bool = False,
    ) -> dict:
        resp = httpx.post(
            self._url,
            json={"texts": texts, "return_sparse": return_sparse},
            timeout=_HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        result: dict = {}
        if return_dense:
            result["dense_vecs"] = np.array(data["dense_vecs"], dtype=np.float32)
        if return_sparse:
            result["lexical_weights"] = data.get("lexical_weights", [{}] * len(texts))
        return result


class EmbeddingReranker:
    """
    Proxy BGE-reranker przez HTTP.

    Interfejs zgodny z FlagReranker.compute_score():
        scores = reranker.compute_score([(query, passage), ...])
        → list[float]
    """

    def __init__(self, base_url: str = EMBEDDING_SERVICE_URL) -> None:
        self._url = base_url.rstrip("/") + "/rerank"

    def compute_score(self, pairs: list[tuple[str, str]], normalize: bool = True) -> list[float]:
        if not pairs:
            return []
        query = pairs[0][0]
        passages = [p for _, p in pairs]
        resp = httpx.post(
            self._url,
            json={"query": query, "passages": passages, "normalize": normalize},
            timeout=_HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()["scores"]
