"""Immutable document model shared by extraction, synthesis, playback and the TUI.

A Document is a flat tuple of Sentences plus a tuple of Chapters that index into it.
Every Sentence carries a stable id so playback position can be saved and resumed even
if the surrounding text changes slightly.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Sentence:
    """One spoken unit. `text` is what is displayed; `speech_text` is what is synthesized."""

    id: str
    index: int
    chapter: int
    paragraph: int
    text: str
    speech_text: str
    # word_map[i] = (start, end) span of speech-word indices covering display word i
    word_map: tuple[tuple[int, int], ...] = field(default=())

    @property
    def words(self) -> tuple[str, ...]:
        return tuple(self.text.split())


@dataclass(frozen=True)
class Chapter:
    index: int
    title: str
    start_sentence: int  # index into Document.sentences


@dataclass(frozen=True)
class Document:
    title: str
    source: str  # path, URL, "clipboard", or "stdin"
    sentences: tuple[Sentence, ...]
    chapters: tuple[Chapter, ...]

    def __len__(self) -> int:
        return len(self.sentences)

    @property
    def total_chars(self) -> int:
        return sum(len(s.text) for s in self.sentences)

    def chapter_of(self, sentence_index: int) -> Chapter | None:
        if not self.chapters:
            return None
        current = self.chapters[0]
        for chapter in self.chapters:
            if chapter.start_sentence <= sentence_index:
                current = chapter
            else:
                break
        return current

    def search(self, query: str, start_after: int = -1) -> int | None:
        """Index of the next sentence containing `query` (case-insensitive), wrapping around."""
        needle = query.strip().lower()
        if not needle:
            return None
        count = len(self.sentences)
        for offset in range(1, count + 1):
            index = (start_after + offset) % count
            if needle in self.sentences[index].text.lower():
                return index
        return None

    def index_of_id(self, sentence_id: str) -> int | None:
        for sentence in self.sentences:
            if sentence.id == sentence_id:
                return sentence.index
        return None


def sentence_id(text: str, occurrence: int) -> str:
    """Stable id: hash of the sentence text plus how many times it appeared before.

    Hashing the text (not the position) keeps ids stable when text elsewhere in the
    document is edited; the occurrence counter disambiguates repeated sentences.
    """
    digest = hashlib.sha1(f"{occurrence}\x1f{text}".encode()).hexdigest()
    return digest[:12]
