"""PDF extraction with PyMuPDF.

Skips running headers/footers and page numbers, drops superscript footnote markers,
de-hyphenates words broken across lines, promotes large-font lines to headings and
reads two-column layouts in the right order (left column, then right, band by band).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from lisn.errors import ExtractionError
from lisn.extract.base import Block, Extracted, heading, paragraph

HEADER_ZONE = 0.08  # top fraction of the page where repeated lines are headers
FOOTER_ZONE = 0.92  # bottom fraction where repeated lines are footers
REPEAT_MIN_PAGES = 2
HEADING_SCALE = 1.18  # a line is a heading if its font is this much larger than body text
MAX_HEADING_WORDS = 16
SUPERSCRIPT_FLAG = 1
COLUMN_MAX_WIDTH = 0.62  # a block narrower than this fraction of the page may be a column

_PAGE_NUMBER_RE = re.compile(r"^\s*(page\s+)?\d+(\s*(of|/)\s*\d+)?\s*$", re.IGNORECASE)
_ROMAN_RE = re.compile(r"^\s*[ivxlcdm]+\s*$", re.IGNORECASE)
_DIGITS_RE = re.compile(r"\d+")
_HYPHEN_BREAK_RE = re.compile(r"(\w)-$")


@dataclass(frozen=True)
class _Span:
    text: str
    size: float
    superscript: bool


@dataclass(frozen=True)
class _Line:
    spans: tuple[_Span, ...]
    bbox: tuple[float, float, float, float]

    @property
    def text(self) -> str:
        return "".join(s.text for s in self.spans if not s.superscript).strip()

    @property
    def size(self) -> float:
        sizes = [s.size for s in self.spans if not s.superscript and s.text.strip()]
        return max(sizes) if sizes else 0.0


@dataclass(frozen=True)
class _Block:
    lines: tuple[_Line, ...]
    bbox: tuple[float, float, float, float]
    page: int

    @property
    def text(self) -> str:
        return join_lines([line.text for line in self.lines])


def extract_pdf(path: Path) -> Extracted:
    try:
        import pymupdf
    except ImportError as exc:
        raise ExtractionError("PDF support needs 'pip install pymupdf'.") from exc
    try:
        document = pymupdf.open(str(path))
    except Exception as exc:
        raise ExtractionError(f"Cannot open PDF {path}: {exc}") from exc
    with document:
        if document.needs_pass:
            raise ExtractionError(f"{path} is password protected.")
        pages = [_read_page(page, number) for number, page in enumerate(document)]
        title = (document.metadata or {}).get("title") or ""
    blocks = tuple(_blocks_from_pages(pages))
    if not blocks:
        raise ExtractionError(f"No text layer found in {path} (scanned PDFs need OCR first).")
    return Extracted(title=title.strip() or path.stem, source=str(path), blocks=blocks)


# ---- page reading --------------------------------------------------------------------


@dataclass(frozen=True)
class _Page:
    blocks: tuple[_Block, ...]
    width: float
    height: float


def _read_page(page, number: int) -> _Page:  # type: ignore[no-untyped-def]
    raw = page.get_text("dict")
    blocks: list[_Block] = []
    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue
        lines = tuple(
            _Line(
                spans=tuple(
                    _Span(
                        text=span.get("text", ""),
                        size=float(span.get("size", 0.0)),
                        superscript=bool(span.get("flags", 0) & SUPERSCRIPT_FLAG),
                    )
                    for span in line.get("spans", [])
                ),
                bbox=tuple(line.get("bbox", block["bbox"])),
            )
            for line in block.get("lines", [])
        )
        if any(line.text for line in lines):
            blocks.append(_Block(lines=lines, bbox=tuple(block["bbox"]), page=number))
    return _Page(blocks=tuple(blocks), width=float(page.rect.width), height=float(page.rect.height))


# ---- filtering -----------------------------------------------------------------------


def _blocks_from_pages(pages: list[_Page]) -> list[Block]:
    repeated = _repeated_edge_lines(pages)
    body_size = _body_font_size(pages)
    result: list[Block] = []
    pending: list[str] = []

    def flush() -> None:
        nonlocal pending
        if pending:
            result.append(paragraph(" ".join(pending)))
            pending = []

    for page in pages:
        for block in _reading_order(page):
            if _is_noise(block, page, repeated):
                continue
            text = block.text
            if not text or sum(ch.isalpha() for ch in text) < 2:
                continue
            if _is_heading(block, body_size):
                flush()
                result.append(heading(text))
                continue
            if pending and _continues(pending[-1], text):
                pending = [*pending[:-1], join_lines([pending[-1], text])]
            else:
                flush()
                pending = [text]
    flush()
    return result


def _repeated_edge_lines(pages: list[_Page]) -> set[str]:
    """Lines that appear near the top or bottom of several pages (digits ignored)."""
    seen: Counter[str] = Counter()
    for page in pages:
        page_keys: set[str] = set()
        for block in page.blocks:
            if _in_edge_zone(block, page):
                page_keys.add(_edge_key(block.text))
        seen.update(page_keys)
    threshold = min(REPEAT_MIN_PAGES, max(1, len(pages)))
    return {key for key, count in seen.items() if count >= threshold and key}


def _in_edge_zone(block: _Block, page: _Page) -> bool:
    _x0, y0, _x1, y1 = block.bbox
    return y1 <= page.height * HEADER_ZONE or y0 >= page.height * FOOTER_ZONE


def _edge_key(text: str) -> str:
    return _DIGITS_RE.sub("#", " ".join(text.lower().split()))


def _is_noise(block: _Block, page: _Page, repeated: set[str]) -> bool:
    text = block.text
    if _PAGE_NUMBER_RE.match(text) or _ROMAN_RE.match(text):
        return True
    if _in_edge_zone(block, page):
        if _edge_key(text) in repeated:
            return True
        if len(text.split()) <= 6 and len(page.blocks) > 1:
            return True  # short lone line at the page edge: a running head or folio
    return False


def _body_font_size(pages: list[_Page]) -> float:
    counter: Counter[float] = Counter()
    for page in pages:
        for block in page.blocks:
            for line in block.lines:
                if line.size:
                    counter[round(line.size, 1)] += len(line.text)
    return counter.most_common(1)[0][0] if counter else 0.0


def _is_heading(block: _Block, body_size: float) -> bool:
    if body_size <= 0 or len(block.lines) > 3:
        return False
    text = block.text
    if len(text.split()) > MAX_HEADING_WORDS or text.endswith((".", ",", ";", ":")):
        return False
    return block.lines[0].size >= body_size * HEADING_SCALE


def _continues(previous: str, current: str) -> bool:
    """Does `current` continue a paragraph that ran across a column or page break?"""
    if not previous or not current:
        return False
    if previous.endswith("-"):
        return True
    unterminated = previous[-1] not in ".!?:\"')]”’"
    return unterminated and current[0].islower()


# ---- layout ---------------------------------------------------------------------------


def _reading_order(page: _Page) -> list[_Block]:
    """Order blocks top-to-bottom, reading two columns left then right within each band."""
    ordered: list[_Block] = []
    for band in _bands(page):
        narrow = [b for b in band if (b.bbox[2] - b.bbox[0]) <= page.width * COLUMN_MAX_WIDTH]
        if len(narrow) == len(band) and _is_two_column(band, page):
            left = sorted((b for b in band if _center_x(b) < page.width / 2), key=lambda b: b.bbox[1])
            right = sorted((b for b in band if _center_x(b) >= page.width / 2), key=lambda b: b.bbox[1])
            ordered.extend(left + right)
        else:
            ordered.extend(sorted(band, key=lambda b: (round(b.bbox[1]), b.bbox[0])))
    return ordered


def _bands(page: _Page) -> list[list[_Block]]:
    """Split the page at full-width blocks (titles, spanning paragraphs)."""
    bands: list[list[_Block]] = []
    current: list[_Block] = []
    for block in sorted(page.blocks, key=lambda b: (b.bbox[1], b.bbox[0])):
        wide = (block.bbox[2] - block.bbox[0]) > page.width * COLUMN_MAX_WIDTH
        if wide:
            if current:
                bands.append(current)
            bands.append([block])
            current = []
        else:
            current = [*current, block]
    if current:
        bands.append(current)
    return bands


def _is_two_column(blocks: list[_Block], page: _Page) -> bool:
    left = [b for b in blocks if _center_x(b) < page.width / 2]
    right = [b for b in blocks if _center_x(b) >= page.width / 2]
    if not left or not right:
        return False
    left_max = max(b.bbox[2] for b in left)
    right_min = min(b.bbox[0] for b in right)
    return right_min >= left_max - 2  # columns do not overlap horizontally


def _center_x(block: _Block) -> float:
    return (block.bbox[0] + block.bbox[2]) / 2


# ---- text joining ---------------------------------------------------------------------


def join_lines(lines: list[str]) -> str:
    """Join wrapped lines, removing hyphenation at line ends (but keeping real hyphens)."""
    result = ""
    for line in lines:
        piece = " ".join(line.split())
        if not piece:
            continue
        if not result:
            result = piece
        elif _HYPHEN_BREAK_RE.search(result) and piece[:1].islower():
            result = result[:-1] + piece
        else:
            result = f"{result} {piece}"
    return result
