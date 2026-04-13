"""Pydantic schemas for API request/response models."""

from __future__ import annotations

from pydantic import BaseModel, Field


# ── Search ──

class SearchRequest(BaseModel):
    query: str
    top_k: int = Field(default=10, ge=1, le=50)
    rerank: bool = False


class SearchResult(BaseModel):
    qdrant_id: int | str | None = None
    indeks: str
    nazwa: str
    komb_id: str = ""
    jdmr_nazwa: str = ""
    score: float


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]


# ── Search by URL ──

class SearchUrlRequest(BaseModel):
    url: str
    top_k: int = Field(default=10, ge=1, le=50)
    rerank: bool = False


class ScrapedData(BaseModel):
    title: str = ""
    price: str = ""
    specifications: dict[str, str] = {}
    description: str = ""


class SearchUrlResponse(BaseModel):
    scraped: ScrapedData
    query: str
    results: list[SearchResult]


# ── Save selection ──

class SaveSelectionRequest(BaseModel):
    query: str
    source: str = "text"
    results: list[SearchResult]
    groq_descriptions: dict[str, str] = {}


# ── Generate description (Groq) ──

class GenerateDescriptionRequest(BaseModel):
    nazwa: str = ""
    indeks: str = ""
    query: str = ""
    model: str | None = None


class GenerateDescriptionResponse(BaseModel):
    description: str
    error: bool = False


# ── Segments ──

class SegmentTreeResponse(BaseModel):
    pos1: dict[str, str]  # slit_id (as str) → opis
    pos1_kod: dict[str, str]
    pos2_by_parent: dict[str, list[list]]  # parent_slit_id → [[slit_id, opis], ...]
    pos3_by_parent: dict[str, list[list]]
    pos2_kod: dict[str, str]
    pos3_kod: dict[str, str]
    pos4_values: list[str]
    pos5_values: list[str]
    pos6_values: list[str]


# ── Suggest ──

class SuggestRequest(BaseModel):
    query: str
    top_n: int = Field(default=3, ge=1, le=10)


class SegmentProposalResponse(BaseModel):
    seg1_slit_id: int
    seg1_text: str
    seg2_slit_id: int
    seg2_text: str
    seg3_slit_id: int
    seg3_text: str
    score: float


# ── Propose ──

class ProposeRequest(BaseModel):
    query: str
    seg1: str
    seg2: str
    seg3: str
    seg4: str = "0"
    seg5: str = "0"
    seg6: str = "0"
    kod1: str = ""
    kod2: str = ""
    kod3: str = ""
    nazwa: str
    indeks: str = ""


class ProposeResponse(BaseModel):
    id: str


class ProposalItem(BaseModel):
    id: str
    query: str = ""
    indeks: str = ""
    nazwa: str = ""
    seg1: str = ""
    seg2: str = ""
    seg3: str = ""
    seg4: str = ""
    seg5: str = ""
    seg6: str = ""
    status: str = "proposed"
    proposed_at: str = ""
