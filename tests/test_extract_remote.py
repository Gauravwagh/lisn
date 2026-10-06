import pytest

from lisn.errors import ExtractionError
from lisn.extract import extract
from lisn.extract.gdoc import EXPORT_URL, extract_gdoc, gdoc_id, is_gdoc_url

GDOC_URL = "https://docs.google.com/document/d/1AbC_def-123/edit?usp=sharing"
GDOC_HTML = (
    "<html><head><title>Shared Doc</title></head><body>"
    "<h1 class='title'>Shared Doc</h1><p>First paragraph.</p><h2>Part</h2><p>Second.</p></body></html>"
)


def test_gdoc_url_parsing():
    assert is_gdoc_url(GDOC_URL)
    assert gdoc_id(GDOC_URL) == "1AbC_def-123"
    assert gdoc_id("https://docs.google.com/document/u/0/d/xyz/edit") == "xyz"
    assert not is_gdoc_url("https://example.com")
    with pytest.raises(ExtractionError):
        gdoc_id("https://example.com")


def test_gdoc_public_export():
    seen = []

    def fetch(url: str) -> str:
        seen.append(url)
        return GDOC_HTML

    result = extract_gdoc(GDOC_URL, fetch=fetch)
    assert seen == [EXPORT_URL.format(doc_id="1AbC_def-123")]
    assert result.title == "Shared Doc"
    assert [(b.kind, b.text) for b in result.blocks] == [
        ("heading", "Shared Doc"),
        ("paragraph", "First paragraph."),
        ("heading", "Part"),
        ("paragraph", "Second."),
    ]


def test_gdoc_private_detected():
    login = "<html><head><title>Sign in</title><meta content='https://accounts.google.com/signin'></head></html>"
    with pytest.raises(ExtractionError, match="private"):
        extract_gdoc(GDOC_URL, fetch=lambda url: login)


def test_gdoc_http_errors(monkeypatch):
    import urllib.error

    def boom(*_a, **_k):
        raise urllib.error.HTTPError("u", 403, "forbidden", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", boom)
    with pytest.raises(ExtractionError, match="private"):
        extract(GDOC_URL)


def test_web_dispatch_uses_trafilatura(monkeypatch):
    html = (
        "<html><head><title>Web Page</title></head><body><article><h1>Web Page</h1>"
        "<p>A paragraph long enough to be treated as the main content of this little page by trafilatura.</p>"
        "<p>Another paragraph with sufficient length to keep the extractor happy and the content intact.</p>"
        "</article><nav>menu</nav></body></html>"
    )
    monkeypatch.setattr("trafilatura.fetch_url", lambda url: html)
    result = extract("https://example.com/post")
    assert result.title == "Web Page" and result.source == "https://example.com/post"
    assert "menu" not in " ".join(b.text for b in result.blocks)
    assert len(result.blocks) == 3


def test_web_download_failure(monkeypatch):
    monkeypatch.setattr("trafilatura.fetch_url", lambda url: None)
    with pytest.raises(ExtractionError, match="download"):
        extract("https://example.com/missing")
