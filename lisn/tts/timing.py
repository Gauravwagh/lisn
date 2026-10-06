"""Helpers that turn engine-specific timing data into per-display-word timings."""

from __future__ import annotations

from lisn.model import Sentence
from lisn.tts.base import WordTiming


def proportional_timings(words: tuple[str, ...], duration: float, offset: float = 0.0) -> tuple[WordTiming, ...]:
    """Fallback when an engine gives no timings: spread duration by word length."""
    if not words or duration <= 0:
        return ()
    weights = [len(w) + 1 for w in words]
    total = float(sum(weights))
    timings: list[WordTiming] = []
    cursor = offset
    for word, weight in zip(words, weights, strict=True):
        length = duration * weight / total
        timings.append(WordTiming(word=word, start=cursor, end=cursor + length))
        cursor += length
    return tuple(timings)


def display_word_timings(
    sentence: Sentence, speech_timings: tuple[WordTiming, ...], duration: float
) -> tuple[WordTiming, ...]:
    """Map speech-word timings back onto the sentence's display words via word_map.

    If the engine's word count does not match the expanded text (engines re-tokenize),
    fall back to a proportional spread so highlighting still advances smoothly.
    """
    words = sentence.words
    expected = len(sentence.speech_text.split())
    if not speech_timings or len(speech_timings) != expected or len(sentence.word_map) != len(words):
        return proportional_timings(words, duration)
    result: list[WordTiming] = []
    previous_end = 0.0
    for word, (start, end) in zip(words, sentence.word_map, strict=True):
        if start >= end:  # display token produced no speech (e.g. a lone "*")
            result.append(WordTiming(word=word, start=previous_end, end=previous_end))
            continue
        span = speech_timings[start:end]
        timing = WordTiming(word=word, start=span[0].start, end=span[-1].end)
        result.append(timing)
        previous_end = timing.end
    return tuple(result)
