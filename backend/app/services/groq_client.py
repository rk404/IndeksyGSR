"""
groq_client.py — Klient Groq API do generowania opisów indeksów materiałowych.

Wymagane zmienne środowiskowe (.env):
    GROQ_API_KEY=gsk_...
    GROQ_MODEL=llama-3.3-70b-versatile   (opcjonalnie)
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent.parent / ".env")

_API_URL = "https://api.groq.com/openai/v1/chat/completions"
_DEFAULT_MODEL = "llama-3.3-70b-versatile"
_TIMEOUT = 30.0

_SYSTEM_PROMPT = """Jesteś ekspertem technicznym w dziedzinie materiałów budowlanych i instalacyjnych.
Na podstawie danych produktu ze sklepu internetowego generujesz rozszerzony opis indeksu materiałowego.
Opis powinien być zwięzły (3–5 zdań), techniczny, po polsku.
Zawieraj: zastosowanie, materiał, parametry techniczne (wymiary, normy, klasy), środowisko pracy.
Nie wymyślaj danych — opieraj się wyłącznie na dostarczonych informacjach."""

_CLASSIFIER_SYSTEM_PROMPT = """Jesteś klasyfikatorem tekstu.

Twoim zadaniem jest ocenić, czy podany tekst:
1. Jest rzeczywistym opisem produktu
2. NIE jest polityką cookies, RODO, regulaminem ani komunikatem strony

Weź pod uwagę tytuł produktu.

Zwróć TYLKO jedno słowo:
True - jeśli to poprawny opis produktu
False - jeśli to cookies / regulamin / śmieci / niepowiązany tekst

Nie dodawaj nic więcej."""

def _build_prompt(scraped: dict, nazwa: str = "", indeks: str = "") -> str:
    parts = []
    if indeks:
        parts.append(f"Kod indeksu: {indeks}")
    if nazwa:
        parts.append(f"Nazwa indeksu: {nazwa}")
    title = scraped.get("title", "").strip()
    if title:
        parts.append(f"Tytuł produktu ze sklepu: {title}")
    price = scraped.get("price", "").strip()
    if price:
        parts.append(f"Cena: {price}")
    specs = scraped.get("specifications") or {}
    if specs:
        spec_lines = "\n".join(f"  {k}: {v}" for k, v in list(specs.items())[:30])
        parts.append(f"Specyfikacja techniczna:\n{spec_lines}")
    desc = (scraped.get("description") or "").strip()
    if desc:
        parts.append(f"Opis ze strony produktu:\n{desc[:1500]}")
    parts.append("\nWygeneruj rozszerzony opis indeksu materiałowego.")
    return "\n\n".join(parts)


def generate_index_description(
    scraped: dict,
    nazwa: str = "",
    indeks: str = "",
    model: str | None = None,
) -> str:
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        return "BŁĄD: Brak GROQ_API_KEY w pliku .env"
    used_model = model or os.getenv("GROQ_MODEL", _DEFAULT_MODEL)
    prompt = _build_prompt(scraped, nazwa=nazwa, indeks=indeks)
    try:
        resp = httpx.post(
            _API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": used_model,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user",   "content": prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 512,
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except httpx.HTTPStatusError as e:
        return f"BŁĄD: Groq API {e.response.status_code} — {e.response.text[:200]}"
    except Exception as e:
        return f"BŁĄD: {e}"

def is_valid_product_description(
    description: str,
    title: str,
    model: str | None = None,
) -> bool:
    """ Sprawdza czy description jest opisem produktu a nie jest polityką cookies """

    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        return True
    if not description.strip():
        return False

    used_model = model or os.getenv("GROQ_MODEL", _DEFAULT_MODEL)
    prompt = f"""Tytuł produktu:
{title}

Tekst do oceny:
{description[:1500]}

Czy to jest poprawny opis produktu zgodny z tytułem?"""

    try:
        resp = httpx.post(
            _API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": used_model,
                "messages": [
                    {"role": "system", "content": _CLASSIFIER_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.0,  # deterministycznie
                "max_tokens": 5,
            },
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()

        answer = resp.json()["choices"][0]["message"]["content"].strip().upper()
        return answer.startswith("True")

    except Exception:
        return True