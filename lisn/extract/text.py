"""Plain text and Markdown extraction.

Markdown syntax is stripped so it is never read aloud: headings become chapter blocks,
list items become paragraphs, fenced code blocks are replaced by "code block omitted"
unless `read_code` is set, and link/image syntax is reduced to its visible text.
"""

from __future__ import annotations

import re
from pathlib import Path

from lisn.errors import ExtractionError
from lisn.extract.base import Block, Extracted, heading, paragraph

CODE_OMITTED = "Code block omitted."
_FENCE_RE = re.compile(r"^(`{3,}|~{3,})")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_SETEXT_RE = re.compile(r"^(={3,}|-{3,})\s*$")
_LIST_RE = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+")
_QUOTE_RE = re.compile(r"^\s*>+\s?")
_HR_RE = re.compile(r"^\s*([-*_]\s*){3,}$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_REF_LINK_RE = re.compile(r"\[([^\]]+)\]\[[^\]]*\]")
_AUTOLINK_RE = re.compile(r"<(https?://[^>]+)>")
_INLINE_CODE_RE = re.compile(r"`([^`]*)`")
_EMPHASIS_RE = re.compile(r"(\*{1,3}|_{1,3})(?=\S)(.+?)(?<=\S)\1")
_STRIKE_RE = re.compile(r"~~(.+?)~~")
_HTML_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")
_FOOTNOTE_RE = re.compile(r"\[\^[^\]]+\]")
_TXT_CHAPTER_RE = re.compile(r"^\s*(chapter|part|section)\s+[\divxlc]+\b.*$", re.IGNORECASE)

TEXT_EXTENSIONS = {".txt", ".text", ".md", ".markdown", ".mdx", ".rst"}


def extract_text_file(path: Path, read_code: bool = False) -> Extracted:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ExtractionError(f"Cannot read {path}: {exc}") from exc
    is_markdown = path.suffix.lower() in {".md", ".markdown", ".mdx"}
    blocks = blocks_from_markdown(raw, read_code) if is_markdown else blocks_from_plain_text(raw)
    title = _leading_heading(blocks) or path.stem
    return Extracted(title=title, source=str(path), blocks=blocks)


def blocks_from_plain_text(raw: str) -> tuple[Block, ...]:
    """Paragraphs separated by blank lines; 'Chapter N' style lines become headings."""
    blocks: list[Block] = []
    for chunk in re.split(r"\n\s*\n", raw):
        lines = [line.strip() for line in chunk.splitlines() if line.strip()]
        if not lines:
            continue
        joined = " ".join(lines)
        if len(lines) == 1 and _looks_like_plain_heading(lines[0]):
            blocks.append(heading(lines[0]))
        else:
            blocks.append(paragraph(joined))
    return tuple(blocks)


def blocks_from_markdown(raw: str, read_code: bool = False) -> tuple[Block, ...]:
    blocks: list[Block] = []
    pending: list[str] = []
    code: list[str] | None = None
    lines = raw.splitlines()

    def flush() -> None:
        nonlocal pending
        if pending:
            blocks.append(paragraph(" ".join(pending)))
            pending = []

    for line in lines:
        if _FENCE_RE.match(line.strip()):
            if code is None:
                flush()
                code = []
            else:
                blocks.append(paragraph(" ".join(code) if read_code else CODE_OMITTED))
                code = None
            continue
        if code is not None:
            code.append(line.strip())
            continue
        stripped = line.strip()
        if not stripped or _HR_RE.match(stripped) or _TABLE_SEP_RE.match(stripped):
            flush()
            continue
        head = _HEADING_RE.match(stripped)
        if head:
            flush()
            blocks.append(heading(strip_inline_markdown(head.group(2)), len(head.group(1))))
            continue
        if _SETEXT_RE.match(stripped) and pending:
            title = pending[-1]
            pending = pending[:-1]
            flush()
            blocks.append(heading(title, 1 if stripped.startswith("=") else 2))
            continue
        if _LIST_RE.match(line) or _is_table_row(stripped):
            flush()
            pending = [strip_inline_markdown(_strip_line_prefix(stripped))]
            flush()
            continue
        pending = pending + [strip_inline_markdown(_strip_line_prefix(stripped))]
    if code is not None:
        blocks.append(paragraph(" ".join(code) if read_code else CODE_OMITTED))
    flush()
    return tuple(blocks)


def strip_inline_markdown(text: str) -> str:
    result = _IMAGE_RE.sub(lambda m: m.group(1), text)
    result = _LINK_RE.sub(lambda m: m.group(1), result)
    result = _REF_LINK_RE.sub(lambda m: m.group(1), result)
    result = _AUTOLINK_RE.sub(lambda m: m.group(1), result)
    result = _INLINE_CODE_RE.sub(lambda m: m.group(1), result)
    result = _STRIKE_RE.sub(lambda m: m.group(1), result)
    for _ in range(3):  # nested emphasis like ***bold italic***
        result = _EMPHASIS_RE.sub(lambda m: m.group(2), result)
    result = _FOOTNOTE_RE.sub("", result)
    result = _HTML_TAG_RE.sub("", result)
    return " ".join(result.split())


def _strip_line_prefix(line: str) -> str:
    without_quote = _QUOTE_RE.sub("", line)
    without_list = _LIST_RE.sub("", without_quote)
    if _is_table_row(without_list):
        cells = [c.strip() for c in without_list.strip().strip("|").split("|")]
        return ", ".join(c for c in cells if c)
    return without_list


def _is_table_row(line: str) -> bool:
    return line.startswith("|") and line.count("|") >= 2


def _looks_like_plain_heading(line: str) -> bool:
    if _TXT_CHAPTER_RE.match(line):
        return True
    words = line.split()
    return 1 <= len(words) <= 8 and line.isupper() and not line.endswith((".", ",", ";"))


def _leading_heading(blocks: tuple[Block, ...]) -> str | None:
    """The document title is the first block only if that block is a heading."""
    if blocks and blocks[0].kind == "heading":
        return blocks[0].text
    return None
