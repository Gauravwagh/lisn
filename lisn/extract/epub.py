"""EPUB extraction with ebooklib + BeautifulSoup, preserving chapters in spine order."""

from __future__ import annotations

import warnings
from pathlib import Path

from lisn.errors import ExtractionError
from lisn.extract.base import Block, Extracted, heading
from lisn.extract.html import blocks_from_html


def extract_epub(path: Path, read_code: bool = False) -> Extracted:
    try:
        import ebooklib
        from ebooklib import epub
    except ImportError as exc:
        raise ExtractionError("EPUB support needs 'pip install ebooklib beautifulsoup4'.") from exc
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            book = epub.read_epub(str(path), options={"ignore_ncx": True})
    except Exception as exc:
        raise ExtractionError(f"Cannot open EPUB {path}: {exc}") from exc

    toc_titles = _toc_titles(book)
    blocks: list[Block] = []
    for item_id, _linear in book.spine:
        item = book.get_item_with_id(item_id)
        if item is None or item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        chapter_blocks = list(blocks_from_html(item.get_content().decode("utf-8", errors="replace"), read_code))
        if not chapter_blocks:
            continue
        toc_title = toc_titles.get(item.get_name().split("#")[0])
        if toc_title and (chapter_blocks[0].kind != "heading"):
            chapter_blocks = [heading(toc_title), *chapter_blocks]
        blocks.extend(chapter_blocks)
    if not blocks:
        raise ExtractionError(f"No readable chapters found in {path}.")
    titles = book.get_metadata("DC", "title")
    title = titles[0][0] if titles else path.stem
    return Extracted(title=title, source=str(path), blocks=tuple(blocks))


def _toc_titles(book) -> dict[str, str]:  # type: ignore[no-untyped-def]
    titles: dict[str, str] = {}

    def visit(entries) -> None:  # type: ignore[no-untyped-def]
        for entry in entries:
            if isinstance(entry, tuple | list):
                visit(entry)
            elif hasattr(entry, "href") and hasattr(entry, "title"):
                titles.setdefault(entry.href.split("#")[0], entry.title)

    visit(book.toc)
    return titles
