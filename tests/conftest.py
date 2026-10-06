from __future__ import annotations

import numpy as np
import pytest

from lisn.extract.base import Extracted, heading, paragraph
from lisn.text.pipeline import build_document
from lisn.tts.base import Audio, TTSEngine, Voice, WordTiming


class FakeEngine(TTSEngine):
    """Deterministic engine: 0.05 s per speech word, timings aligned to words."""

    name = "fake"
    default_voice = "fake_voice"
    seconds_per_word = 0.05
    sample_rate = 8000

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, float]] = []

    def supports_word_timings(self) -> bool:
        return True

    def voices(self) -> tuple[Voice, ...]:
        return (Voice(id="fake_voice", engine="fake", language="en"),)

    def synthesize(self, text: str, voice: str, speed: float = 1.0) -> Audio:
        self.calls.append((text, voice, speed))
        words = text.split()
        per_word = self.seconds_per_word / speed
        timings = tuple(WordTiming(word=w, start=i * per_word, end=(i + 1) * per_word) for i, w in enumerate(words))
        total = int(self.sample_rate * per_word * len(words)) or 1
        return Audio(samples=np.zeros(total, dtype=np.float32), sample_rate=self.sample_rate, timings=timings)


@pytest.fixture
def fake_engine() -> FakeEngine:
    return FakeEngine()


@pytest.fixture
def small_document():
    extracted = Extracted(
        title="Doc",
        source="memory",
        blocks=(
            heading("Chapter One"),
            paragraph("First sentence here. Second sentence follows."),
            paragraph("A new paragraph begins."),
            heading("Chapter Two"),
            paragraph("Final words at last."),
        ),
    )
    return build_document(extracted)
