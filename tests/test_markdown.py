from pathlib import Path

from lisn.extract import extract
from lisn.extract.text import CODE_OMITTED, blocks_from_markdown, blocks_from_plain_text, strip_inline_markdown


def test_headings_lists_and_code():
    md = """# Title

Intro paragraph with **bold** and `code` and a [link](http://x.y).

## Section

- item one
- item two

```python
print("hi")
```

> quoted text
"""
    blocks = blocks_from_markdown(md)
    kinds = [(b.kind, b.text) for b in blocks]
    assert kinds == [
        ("heading", "Title"),
        ("paragraph", "Intro paragraph with bold and code and a link."),
        ("heading", "Section"),
        ("paragraph", "item one"),
        ("paragraph", "item two"),
        ("paragraph", CODE_OMITTED),
        ("paragraph", "quoted text"),
    ]
    assert blocks[0].level == 1 and blocks[2].level == 2


def test_read_code_keeps_code():
    blocks = blocks_from_markdown("```\nx = 1\n```", read_code=True)
    assert blocks[0].text == "x = 1"


def test_tables_and_hr_and_setext():
    md = "Big Title\n=========\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n---\n\nAfter."
    blocks = blocks_from_markdown(md)
    assert [(b.kind, b.text) for b in blocks] == [
        ("heading", "Big Title"),
        ("paragraph", "a, b"),
        ("paragraph", "1, 2"),
        ("paragraph", "After."),
    ]


def test_strip_inline_markdown():
    assert strip_inline_markdown("***x*** ~~y~~ ![alt](i.png) <b>z</b>[^1]") == "x y alt z"


def test_plain_text_paragraphs_and_chapters():
    blocks = blocks_from_plain_text("CHAPTER 1\n\nSome wrapped\ntext here.\n\nSecond para.")
    assert [(b.kind, b.text) for b in blocks] == [
        ("heading", "CHAPTER 1"),
        ("paragraph", "Some wrapped text here."),
        ("paragraph", "Second para."),
    ]


def test_extract_fixture_files():
    fixtures = Path(__file__).parent / "fixtures"
    md = extract(str(fixtures / "sample.md"))
    assert md.title == "The Little Reader"
    assert any(b.kind == "heading" for b in md.blocks)
    txt = extract(str(fixtures / "sample.txt"))
    assert txt.title == "sample"
    assert txt.blocks[0].text.startswith("This is a plain")


def test_extract_errors():
    import pytest

    from lisn.errors import ExtractionError, UnsupportedSourceError

    with pytest.raises(ExtractionError):
        extract("does-not-exist.txt")
    with pytest.raises(UnsupportedSourceError):
        extract("tests/fixtures/sample.unknownext")
