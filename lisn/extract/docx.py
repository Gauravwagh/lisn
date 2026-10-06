"""DOCX extraction with python-docx: headings become chapters, tables are read row by row."""

from __future__ import annotations

import re
from pathlib import Path

from lisn.errors import ExtractionError
from lisn.extract.base import Block, Extracted, heading, paragraph

_HEADING_LEVEL_RE = re.compile(r"heading\s*(\d+)", re.IGNORECASE)


def extract_docx(path: Path) -> Extracted:
    try:
        import docx
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except ImportError as exc:
        raise ExtractionError("DOCX support needs 'pip install python-docx'.") from exc
    try:
        document = docx.Document(str(path))
    except Exception as exc:
        raise ExtractionError(f"Cannot open DOCX {path}: {exc}") from exc

    blocks: list[Block] = []
    for child in document.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            block = _paragraph_block(Paragraph(child, document))
            if block is not None:
                blocks.append(block)
        elif tag == "tbl":
            blocks.extend(_table_blocks(Table(child, document)))
    if not blocks:
        raise ExtractionError(f"No text found in {path}.")
    title = (document.core_properties.title or "").strip()
    if not title and blocks[0].kind == "heading":
        title = blocks[0].text
    return Extracted(title=title or path.stem, source=str(path), blocks=tuple(blocks))


def _paragraph_block(par) -> Block | None:  # type: ignore[no-untyped-def]
    text = " ".join(par.text.split())
    if not text:
        return None
    style = (par.style.name if par.style is not None else "") or ""
    if style.lower() == "title":
        return heading(text, 1)
    match = _HEADING_LEVEL_RE.search(style)
    if match:
        return heading(text, int(match.group(1)))
    return paragraph(text)


def _table_blocks(table) -> list[Block]:  # type: ignore[no-untyped-def]
    blocks: list[Block] = []
    for row in table.rows:
        cells = []
        for cell in row.cells:
            cell_text = " ".join(cell.text.split())
            if cell_text and cell_text not in cells:  # merged cells repeat
                cells.append(cell_text)
        if cells:
            blocks.append(paragraph(", ".join(cells)))
    return blocks
