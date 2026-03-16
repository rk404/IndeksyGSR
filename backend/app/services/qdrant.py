"""Fabryka klienta Qdrant."""

import os
from pathlib import Path

from dotenv import load_dotenv
from qdrant_client import QdrantClient

load_dotenv(Path(__file__).parent.parent.parent / ".env")


def get_client() -> QdrantClient:
    """Tworzy i zwraca klienta Qdrant na podstawie konfiguracji z .env."""
    url = os.getenv("QDRANT_URL")
    api_key = os.getenv("QDRANT_API_KEY")
    if not url:
        raise RuntimeError("Brak QDRANT_URL w .env")
    return QdrantClient(url=url, api_key=api_key, timeout=120)
