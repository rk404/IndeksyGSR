"""Fabryka klienta Google Cloud Firestore."""

import json
from pathlib import Path

from google.cloud import firestore
from google.oauth2 import service_account

_KEY_FILE = Path(__file__).parent.parent.parent / "service_account.json"
_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]


def get_credentials() -> tuple[service_account.Credentials, str]:
    """Zwraca (credentials, project_id) z pliku service_account.json."""
    with open(_KEY_FILE) as f:
        info = json.load(f)
    creds = service_account.Credentials.from_service_account_info(info, scopes=_SCOPES)
    return creds, info["project_id"]


def get_client() -> firestore.Client:
    """Tworzy i zwraca klienta Firestore."""
    creds, project = get_credentials()
    return firestore.Client(credentials=creds, project=project)
