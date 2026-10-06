from pathlib import Path

import pytest

from lisn.errors import ExtractionError
from lisn.extract import extract
from lisn.extract.pdf import join_lines

FIXTURES = Path(__file__).parent / "fixtures"


def kinds(extracted):
    return [(b.kind, b.text) for b in extracted.blocks]


def test_pdf_skips_headers_footers_and_reads_columns():
    result = extract(str(FIXTURES / "sample.pdf"))
    assert result.title == "Fixture Report"
    texts = [b.text for b in result.blocks]
    assert "Running Header Of The Report" not in " ".join(texts)
    assert not any(t.strip().isdigit() for t in texts), "page numbers must be dropped"
    assert result.blocks[0] == ("heading", "Big Title") or kinds(result)[0] == ("heading", "Big Title")
    assert texts[1].startswith("The first column starts here with a sentence that is hyphenated")
    assert texts[2].startswith("The right column comes second")
    assert "Footnote marker" in texts and "Footnote marker 1" not in texts


def test_pdf_join_lines_dehyphenates():
    assert join_lines(["a sen-", "tence here", "self-", "Aware"]) == "a sentence here self- Aware"


def test_docx_headings_lists_tables():
    result = extract(str(FIXTURES / "sample.docx"))
    assert result.title == "Fixture Document"
    assert kinds(result) == [
        ("heading", "Fixture Document"),
        ("paragraph", "An opening paragraph with two sentences. Here is the second one."),
        ("heading", "Chapter One"),
        ("paragraph", "Chapter one body text."),
        ("paragraph", "First bullet"),
        ("paragraph", "Second bullet"),
        ("paragraph", "Name, Value"),
        ("paragraph", "Alpha, 1"),
        ("heading", "Chapter Two"),
        ("paragraph", "Chapter two body text."),
    ]
    assert result.blocks[0].level == 1 and result.blocks[2].level == 1


def test_epub_chapters_in_order_without_footnote_markers():
    result = extract(str(FIXTURES / "sample.epub"))
    assert result.title == "Fixture Book"
    assert kinds(result) == [
        ("heading", "Chapter One"),
        ("paragraph", "The first chapter has a sentence. And another one."),
        ("paragraph", "Footnote here."),
        ("heading", "Chapter Two"),
        ("paragraph", "The second chapter is brief."),
        ("paragraph", "Footnote here."),
    ]


def test_html_main_content_only():
    result = extract(str(FIXTURES / "sample.html"))
    assert result.title == "Fixture Article"
    joined = " ".join(b.text for b in result.blocks)
    assert "Home" not in joined and "advertising" not in joined and "Copyright" not in joined
    assert ("heading", "A Section") in kinds(result)
    assert ("paragraph", "First item in a list") in kinds(result)


def test_unreadable_pdf(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf")
    with pytest.raises(ExtractionError):
        extract(str(bad))


def test_unreadable_docx(tmp_path):
    bad = tmp_path / "bad.docx"
    bad.write_bytes(b"nope")
    with pytest.raises(ExtractionError):
        extract(str(bad))


def test_unreadable_epub(tmp_path):
    bad = tmp_path / "bad.epub"
    bad.write_bytes(b"nope")
    with pytest.raises(ExtractionError):
        extract(str(bad))
