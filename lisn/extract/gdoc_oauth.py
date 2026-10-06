"""Google sign-in for private Google Docs (Drive API, read-only scope).

Google does not allow shipping OAuth client secrets in open-source tools, so the user
creates a Desktop OAuth client in Google Cloud and runs `lisn gdoc login client_secret.json`
once. The refresh token is cached in the user config dir.
"""

from __future__ import annotations

import json
from pathlib import Path

from lisn.errors import ExtractionError
from lisn.paths import config_dir

SCOPES = ("https://www.googleapis.com/auth/drive.readonly",)


def token_path() -> Path:
    return config_dir() / "gdoc_token.json"


def client_secret_path() -> Path:
    return config_dir() / "gdoc_client_secret.json"


def is_logged_in() -> bool:
    return token_path().exists()


def login(client_secret: Path | None = None) -> Path:
    """Run the browser consent flow and cache the credentials. Returns the token path."""
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise ExtractionError("Google sign-in needs 'pip install \"lisn[gdoc]\"'.") from exc
    secret = client_secret or client_secret_path()
    if not secret.exists():
        raise ExtractionError(
            "No OAuth client secret found. Create a 'Desktop app' OAuth client in Google Cloud Console "
            "(Drive API enabled), download its JSON and run: lisn gdoc login <that file> "
            f"(it is then saved to {client_secret_path()})"
        )
    if secret != client_secret_path():
        client_secret_path().write_bytes(secret.read_bytes())
    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(secret), scopes=list(SCOPES))
        credentials = flow.run_local_server(port=0, open_browser=True)
    except Exception as exc:
        raise ExtractionError(f"Google sign-in failed: {exc}") from exc
    token_path().write_text(credentials.to_json(), encoding="utf-8")
    return token_path()


def logout() -> bool:
    path = token_path()
    existed = path.exists()
    path.unlink(missing_ok=True)
    return existed


def load_credentials():  # type: ignore[no-untyped-def]
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError as exc:
        raise ExtractionError("Google sign-in needs 'pip install \"lisn[gdoc]\"'.") from exc
    path = token_path()
    if not path.exists():
        raise ExtractionError("Not signed in to Google. Run: lisn gdoc login <client_secret.json>")
    try:
        credentials = Credentials.from_authorized_user_info(json.loads(path.read_text(encoding="utf-8")), list(SCOPES))
    except (ValueError, json.JSONDecodeError) as exc:
        raise ExtractionError(f"Cached Google token is unreadable ({exc}); run `lisn gdoc login` again.") from exc
    if credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
        except Exception as exc:
            raise ExtractionError(f"Could not refresh the Google token: {exc}. Run `lisn gdoc login` again.") from exc
        path.write_text(credentials.to_json(), encoding="utf-8")
    return credentials


def export_private_doc(doc_id: str, credentials=None) -> str:  # type: ignore[no-untyped-def]
    """Return the document as HTML via the Drive API files.export endpoint."""
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise ExtractionError("Google sign-in needs 'pip install \"lisn[gdoc]\"'.") from exc
    creds = credentials or load_credentials()
    try:
        service = build("drive", "v3", credentials=creds, cache_discovery=False)
        data = service.files().export(fileId=doc_id, mimeType="text/html").execute()
    except Exception as exc:
        raise ExtractionError(f"Drive API export failed: {exc}") from exc
    return data.decode("utf-8", errors="replace") if isinstance(data, bytes) else str(data)
