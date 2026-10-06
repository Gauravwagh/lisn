"""Source dispatch: turn a path, URL, clipboard or stdin into Extracted blocks."""

from __future__ import annotations

import sys
from pathlib import Path

from lisn.errors import ExtractionError, UnsupportedSourceError
from lisn.extract.base import Block, Extracted, heading, paragraph
from lisn.extract.text import TEXT_EXTENSIONS, blocks_from_markdown, extract_text_file

__all__ = ["Block", "Extracted", "extract", "extract_clipboard", "extract_stdin", "heading", "paragraph"]

HTML_EXTENSIONS = {".html", ".htm", ".xhtml"}


def extract(source: str, read_code: bool = False) -> Extracted:
    """Dispatch on the source: '-' (stdin), URL (Google Doc or web page), or a file by extension."""
    if source == "-":
        return extract_stdin(read_code)
    if source.startswith(("http://", "https://")):
        return _extract_url(source, read_code)
    path = Path(source).expanduser()
    if not path.exists():
        raise ExtractionError(f"No such file: {source}")
    if path.is_dir():
        raise ExtractionError(f"{source} is a directory, not a document.")
    return _extract_file(path, read_code)


def _extract_url(url: str, read_code: bool) -> Extracted:
    from lisn.extract.gdoc import extract_gdoc, is_gdoc_url
    from lisn.extract.web import extract_url

    if is_gdoc_url(url):
        return extract_gdoc(url, read_code)
    return extract_url(url, read_code)


def _extract_file(path: Path, read_code: bool) -> Extracted:
    suffix = path.suffix.lower()
    if suffix in TEXT_EXTENSIONS or suffix == "":
        return extract_text_file(path, read_code)
    if suffix == ".pdf":
        from lisn.extract.pdf import extract_pdf

        return extract_pdf(path)
    if suffix == ".docx":
        from lisn.extract.docx import extract_docx

        return extract_docx(path)
    if suffix == ".epub":
        from lisn.extract.epub import extract_epub

        return extract_epub(path, read_code)
    if suffix in HTML_EXTENSIONS:
        from lisn.extract.web import extract_html_markup

        return extract_html_markup(path.read_text(encoding="utf-8", errors="replace"), str(path), read_code)
    raise UnsupportedSourceError(f"Unsupported file type '{suffix}'. Supported: txt, md, pdf, docx, epub, html.")


def extract_stdin(read_code: bool = False) -> Extracted:
    raw = sys.stdin.read()
    if not raw.strip():
        raise ExtractionError("Nothing was received on stdin.")
    return Extracted(title="stdin", source="stdin", blocks=blocks_from_markdown(raw, read_code))


def extract_clipboard(read_code: bool = False) -> Extracted:
    try:
        import pyperclip
    except ImportError as exc:
        raise ExtractionError("Clipboard support needs 'pip install pyperclip'.") from exc
    try:
        raw = pyperclip.paste()
    except pyperclip.PyperclipException as exc:
        raise ExtractionError(f"Could not read the clipboard: {exc}") from exc
    if not raw or not raw.strip():
        raise ExtractionError("The clipboard is empty.")
    return Extracted(title="clipboard", source="clipboard", blocks=blocks_from_markdown(raw, read_code))
