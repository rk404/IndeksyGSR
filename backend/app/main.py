"""FastAPI entry point for IndeksyGSR API."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.search import router as search_router
from app.api.segments import router as segments_router

app = FastAPI(title="IndeksyGSR API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(search_router, prefix="/api")
app.include_router(segments_router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok"}
