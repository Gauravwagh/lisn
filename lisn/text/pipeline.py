"""Turn extracted Blocks into an immutable Document ready for playback."""

from __future__ import annotations

from lisn.extract.base import Block, Extracted
from lisn.model import Chapter, Document, Sentence, sentence_id
from lisn.text.expand import expand_text
from lisn.text.normalize import collapse_whitespace, normalize
from lisn.text.segment import split_sentences


def build_document(extracted: Extracted, language: str = "en") -> Document:
    """Normalize, segment and expand every block; headings become chapters."""
    sentences: list[Sentence] = []
    chapters: list[Chapter] = []
    occurrences: dict[str, int] = {}
    paragraph_index = 0

    for block in extracted.blocks:
        text = normalize(block.text)
        if not text:
            continue
        if block.kind == "heading":
            title = collapse_whitespace(text)
            chapters.append(Chapter(index=len(chapters), title=title, start_sentence=len(sentences)))
            pieces: tuple[str, ...] = (title,)
        else:
            pieces = split_sentences(text, language)
        if not pieces:
            continue
        paragraph_index += 1
        for piece in pieces:
            sentences.append(
                _make_sentence(piece, len(sentences), max(len(chapters) - 1, 0), paragraph_index, occurrences)
            )
            occurrences = {**occurrences, piece: occurrences.get(piece, 0) + 1}

    if not sentences:
        raise ValueError(f"No readable text found in {extracted.source}")
    return Document(
        title=extracted.title,
        source=extracted.source,
        sentences=tuple(sentences),
        chapters=tuple(chapters),
    )


def _make_sentence(text: str, index: int, chapter: int, paragraph: int, occurrences: dict[str, int]) -> Sentence:
    expansion = expand_text(text)
    return Sentence(
        id=sentence_id(text, occurrences.get(text, 0)),
        index=index,
        chapter=chapter,
        paragraph=paragraph,
        text=text,
        speech_text=expansion.speech_text,
        word_map=expansion.word_map,
    )


def document_from_text(text: str, title: str = "Text", source: str = "text") -> Document:
    """Convenience for callers that already have plain text (sample, stdin, MCP)."""
    from lisn.extract.text import blocks_from_markdown

    return build_document(Extracted(title=title, source=source, blocks=blocks_from_markdown(text)))


__all__ = ["Block", "build_document", "document_from_text"]
