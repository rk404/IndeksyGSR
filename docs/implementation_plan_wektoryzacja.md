# Wyszukiwanie Semantyczne — Plan Implementacji

## Cel
Mając opis z maila (np. „proszę o indeks na śruby M20 ocynkowane ogniowo"), znaleźć pasujące indeksy materiałowe z bazy. Przeszukiwana powinna byc pełna baza indeksów. Dane zescrapowane powinny. byc tylko uzupelnieniem indeksow w bazie materialowej

## Wybrane technologie
- **Model:** `sdadas/st-polish-paraphrase-from-mpnet` (Sentence Transformers, 768 dim)
- **Vector DB:** Qdrant Cloud free tier
- **Dane:** `baza_indeksow.csv`(google drive) + slownik_segmentow.csv(google_drive) + `product_scrapes` (Firestore)

## Faza 1 — Konfiguracja Qdrant Cloud

1. Załóż konto: [cloud.qdrant.io](https://cloud.qdrant.io)
2. Utwórz klaster (free tier — 1 GB, region EU)
3. Skopiuj **URL klastra** i **API key**
4. Dodaj do pliku `.env` (gitignorowanego):
```
QDRANT_URL=https://xxx.qdrant.io
QDRANT_API_KEY=abc123...
```

## Faza 2 — Budowanie bogatego tekstu i wektoryzacja

### Nowy plik: `vectorize.py`

Dla każdego indeksu budujemy jeden tekst łączący:
```
[zdekodowany segment] + [nazwa] + [title ze sklepu] + [opis] + [specyfikacje]
```

**Przykład:**
```
Wejście:  M-LOZ-KUL-0-0-0-483 | ŁOŻYSKO KULKOWE SKOŚNE 3309-BD-TVH-L285
Słownik:  M=Materiał, LOZ=Łożyska, KUL=Kulkowe
Scraping: title="Łożysko skośne 3309", specs={"Typ": "Kulkowe skośne"}

Tekst:    "Materiał Łożyska Kulkowe ŁOŻYSKO KULKOWE SKOŚNE 3309-BD-TVH-L285
           Łożysko skośne 3309 Typ: Kulkowe skośne"
```

**Wektoryzacja i upload do Qdrant:**
```python
model = SentenceTransformer("sdadas/st-polish-paraphrase-from-mpnet")
vectors = model.encode(texts, batch_size=64, show_progress_bar=True)
# → upload do kolekcji "indeksy" w Qdrant
```

### Plik `.env` (gitignorowany)
```
QDRANT_URL=...
QDRANT_API_KEY=...
```

### CLI `vectorize.py`
```bash
python vectorize.py                 # wektoryzuj wszystkie
python vectorize.py --limit 100     # test na 100
python vectorize.py --recreate      # usuń kolekcję i utwórz od nowa
```

## Faza 3 — Wyszukiwanie

### Nowy plik: `search.py`
```python
results = search("śruby M20 ocynkowane ogniowo", top_k=5)
# → lista indeksów z wynikiem podobieństwa
```

### Integracja z Dashboardem
Nowa zakładka **🔍 Wyszukiwanie** w [dashboard.py](file:///Users/rafalpraca/Documents/Studia/PROJEKT2/PROJEKT/dashboard.py):
- Pole tekstowe: wpisz opis produktu
- Wyniki: top-10 indeksów z nazwą, wynikiem podobieństwa, linkiem do sklepu

## Nowe pliki

| Plik | Opis |
|---|---|
| `vectorize.py` | Buduje wektory i uploaduje do Qdrant |
| `search.py` | Funkcja wyszukiwania semantycznego |
| `.env` | Klucze Qdrant (nie commitować!) |

## Nowe zależności ([requirements.txt](file:///Users/rafalpraca/Documents/Studia/PROJEKT/PROJEKT2/requirements.txt))
```
sentence-transformers
qdrant-client
python-dotenv
```

## Kolejność prac
1. ✅ Konfiguracja Qdrant Cloud (ręcznie przez UI)
2. [ ] Implementacja `vectorize.py`
3. [ ] Test wektoryzacji na 100 indeksach
4. [ ] Pełna wektoryzacja (cała baza + scraping)
5. [ ] Implementacja `search.py`
6. [ ] Integracja z dashboardem

## Wymagane od Ciebie
> [!IMPORTANT]
> Przed implementacją udostępnij **słownik segmentów indeksów** (plik z Google Drive lub wklejony tutaj).
> Pozwoli to zdekodować kody jak `LOZ`, `KUL`, `M` → pełne polskie nazwy kategorii.
