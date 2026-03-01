"""Fabryka klienta Google Cloud Storage."""

from google.cloud import storage

from app.services.firestore import get_credentials


def get_client() -> storage.Client:
    """Tworzy i zwraca klienta Google Cloud Storage."""
    creds, project = get_credentials()
    return storage.Client(credentials=creds, project=project)
