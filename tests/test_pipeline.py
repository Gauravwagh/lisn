from lisn.extract.base import Extracted, heading, paragraph
from lisn.model import sentence_id
from lisn.text.pipeline import build_document, document_from_text


def test_build_document_structure(small_document):
    doc = small_document
    assert [s.text for s in doc.sentences] == [
        "Chapter One",
        "First sentence here.",
        "Second sentence follows.",
        "A new paragraph begins.",
        "Chapter Two",
        "Final words at last.",
    ]
    assert [c.title for c in doc.chapters] == ["Chapter One", "Chapter Two"]
    assert doc.chapters[1].start_sentence == 4
    assert doc.chapter_of(2).title == "Chapter One"
    assert doc.chapter_of(5).title == "Chapter Two"
    assert doc.sentences[1].paragraph == doc.sentences[2].paragraph
    assert doc.sentences[3].paragraph != doc.sentences[2].paragraph


def test_ids_are_stable_and_unique_for_repeats():
    doc = build_document(Extracted("t", "s", (paragraph("Same. Same. Different."),)))
    ids = [s.id for s in doc.sentences]
    assert len(set(ids)) == 3
    assert ids[0] == sentence_id("Same.", 0)
    assert ids[1] == sentence_id("Same.", 1)
    assert doc.index_of_id(ids[2]) == 2


def test_expansion_is_applied():
    doc = document_from_text("Pay $5 e.g. now.")
    sentence = doc.sentences[0]
    assert sentence.text == "Pay $5 e.g. now."
    assert sentence.speech_text == "Pay five dollars for example now."
    assert sentence.word_map == ((0, 1), (1, 3), (3, 5), (5, 6))


def test_empty_document_raises():
    import pytest

    with pytest.raises(ValueError):
        build_document(Extracted("t", "s", (paragraph("   "), heading(""))))
