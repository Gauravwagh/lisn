"""Split normalized text into sentences with a proper sentence boundary detector.

pysbd handles abbreviations ("Dr.", "e.g."), decimals, ellipses and quotes far better
than splitting on periods. Very long sentences are further split at clause boundaries
so that synthesis latency stays low and no sentence exceeds the engine's input limit.
"""

from __future__ import annotations

import re
from functools import lru_cache

import pysbd

MAX_SENTENCE_CHARS = 280
_CLAUSE_BREAK_RE = re.compile(r"(?<=[,;:])\s+|(?<=\s[-—])\s+|\s+(?=[-—]\s)")


@lru_cache(maxsize=4)
def _segmenter(language: str) -> pysbd.Segmenter:
    return pysbd.Segmenter(language=language, clean=False)


def split_sentences(text: str, language: str = "en") -> tuple[str, ...]:
    """Return the sentences of a single paragraph, each stripped and non-empty."""
    if not isinstance(text, str):
        raise TypeError(f"split_sentences expects str, got {type(text).__name__}")
    flat = " ".join(text.split())
    if not flat:
        return ()
    try:
        raw = _segmenter(language).segment(flat)
    except ValueError:
        raw = _segmenter("en").segment(flat)
    sentences = [s.strip() for s in raw if s and s.strip()]
    return tuple(piece for sentence in sentences for piece in split_long(sentence))


def split_long(sentence: str, max_chars: int = MAX_SENTENCE_CHARS) -> tuple[str, ...]:
    """Split an over-long sentence at the clause boundary nearest its middle, recursively."""
    if len(sentence) <= max_chars:
        return (sentence,)
    candidates = [m.start() for m in _CLAUSE_BREAK_RE.finditer(sentence)]
    middle = len(sentence) // 2
    usable = [c for c in candidates if 20 <= c <= len(sentence) - 20]
    if not usable:
        return _split_at_words(sentence, max_chars)
    cut = min(usable, key=lambda c: abs(c - middle))
    left, right = sentence[:cut].strip(), sentence[cut:].strip()
    return split_long(left, max_chars) + split_long(right, max_chars)


def _split_at_words(sentence: str, max_chars: int) -> tuple[str, ...]:
    words = sentence.split()
    chunks: list[str] = []
    current: list[str] = []
    for word in words:
        if current and len(" ".join(current + [word])) > max_chars:
            chunks.append(" ".join(current))
            current = []
        current = current + [word]
    if current:
        chunks.append(" ".join(current))
    return tuple(chunks)
