"""Shared HTML -> Blocks conversion used by EPUB and Google Docs (and local HTML files)."""

from __future__ import annotations

from lisn.errors import ExtractionError
from lisn.extract.base import Block, heading, paragraph

SKIP_TAGS = {"script", "style", "nav", "header", "footer", "aside", "noscript", "template", "svg", "button", "form"}
HEADING_TAGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
PARAGRAPH_TAGS = {"p", "li", "blockquote", "pre", "dd", "dt", "figcaption", "td", "th"}
CONTAINER_TAGS = {
    "div",
    "section",
    "article",
    "main",
    "body",
    "ul",
    "ol",
    "table",
    "tr",
    "tbody",
    "thead",
    "dl",
    "html",
}


def blocks_from_html(markup: str, read_code: bool = False) -> tuple[Block, ...]:
    try:
        from bs4 import BeautifulSoup, Tag
    except ImportError as exc:
        raise ExtractionError("HTML support needs 'pip install beautifulsoup4'.") from exc
    soup = BeautifulSoup(markup, "html.parser")
    for tag in soup.find_all(SKIP_TAGS):
        tag.decompose()
    for sup in soup.find_all("sup"):
        sup.decompose()  # footnote markers
    root = soup.body or soup
    blocks: list[Block] = []
    _walk(root, blocks, read_code, Tag)
    return tuple(blocks)


def html_title(markup: str) -> str:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return ""
    soup = BeautifulSoup(markup, "html.parser")
    if soup.title and soup.title.string:
        return " ".join(soup.title.string.split())
    first = soup.find(["h1", "h2"])
    return " ".join(first.get_text().split()) if first else ""


def _walk(node, blocks: list[Block], read_code: bool, tag_type) -> None:  # type: ignore[no-untyped-def]
    for child in node.children:
        if not isinstance(child, tag_type):
            text = _clean(str(child))
            if text and node.name in CONTAINER_TAGS:
                blocks.append(paragraph(text))
            continue
        name = child.name.lower()
        if name in HEADING_TAGS:
            text = _clean(child.get_text(" "))
            if text:
                blocks.append(heading(text, HEADING_TAGS[name]))
        elif name == "pre" and not read_code:
            blocks.append(paragraph("Code block omitted."))
        elif name in PARAGRAPH_TAGS:
            if child.find(["p", "li", "div"]) is not None:
                _walk(child, blocks, read_code, tag_type)
                continue
            text = _clean(child.get_text(" "))
            if text:
                blocks.append(paragraph(text))
        elif name == "br":
            continue
        else:
            _walk(child, blocks, read_code, tag_type)


def _clean(text: str) -> str:
    return " ".join(text.split())
