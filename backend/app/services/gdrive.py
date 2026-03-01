"""
gdrive.py — Google Drive client oparty na Service Account.

Użycie (CLI):
    python gdrive.py list
    python gdrive.py list <folder_id>
    python gdrive.py list --recursive          # drzewo całego folderu
    python gdrive.py list -r <folder_id>       # drzewo od podanego ID
    python gdrive.py upload <ścieżka_pliku>
    python gdrive.py upload <ścieżka_pliku> <folder_id>
    python gdrive.py download <file_id> <dest_path>
    python gdrive.py update <file_id> <ścieżka_pliku>
    python gdrive.py delete <file_id>
"""

import io
import os
import sys
import mimetypes
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

# ──────────────────────────────────────────────
# Konfiguracja
# ──────────────────────────────────────────────
DEFAULT_KEY_FILE = Path(__file__).parent.parent.parent / "service_account.json"
DEFAULT_FOLDER_ID = "1TBduyqnjyjXhWZpBOseHDn6iu46Cf2UN"
SCOPES = ["https://www.googleapis.com/auth/drive"]


class GoogleDriveClient:
    """Klient Google Drive z uwierzytelnianiem przez Service Account."""

    def __init__(self, key_file: str | Path = DEFAULT_KEY_FILE):
        key_file = Path(key_file)
        if not key_file.exists():
            raise FileNotFoundError(
                f"Nie znaleziono pliku klucza Service Account: {key_file}\n"
                "Pobierz plik JSON z Google Cloud Console i zapisz go jako service_account.json."
            )
        creds = service_account.Credentials.from_service_account_file(
            str(key_file), scopes=SCOPES
        )
        self.service = build("drive", "v3", credentials=creds)

    # ── Odczyt ────────────────────────────────

    def list_files(self, folder_id: str = DEFAULT_FOLDER_ID) -> list[dict]:
        """Zwraca listę plików i folderów w podanym katalogu."""
        results = []
        page_token = None
        query = f"'{folder_id}' in parents and trashed = false"

        while True:
            response = (
                self.service.files()
                .list(
                    q=query,
                    spaces="drive",
                    fields="nextPageToken, files(id, name, mimeType, size, modifiedTime)",
                    pageToken=page_token,
                )
                .execute()
            )
            results.extend(response.get("files", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break

        return results

    def list_files_recursive(
        self,
        folder_id: str = DEFAULT_FOLDER_ID,
        _indent: int = 0,
        _results: list | None = None,
    ) -> list[dict]:
        """Rekurencyjnie zbiera pliki i foldery jako plaska lista z polem 'indent'."""
        if _results is None:
            _results = []
        for item in self.list_files(folder_id):
            item["indent"] = _indent
            _results.append(item)
            if item["mimeType"] == "application/vnd.google-apps.folder":
                self.list_files_recursive(item["id"], _indent + 1, _results)
        return _results

    def download_file(self, file_id: str, dest_path: str | Path) -> Path:
        """Pobiera plik o podanym ID na dysk lokalny."""
        dest_path = Path(dest_path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        request = self.service.files().get_media(fileId=file_id)
        with open(dest_path, "wb") as f:
            downloader = MediaIoBaseDownload(f, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
                if status:
                    print(f"  Pobieranie: {int(status.progress() * 100)}%")

        print(f"Pobrano: {dest_path}")
        return dest_path

    # ── Zapis ─────────────────────────────────

    def upload_file(
        self,
        local_path: str | Path,
        folder_id: str = DEFAULT_FOLDER_ID,
        mime_type: str | None = None,
    ) -> dict:
        """Wgrywa nowy plik do wskazanego folderu. Zwraca metadane nowego pliku."""
        local_path = Path(local_path)
        if not local_path.exists():
            raise FileNotFoundError(f"Plik nie istnieje: {local_path}")

        if mime_type is None:
            mime_type, _ = mimetypes.guess_type(str(local_path))
            mime_type = mime_type or "application/octet-stream"

        metadata = {"name": local_path.name, "parents": [folder_id]}
        media = MediaFileUpload(str(local_path), mimetype=mime_type, resumable=True)

        file = (
            self.service.files()
            .create(body=metadata, media_body=media, fields="id, name, webViewLink")
            .execute()
        )
        print(f"Wgrano: {file['name']}  (id: {file['id']})")
        return file

    def update_file(self, file_id: str, local_path: str | Path) -> dict:
        """Zastępuje zawartość istniejącego pliku Drive nową wersją lokalną."""
        local_path = Path(local_path)
        if not local_path.exists():
            raise FileNotFoundError(f"Plik nie istnieje: {local_path}")

        mime_type, _ = mimetypes.guess_type(str(local_path))
        mime_type = mime_type or "application/octet-stream"

        media = MediaFileUpload(str(local_path), mimetype=mime_type, resumable=True)
        file = (
            self.service.files()
            .update(fileId=file_id, media_body=media, fields="id, name, modifiedTime")
            .execute()
        )
        print(f"Zaktualizowano: {file['name']}  (id: {file['id']})")
        return file

    # ── Usuwanie ──────────────────────────────

    def delete_file(self, file_id: str) -> None:
        """Przenosi plik do kosza na Google Drive."""
        self.service.files().delete(fileId=file_id).execute()
        print(f"Usunięto plik o id: {file_id}")


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────

def _print_files(files: list[dict], recursive: bool = False) -> None:
    if not files:
        print("Brak plików w folderze.")
        return
    if recursive:
        for f in files:
            indent = "  " * f.get("indent", 0)
            is_folder = f["mimeType"] == "application/vnd.google-apps.folder"
            label = "[FOLDER]" if is_folder else "[PLIK]  "
            size = f.get("size", "")
            size_str = f"{int(size):,} B" if size else ""
            name = f"{f['name']}/" if is_folder else f['name']
            print(f"{indent}{label}  {name:<45} {f['id']}  {size_str}")
    else:
        print(f"{'Nazwa':<45} {'ID':<35} {'Rozmiar':>10}  Zmodyfikowano")
        print("-" * 105)
        for f in files:
            size = f.get("size", "-")
            if size != "-":
                size = f"{int(size):,} B"
            print(
                f"{f['name']:<45} {f['id']:<35} {size:>10}  {f.get('modifiedTime', '')}"
            )


def main():
    client = GoogleDriveClient()
    args = sys.argv[1:]

    if not args or args[0] == "list":
        recursive = "--recursive" in args or "-r" in args
        remaining = [a for a in args[1:] if a not in ("--recursive", "-r")]
        folder_id = remaining[0] if remaining else DEFAULT_FOLDER_ID
        print(f"Folder: {folder_id}\n")
        if recursive:
            _print_files(client.list_files_recursive(folder_id), recursive=True)
        else:
            _print_files(client.list_files(folder_id))

    elif args[0] == "upload":
        if len(args) < 2:
            print("Użycie: python gdrive.py upload <plik> [folder_id]")
            sys.exit(1)
        folder_id = args[2] if len(args) > 2 else DEFAULT_FOLDER_ID
        client.upload_file(args[1], folder_id)

    elif args[0] == "download":
        if len(args) < 3:
            print("Użycie: python gdrive.py download <file_id> <dest_path>")
            sys.exit(1)
        client.download_file(args[1], args[2])

    elif args[0] == "update":
        if len(args) < 3:
            print("Użycie: python gdrive.py update <file_id> <plik>")
            sys.exit(1)
        client.update_file(args[1], args[2])

    elif args[0] == "delete":
        if len(args) < 2:
            print("Użycie: python gdrive.py delete <file_id>")
            sys.exit(1)
        client.delete_file(args[1])

    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
