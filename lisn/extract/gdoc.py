"""Google Docs: public / 'anyone with the link' documents via the HTML export endpoint.

Private documents need OAuth (phase 7). When the export redirects to a sign-in page we
raise a clear ExtractionError explaining that.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request

from lisn.errors import ExtractionError
from lisn.extract.base import Extracted
from lisn.extract.html import blocks_from_html, html_title

GDOC_ID_RE = re.compile(r"docs\.google\.com/document/(?:u/\d+/)?d/([a-zA-Z0-9_-]+)")
EXPORT_URL = "https://docs.google.com/document/d/{doc_id}/export?format=html"
FETCH_TIMEOUT = 30
USER_AGENT = "lisn/0.1 (+https://github.com/lisn)"
PRIVATE_HINT = (
    "This Google Doc is private. Share it as 'Anyone with the link', or sign in once with "
    "`lisn gdoc login <client_secret.json>` to read your own private docs."
)


def is_gdoc_url(url: str) -> bool:
    return GDOC_ID_RE.search(url) is not None


def gdoc_id(url: str) -> str:
    match = GDOC_ID_RE.search(url)
    if not match:
        raise ExtractionError(f"Not a Google Docs URL: {url}")
    return match.group(1)


def extract_gdoc(url: str, read_code: bool = False, fetch=None, private_fetch=None) -> Extracted:  # type: ignore[no-untyped-def]
    """Public export first; if the doc is private and the user is signed in, use the Drive API."""
    doc_id = gdoc_id(url)
    try:
        markup = (fetch or _fetch)(EXPORT_URL.format(doc_id=doc_id))
        if _looks_like_login(markup):
            raise ExtractionError(PRIVATE_HINT)
    except ExtractionError as public_error:
        if "private" not in str(public_error).lower():
            raise
        markup = _private_export(doc_id, private_fetch, public_error)
    blocks = blocks_from_html(markup, read_code)
    if not blocks:
        raise ExtractionError("The Google Doc appears to be empty.")
    title = html_title(markup) or f"Google Doc {doc_id}"
    return Extracted(title=title, source=url, blocks=blocks)


def _fetch(export_url: str) -> str:
    request = urllib.request.Request(export_url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT) as response:  # noqa: S310 - fixed https host
            final_url = response.geturl()
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403, 404):
            raise ExtractionError(PRIVATE_HINT) from exc
        raise ExtractionError(f"Google Docs export failed with HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ExtractionError(f"Could not reach Google Docs: {exc}") from exc
    if "accounts.google.com" in final_url:
        raise ExtractionError(PRIVATE_HINT)
    return body


def _private_export(doc_id: str, private_fetch, public_error: ExtractionError) -> str:  # type: ignore[no-untyped-def]
    from lisn.extract.gdoc_oauth import export_private_doc, is_logged_in

    if private_fetch is not None:
        return private_fetch(doc_id)
    if not is_logged_in():
        raise public_error
    return export_private_doc(doc_id)


def _looks_like_login(markup: str) -> bool:
    head = markup[:4000].lower()
    return "accounts.google.com" in head and "signin" in head
