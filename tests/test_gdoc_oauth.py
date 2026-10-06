import pytest

from lisn.errors import ExtractionError
from lisn.extract import gdoc_oauth
from lisn.extract.gdoc import extract_gdoc

URL = "https://docs.google.com/document/d/abc123/edit"
LOGIN = "<html><head><title>Sign in</title><meta content='https://accounts.google.com/signin'></head></html>"
DOC = "<html><head><title>Private Doc</title></head><body><p>Secret paragraph.</p></body></html>"


def test_private_doc_uses_drive_when_logged_in(monkeypatch):
    calls = []
    result = extract_gdoc(URL, fetch=lambda url: LOGIN, private_fetch=lambda doc_id: calls.append(doc_id) or DOC)
    assert calls == ["abc123"] and result.title == "Private Doc"


def test_private_doc_without_login_raises(monkeypatch):
    monkeypatch.setattr("lisn.extract.gdoc_oauth.is_logged_in", lambda: False)
    with pytest.raises(ExtractionError, match="lisn gdoc login"):
        extract_gdoc(URL, fetch=lambda url: LOGIN)


def test_oauth_helpers(tmp_path, monkeypatch):
    monkeypatch.setattr(gdoc_oauth, "config_dir", lambda: tmp_path)
    assert not gdoc_oauth.is_logged_in()
    with pytest.raises(ExtractionError, match="client secret"):
        gdoc_oauth.login()
    with pytest.raises(ExtractionError, match="Not signed in"):
        gdoc_oauth.load_credentials()
    gdoc_oauth.token_path().write_text("{not json")
    with pytest.raises(ExtractionError, match="unreadable"):
        gdoc_oauth.load_credentials()
    assert gdoc_oauth.logout() is True and gdoc_oauth.logout() is False


def test_login_flow_with_fake_google(tmp_path, monkeypatch):
    monkeypatch.setattr(gdoc_oauth, "config_dir", lambda: tmp_path)
    secret = tmp_path / "secret.json"
    secret.write_text("{}")

    class Creds:
        def to_json(self):
            return '{"token": "t", "refresh_token": "r"}'

    class Flow:
        @classmethod
        def from_client_secrets_file(cls, path, scopes):
            return cls()

        def run_local_server(self, port, open_browser):
            return Creds()

    import types

    fake = types.SimpleNamespace(InstalledAppFlow=Flow)
    monkeypatch.setitem(__import__("sys").modules, "google_auth_oauthlib.flow", fake)
    path = gdoc_oauth.login(secret)
    assert path.exists() and gdoc_oauth.client_secret_path().exists() and gdoc_oauth.is_logged_in()


def test_export_private_doc_with_fake_service(monkeypatch):
    class Export:
        def execute(self):
            return b"<p>hi</p>"

    class Files:
        def export(self, fileId, mimeType):  # noqa: N803 - mirrors the Google API
            assert fileId == "id1" and mimeType == "text/html"
            return Export()

    class Service:
        def files(self):
            return Files()

    import types

    fake = types.SimpleNamespace(build=lambda *a, **k: Service())
    monkeypatch.setitem(__import__("sys").modules, "googleapiclient.discovery", fake)
    assert gdoc_oauth.export_private_doc("id1", credentials=object()) == "<p>hi</p>"
