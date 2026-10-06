"""Web article extraction with trafilatura: main content only (no nav, ads, comments)."""

from __future__ import annotations

from lisn.errors import ExtractionError
from lisn.extract.base import Block, Extracted, heading
from lisn.extract.html import blocks_from_html, html_title
from lisn.extract.text import blocks_from_markdown


def extract_url(url: str, read_code: bool = False) -> Extracted:
    trafilatura = _trafilatura()
    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        raise ExtractionError(f"Could not download {url} (network error, 404, or blocked).")
    return extract_html_markup(downloaded, url, read_code)


def extract_html_markup(markup: str, source: str, read_code: bool = False) -> Extracted:
    """Main-content extraction; falls back to a plain HTML walk for tiny or unusual pages."""
    trafilatura = _trafilatura()
    url = source if source.startswith("http") else None
    markdown = trafilatura.extract(
        markup,
        url=url,
        output_format="markdown",
        include_comments=False,
        include_tables=True,
        include_links=False,
        include_formatting=True,
    )
    blocks: tuple[Block, ...] = blocks_from_markdown(markdown, read_code) if markdown else ()
    if not blocks:
        blocks = blocks_from_html(markup, read_code)
    if not blocks:
        raise ExtractionError(f"No article text found at {source}.")
    title = _title(trafilatura, markup, url) or html_title(markup)
    if title and blocks[0].text != title:
        blocks = (heading(title), *blocks)
    return Extracted(title=title or source, source=source, blocks=blocks)


def _title(trafilatura, markup: str, url: str | None) -> str:  # type: ignore[no-untyped-def]
    try:
        metadata = trafilatura.extract_metadata(markup, default_url=url)
    except Exception:  # metadata is best-effort only
        return ""
    return " ".join((metadata.title or "").split()) if metadata is not None else ""


def _trafilatura():  # type: ignore[no-untyped-def]
    try:
        import trafilatura
    except ImportError as exc:
        raise ExtractionError("Web support needs 'pip install trafilatura'.") from exc
    return trafilatura
