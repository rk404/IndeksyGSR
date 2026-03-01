"""
parse_email.py — Parser pliku .pst z zapisem do Firestore i GCS.

Użycie:
    python parse_email.py                        # pobierz pst z Drive i przetwórz
    python parse_email.py --local plik.pst       # parsuj lokalny plik
    python parse_email.py --no-attachments       # pomiń zapis załączników
    python parse_email.py --dry-run              # parsuj bez zapisu do bazy
"""

import argparse
import hashlib
import html as html_module
import logging
import re
import uuid
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

import pypff

from app.services.gdrive import GoogleDriveClient
from app.services import firestore as firestore_svc
from app.services import gcs as gcs_svc

# ──────────────────────────────────────────────
# Konfiguracja
# ──────────────────────────────────────────────
GCS_BUCKET_NAME = "projekt-email-attachments"
FIRESTORE_COLLECTION = "emails"

# ID pliku .pst na Google Drive
PST_FILE_ID = "1CYL0zSzKnr0r70W-Nd89_vmD3BiAePjK"
PST_LOCAL_PATH = Path(__file__).parent.parent.parent / "data" / "indeksy_zapytania_z7dni.pst"

# Wzorzec linków do sklepów (plain text)
SHOP_URL_PATTERN = re.compile(r"https?://[^\s\"'<>\)\]]+", re.IGNORECASE)
# Wzorzec href w HTML
HREF_PATTERN = re.compile(r'href=["\']?(https?://[^"\' >]+)', re.IGNORECASE)

# Domeny wykluczane ze stopek maili, mediów społecznościowych itp.
EXCLUDED_DOMAINS = {
    # Firma nadawcy
    "remontowa.com.pl",
    "woodwardgroup.ca",
    # Media społecznościowe
    "linkedin.com",
    "facebook.com",
    "twitter.com",
    "instagram.com",
    # Techniczne / Microsoft
    "schemas.microsoft.com",
    "w3.org",
    "schemas.openxmlformats.org",
}


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _safe_str(val) -> str:
    if val is None:
        return ""
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")
    return str(val).strip()


# Linie typowe dla stopki maila
_SIG_LINE_RE = re.compile(
    r"^("
    r"[-—]{2,}\s*$"                           # -- separator
    r"|[TKMFtkmf]\s{1,4}\+?[\d\s\(\)]{6,}"   # T +48 58..., K +48...
    r"|www\.\S+"                               # www.firma.pl
    r"|Wiadomo[śs][ćc] jest przeznaczona"      # PL disclaimer
    r"|This e.?mail is intended"               # EN disclaimer
    r")",
    re.IGNORECASE,
)


def strip_signature(text: str) -> tuple[str, str]:
    """Oddziela treść maila od stopki (podpis, dane kontaktowe, disclaimer).

    Returns:
        (body, signature) — oba jako plain text
    """
    lines = text.splitlines()
    sig_start = None

    for i, line in enumerate(lines):
        if _SIG_LINE_RE.match(line.strip()):
            # Szukaj pustej linii przed triggerem (w promieniu 6 linii)
            # — pusta linia to naturalny separator treści od podpisu
            cut = i  # domyślnie: tnij tuż przed triggerem
            for k in range(i - 1, max(i - 7, -1), -1):
                if not lines[k].strip():   # pusta linia znaleziona
                    cut = k + 1            # podpis zaczyna się po niej
                    break
            sig_start = max(cut, 1)
            break


    if sig_start is None or sig_start == 0:
        return text.strip(), ""

    body = "\n".join(lines[:sig_start]).strip()
    signature = "\n".join(lines[sig_start:]).strip()
    return body, signature


# Nagłówki cytowanej wiadomości (Outlook PL/EN)
_THREAD_HEADER_RE = re.compile(
    r"^(From|Od):\s+.+",
    re.IGNORECASE | re.MULTILINE,
)

# Pola nagłówka wątku
_HEADER_FIELD_RE = re.compile(
    r"^(From|Od|Sent|Wysłano|To|Do|Cc|DW|Subject|Temat):\s*(.*)",
    re.IGNORECASE,
)


def _strip_thread(signature: str) -> str:
    """Usuwa cytowaną korespondencję ze stopki (tryb C — strip)."""
    m = _THREAD_HEADER_RE.search(signature)
    if m:
        return signature[: m.start()].strip()
    return signature


def _parse_thread(signature: str) -> list[dict]:
    """Wyodrębnia cytowane wiadomości ze stopki jako listę słowników (tryb B — split)."""
    matches = list(_THREAD_HEADER_RE.finditer(signature))
    if not matches:
        return []

    messages = []
    boundaries = [m.start() for m in matches] + [len(signature)]

    for start, end in zip(boundaries, boundaries[1:]):
        chunk = signature[start:end].strip()
        lines = chunk.splitlines()

        headers: dict[str, str] = {}
        body_lines_start = 0
        for i, line in enumerate(lines):
            hm = _HEADER_FIELD_RE.match(line)
            if hm:
                key = hm.group(1).lower()
                headers[key] = hm.group(2).strip()
                body_lines_start = i + 1
            elif not line.strip() and not headers:
                continue
            elif headers:
                # Pierwsza linia niebędąca nagłówkiem → koniec sekcji nagłówkowej
                body_lines_start = i
                break

        raw_body = "\n".join(lines[body_lines_start:]).strip()
        body_clean, _ = strip_signature(raw_body)

        msg = {
            "sender":     headers.get("from") or headers.get("od", ""),
            "date":       headers.get("sent") or headers.get("wysłano", ""),
            "recipients": headers.get("to") or headers.get("do", ""),
            "subject":    headers.get("subject") or headers.get("temat", ""),
            "body":       body_clean,
        }
        if any(msg.values()):
            messages.append(msg)

    return messages


class _TextExtractor(HTMLParser):
    """Prosty parser HTML → plain text."""
    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._skip_tags = {"script", "style", "head"}
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._skip_tags:
            self._skip += 1
        if tag in ("br", "p", "div", "tr", "li"):
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._skip_tags:
            self._skip = max(0, self._skip - 1)

    def handle_data(self, data):
        if self._skip == 0:
            self._parts.append(data)

    def get_text(self) -> str:
        text = "".join(self._parts)
        # Znormalizuj białe znaki
        lines = [line.strip() for line in text.splitlines()]
        lines = [l for l in lines if l]
        return "\n".join(lines)


def _detect_charset(html_bytes: bytes) -> str:
    """Wykrywa kodowanie z meta tagu HTML, domyślnie cp1250 dla polskich maili Outlook."""
    try:
        snippet = html_bytes[:2048].decode("ascii", errors="ignore")
        m = re.search(r'charset=["\']?([\w\-]+)', snippet, re.IGNORECASE)
        if m:
            return m.group(1)
    except Exception:
        pass
    return "cp1250"


def _html_to_text(html_raw) -> str:
    """Konwertuje HTML (bytes lub str) na plain text z wykrywaniem kodowania."""
    if not html_raw:
        return ""
    # Zdekoduj bajty z właściwym kodowaniem
    if isinstance(html_raw, bytes):
        charset = _detect_charset(html_raw)
        html_str = html_raw.decode(charset, errors="replace")
    else:
        html_str = str(html_raw)
    parser = _TextExtractor()
    try:
        parser.feed(html_str)
        return html_module.unescape(parser.get_text())
    except Exception:
        return re.sub(r"<[^>]+>", " ", html_str).strip()


# ──────────────────────────────────────────────
# Anonimizacja PII
# ──────────────────────────────────────────────

_EMAIL_RE = re.compile(r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b')

_nlp = None


def _get_nlp():
    global _nlp
    if _nlp is None:
        import spacy  # noqa: PLC0415
        _nlp = spacy.load("pl_core_news_lg")
    return _nlp


def anonymize_pii(text: str) -> str:
    """Usuwa dane osobowe z tekstu.

    Zastępuje:
      - Adresy email → [EMAIL]    (regex)
      - Imiona i nazwiska → [OSOBA]  (spaCy NER, model pl_core_news_lg)
    """
    if not text:
        return text

    # 1. Adresy email — regex
    text = _EMAIL_RE.sub("[EMAIL]", text)

    # 2. Imiona i nazwiska — spaCy NER
    nlp = _get_nlp()
    doc = nlp(text)
    parts: list[str] = []
    last = 0
    for ent in doc.ents:
        if ent.label_ == "persName":
            parts.append(text[last:ent.start_char])
            parts.append("[OSOBA]")
            last = ent.end_char
    parts.append(text[last:])
    return "".join(parts)


def _anonymize_email(record: dict) -> dict:
    """Anonimizuje PII we wszystkich polach tekstowych rekordu maila."""
    for field in ("subject", "body_text", "signature"):
        if record.get(field):
            record[field] = anonymize_pii(record[field])

    if record.get("sender"):
        record["sender"] = anonymize_pii(record["sender"])

    if record.get("recipients"):
        record["recipients"] = [anonymize_pii(r) for r in record["recipients"]]

    for msg in record.get("thread_messages", []):
        for field in ("body", "subject", "sender"):
            if msg.get(field):
                msg[field] = anonymize_pii(msg[field])
        if msg.get("recipients"):
            if isinstance(msg["recipients"], list):
                msg["recipients"] = [anonymize_pii(r) for r in msg["recipients"]]
            else:
                msg["recipients"] = anonymize_pii(msg["recipients"])

    return record


# ──────────────────────────────────────────────
# PST traversal
# ──────────────────────────────────────────────

def _iter_messages(folder):
    """Rekurencyjnie iteruje przez wszystkie wiadomości w folderze PST."""
    for i in range(folder.number_of_sub_messages):
        try:
            yield folder.get_sub_message(i)
        except Exception as exc:
            log.warning("Błąd odczytu wiadomości %d: %s", i, exc)

    for i in range(folder.number_of_sub_folders):
        try:
            sub = folder.get_sub_folder(i)
            yield from _iter_messages(sub)
        except Exception as exc:
            log.warning("Błąd odczytu podfolderu %d: %s", i, exc)


# ──────────────────────────────────────────────
# Klasa parsera
# ──────────────────────────────────────────────

class PstParser:
    def __init__(
        self,
        save_attachments: bool = True,
        dry_run: bool = False,
        thread_mode: str = "keep",  # "keep" | "strip" | "split"
        anonymize: bool = False,
    ):
        self.save_attachments = save_attachments
        self.dry_run = dry_run
        self.thread_mode = thread_mode
        self.anonymize = anonymize

        self.drive = GoogleDriveClient()

        if not dry_run:
            self.db = firestore_svc.get_client()
            gcs = gcs_svc.get_client()
            self.bucket = gcs.bucket(GCS_BUCKET_NAME)

    # ── Download ─────────────────────────────

    def download_pst(
        self,
        file_id: str = PST_FILE_ID,
        dest: Path = PST_LOCAL_PATH,
    ) -> Path:
        if dest.exists():
            log.info("Plik .pst już istnieje lokalnie: %s (pomijam pobieranie)", dest.name)
            return dest
        log.info("Pobieranie pliku .pst z Google Drive (%s)...", file_id)
        return self.drive.download_file(file_id, dest)

    # ── Ekstrakcja URL-i ──────────────────────

    @staticmethod
    def extract_shop_urls(plain_text: str, html_body: str = "") -> list[str]:
        """Ekstrachuje URL-e z plain text i HTML body (href), filtrując wykluczone domeny."""
        from urllib.parse import urlparse
        urls = []
        if plain_text:
            urls.extend(SHOP_URL_PATTERN.findall(plain_text))
        if html_body:
            urls.extend(HREF_PATTERN.findall(html_body))
            urls.extend(SHOP_URL_PATTERN.findall(html_body))

        # Odfiltruj wykluczone domeny
        def _is_allowed(url: str) -> bool:
            try:
                host = urlparse(url).netloc.lower().removeprefix("www.")
                return not any(host == d or host.endswith("." + d) for d in EXCLUDED_DOMAINS)
            except Exception:
                return False

        return list(dict.fromkeys(u for u in urls if _is_allowed(u)))


    # ── Parsowanie PST ────────────────────────

    def parse(self, pst_path: Path) -> list[dict]:
        emails = []
        log.info("Otwieram plik: %s", pst_path)

        pff = pypff.file()
        pst_source = pst_path.name
        pff.open(str(pst_path))
        try:
            root = pff.get_root_folder()
            for message in _iter_messages(root):
                try:
                    emails.append(self._extract_message(message, pst_source))
                except Exception as exc:
                    log.warning("Błąd przetwarzania wiadomości: %s", exc)
        finally:
            pff.close()

        log.info("Sparsowano %d wiadomości", len(emails))
        return emails

    def _extract_message(self, message, pst_source: str) -> dict:
        msg_id = str(uuid.uuid4())

        # Treść plain text
        body = ""
        try:
            raw = message.plain_text_body
            body = _safe_str(raw) if raw else ""
        except Exception:
            pass

        # Treść HTML — zachowaj surowe bajty dla poprawnego dekodowania
        html_body_raw = None
        try:
            raw_html = message.html_body
            if raw_html:
                html_body_raw = raw_html  # bytes — nie konwertuj przez _safe_str!
        except Exception:
            pass

        # Jeśli brak plain text — wyciągnij tekst z HTML z wykrywaniem kodowania
        if not body and html_body_raw:
            body = _html_to_text(html_body_raw)  # bytes → charset wykryty z meta tagu

        # Dla ekstrakcji URL-i zdekoduj HTML z poprawnym kodowaniem
        html_body_str = ""
        if html_body_raw:
            charset = _detect_charset(html_body_raw)
            html_body_str = html_body_raw.decode(charset, errors="replace")

        # Metadane
        subject = _safe_str(getattr(message, "subject", ""))
        sender_name = _safe_str(getattr(message, "sender_name", ""))
        sender_email = _safe_str(getattr(message, "sender_email_address", ""))
        sender = f"{sender_name} <{sender_email}>" if sender_name and sender_email else (sender_email or sender_name)

        # Odbiorcy z nagłówków transport
        recipients = self._parse_recipients(message)

        # Data
        date = None
        try:
            for attr in ("delivery_time", "creation_time", "client_submit_time"):
                dt = getattr(message, attr, None)
                if dt:
                    date = dt.isoformat()
                    break
        except Exception:
            pass

        # Linki (szukamy w plain text i poprawnie zdekodowanym HTML)
        shop_urls = self.extract_shop_urls(body, html_body_str)

        # Oddziel treść od stopki, a ze stopki — cytowany wątek
        body_clean, signature = strip_signature(body)

        thread_messages: list[dict] = []
        if self.thread_mode == "strip":
            signature = _strip_thread(signature)
        elif self.thread_mode == "split":
            thread_messages = _parse_thread(signature)
            signature = _strip_thread(signature)

        # Załączniki
        attachments = self._handle_attachments(message, msg_id)

        record = {
            "id": msg_id,
            "pst_source": pst_source,
            "subject": subject,
            "sender": sender,
            "recipients": recipients,
            "date": date,
            "body_text": body_clean,
            "signature": signature,
            "thread_messages": thread_messages,
            "shop_urls": shop_urls,
            "has_attachments": bool(attachments),
            "attachments": attachments,
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }

        if self.anonymize:
            record = _anonymize_email(record)

        return record

    def _parse_recipients(self, message) -> list[str]:
        recipients = []
        try:
            headers = _safe_str(getattr(message, "transport_headers", ""))
            to_match = re.search(r"^To:\s*(.+?)(?=\r?\n\S|\Z)", headers, re.MULTILINE | re.DOTALL)
            if to_match:
                raw = to_match.group(1).replace("\r\n", " ").replace("\n", " ")
                for addr in raw.split(","):
                    addr = addr.strip()
                    if addr:
                        recipients.append(addr)
        except Exception:
            pass
        return recipients

    # ── Załączniki ────────────────────────────

    def _handle_attachments(self, message, msg_id: str) -> list[dict]:
        records = []
        try:
            n = message.number_of_attachments
            if not n:
                return records

            for i in range(n):
                try:
                    att = message.get_attachment(i)
                    name = _safe_str(
                        getattr(att, "name", None)
                        or getattr(att, "long_filename", None)
                        or f"attachment_{i}"
                    )
                    size = getattr(att, "size", 0) or 0

                    # Tylko pliki PDF
                    if not name.lower().endswith(".pdf"):
                        log.debug("  Pomijam załącznik (nie PDF): %s", name)
                        continue

                    data = att.read_buffer(size) if size > 0 else b""

                    if self.save_attachments and not self.dry_run and data:
                        gcs_path = f"attachments/{msg_id}/{name}"
                        blob = self.bucket.blob(gcs_path)
                        blob.upload_from_string(data)
                        records.append({
                            "filename": name,
                            "gcs_path": gcs_path,
                            "size_bytes": len(data),
                            "md5": hashlib.md5(data).hexdigest(),
                        })
                        log.debug("  Załącznik: %s → GCS", name)
                    else:
                        records.append({
                            "filename": name,
                            "size_bytes": size,
                        })
                except Exception as exc:
                    log.warning("  Błąd załącznika #%d: %s", i, exc)
        except Exception:
            pass
        return records

    # ── Zapis do Firestore ────────────────────

    def save_to_firestore(self, emails: list[dict]) -> int:
        if self.dry_run:
            log.info("[DRY RUN] Pominięto zapis do Firestore (%d rekordów)", len(emails))
            return 0

        collection = self.db.collection(FIRESTORE_COLLECTION)
        batch = self.db.batch()
        saved = 0

        for i, email in enumerate(emails):
            batch.set(collection.document(email["id"]), email)
            saved += 1
            if (i + 1) % 400 == 0:
                batch.commit()
                batch = self.db.batch()
                log.info("  Zapisano %d/%d...", saved, len(emails))

        batch.commit()
        log.info("Zapisano %d dokumentów do Firestore (collection: '%s')", saved, FIRESTORE_COLLECTION)
        return saved

    # ── Czyszczenie ───────────────────────────

    def reset_all(self, pst_source: str) -> None:
        """Usuwa dokumenty i pliki powiązane z danym plikiem PST."""
        self._clear_firestore(pst_source)
        self._clear_gcs(pst_source)

    def _clear_firestore(self, pst_source: str) -> None:
        log.info("Czyszczę Firestore — pst_source='%s'...", pst_source)
        collection = self.db.collection(FIRESTORE_COLLECTION)
        query = collection.where("pst_source", "==", pst_source)
        deleted = 0
        batch = self.db.batch()
        for i, doc in enumerate(query.stream()):
            batch.delete(doc.reference)
            deleted += 1
            if (i + 1) % 400 == 0:
                batch.commit()
                batch = self.db.batch()
        batch.commit()
        log.info("  Usunięto %d dokumentów z Firestore", deleted)

    def _clear_gcs(self, pst_source: str) -> None:
        prefix = f"attachments/{pst_source}/"
        log.info("Czyszczę GCS — prefix: %s...", prefix)
        blobs = list(self.bucket.list_blobs(prefix=prefix))
        if blobs:
            self.bucket.delete_blobs(blobs)
        log.info("  Usunięto %d plików z GCS", len(blobs))

    def purge_all(self) -> None:
        """Usuwa WSZYSTKIE dokumenty z Firestore i WSZYSTKIE pliki z GCS."""
        log.info("Czyszczę cały Firestore (collection: '%s')...", FIRESTORE_COLLECTION)
        collection = self.db.collection(FIRESTORE_COLLECTION)
        deleted = 0
        batch = self.db.batch()
        for i, doc in enumerate(collection.stream()):
            batch.delete(doc.reference)
            deleted += 1
            if (i + 1) % 400 == 0:
                batch.commit()
                batch = self.db.batch()
        batch.commit()
        log.info("  Usunięto %d dokumentów z Firestore", deleted)

        log.info("Czyszczę cały GCS (bucket: %s)...", GCS_BUCKET_NAME)
        blobs = list(self.bucket.list_blobs())
        if blobs:
            self.bucket.delete_blobs(blobs)
        log.info("  Usunięto %d plików z GCS", len(blobs))

    # ── Podsumowanie ──────────────────────────

    @staticmethod
    def print_summary(emails: list[dict]) -> None:
        total = len(emails)
        with_urls = sum(1 for e in emails if e["shop_urls"])
        with_att = sum(1 for e in emails if e["has_attachments"])
        all_urls = [u for e in emails for u in e["shop_urls"]]

        print("\n" + "=" * 60)
        print(f"  Łącznie wiadomości  : {total}")
        print(f"  Z linkami sklepów   : {with_urls}")
        print(f"  Z załącznikami      : {with_att}")
        print(f"  Unikalne URL-e      : {len(set(all_urls))}")
        if all_urls:
            print("\n  Przykładowe URL-e:")
            for url in list(dict.fromkeys(all_urls))[:5]:
                print(f"    {url}")
        print("=" * 60 + "\n")


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Parser maili z pliku .pst → Firestore + GCS")
    ap.add_argument("--local", metavar="PLIK.PST", help="Użyj lokalnego pliku zamiast pobierać z Drive")
    ap.add_argument("--no-attachments", action="store_true", help="Pomiń upload załączników do GCS")
    ap.add_argument("--dry-run", action="store_true", help="Parsuj bez zapisu do Firestore/GCS")
    ap.add_argument("--reset", action="store_true", help="Wyczyść dane z tego pliku PST przed importem")
    ap.add_argument("--purge", action="store_true", help="Wyczyść WSZYSTKIE dane z Firestore i GCS (bez importu)")
    ap.add_argument(
        "--thread-mode",
        choices=["keep", "strip", "split"],
        default="keep",
        help=(
            "Obsługa cytowanej korespondencji: "
            "keep=zachowaj w stopce (domyślnie), "
            "strip=usuń z dokumentu, "
            "split=wyodrębnij jako thread_messages[]"
        ),
    )
    ap.add_argument(
        "--anonymize",
        action="store_true",
        help="Usuń dane osobowe (imiona, nazwiska, e-maile) przed zapisem do Firestore",
    )
    args = ap.parse_args()

    parser = PstParser(
        save_attachments=not args.no_attachments,
        dry_run=args.dry_run,
        thread_mode=args.thread_mode,
        anonymize=args.anonymize,
    )

    # --purge: wyczyść wszystko i zakończ
    if args.purge:
        if args.dry_run:
            log.info("[DRY RUN] Pomińąłem --purge")
        else:
            log.warning("PURGE: usuwanie WSZYSTKICH danych z Firestore i GCS!")
            parser.purge_all()
            log.info("Purge zakończony.")
        return

    pst_path = Path(args.local) if args.local else parser.download_pst()

    if args.reset and not args.dry_run:
        log.info("--- RESET: czyszczenie danych z '%s' ---", pst_path.name)
        parser.reset_all(pst_path.name)
        log.info("--- Reset zakończony, start importu ---")

    emails = parser.parse(pst_path)
    parser.print_summary(emails)

    if not args.dry_run:
        parser.save_to_firestore(emails)
        log.info("Gotowe!")
    else:
        log.info("[DRY RUN] Zakończono bez zapisu.")


if __name__ == "__main__":
    main()
