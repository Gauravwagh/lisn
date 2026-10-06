"""Synthesize every sentence of a Document into one continuous audio array plus chapter times."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from lisn.model import Document
from lisn.tts.base import Audio, TTSEngine
from lisn.tts.cache import AudioCache

SENTENCE_GAP = 0.25  # seconds of silence between sentences
PARAGRAPH_GAP = 0.6
HEADING_GAP = 1.0


@dataclass(frozen=True)
class ChapterMark:
    title: str
    start: float  # seconds
    end: float


@dataclass(frozen=True)
class RenderedDocument:
    samples: np.ndarray
    sample_rate: int
    chapters: tuple[ChapterMark, ...]

    @property
    def duration(self) -> float:
        return len(self.samples) / float(self.sample_rate)


ProgressFn = Callable[[int, int], None]


def render_document(
    document: Document,
    engine: TTSEngine,
    voice: str,
    speed: float,
    cache: AudioCache | None = None,
    progress: ProgressFn | None = None,
) -> RenderedDocument:
    """Synthesize all sentences in order. Chapter boundaries become ChapterMarks."""
    chunks: list[np.ndarray] = []
    sample_rate = 0
    cursor = 0.0
    starts: dict[int, float] = {}
    heading_starts = {c.start_sentence: c for c in document.chapters}
    previous_paragraph: int | None = None

    for position, sentence in enumerate(document.sentences):
        audio = _synthesize(engine, cache, sentence.speech_text, voice, speed)
        sample_rate = sample_rate or audio.sample_rate
        gap = _gap_before(sentence.index in heading_starts, previous_paragraph, sentence.paragraph)
        if gap and chunks:
            chunks.append(np.zeros(int(sample_rate * gap), dtype=np.float32))
            cursor += gap
        if sentence.index in heading_starts:
            starts[sentence.index] = cursor
        chunks.append(audio.samples.astype(np.float32))
        cursor += audio.duration
        previous_paragraph = sentence.paragraph
        if progress is not None:
            progress(position + 1, len(document.sentences))

    if not chunks:
        raise ValueError("Nothing to export: the document has no sentences.")
    chunks.append(np.zeros(int(sample_rate * SENTENCE_GAP), dtype=np.float32))
    cursor += SENTENCE_GAP
    samples = np.concatenate(chunks)
    return RenderedDocument(samples=samples, sample_rate=sample_rate, chapters=_marks(document, starts, cursor))


def _synthesize(engine: TTSEngine, cache: AudioCache | None, text: str, voice: str, speed: float) -> Audio:
    key = AudioCache.key(engine.name, voice, speed, text)
    cached = cache.get(key) if cache else None
    if cached is not None:
        return cached
    audio = engine.synthesize(text, voice, speed)
    if cache:
        cache.put(key, audio)
    return audio


def _gap_before(is_heading: bool, previous_paragraph: int | None, paragraph: int) -> float:
    if previous_paragraph is None:
        return 0.0
    if is_heading:
        return HEADING_GAP
    if paragraph != previous_paragraph:
        return PARAGRAPH_GAP
    return SENTENCE_GAP


def _marks(document: Document, starts: dict[int, float], total: float) -> tuple[ChapterMark, ...]:
    ordered = [(starts[c.start_sentence], c.title) for c in document.chapters if c.start_sentence in starts]
    if not ordered or ordered[0][0] > 0.0:
        ordered = [(0.0, document.title), *ordered]
    marks: list[ChapterMark] = []
    for position, (start, title) in enumerate(ordered):
        end = ordered[position + 1][0] if position + 1 < len(ordered) else total
        if end > start:
            marks.append(ChapterMark(title=title, start=start, end=end))
    return tuple(marks)
