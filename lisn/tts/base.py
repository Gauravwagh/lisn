"""The engine contract: synthesize(text, voice, speed) -> Audio with word timings."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np

MIN_SPEED = 0.5
MAX_SPEED = 3.0


@dataclass(frozen=True)
class WordTiming:
    """Start/end (seconds) of one spoken word within the Audio samples."""

    word: str
    start: float
    end: float


@dataclass(frozen=True)
class Voice:
    id: str
    engine: str
    language: str  # BCP-47-ish, e.g. "en-US", "hi"
    gender: str = ""  # "female" | "male" | ""
    description: str = ""


@dataclass(frozen=True)
class Audio:
    """Mono float32 samples plus timings for the speech words of the input text."""

    samples: np.ndarray
    sample_rate: int
    timings: tuple[WordTiming, ...] = field(default=())

    @property
    def duration(self) -> float:
        return float(len(self.samples)) / float(self.sample_rate)


class TTSEngine(ABC):
    """Every engine subclasses this. Implementations must be safe to call sequentially
    from a single worker thread; the player never calls synthesize concurrently."""

    name: str = "base"
    default_voice: str = ""

    @abstractmethod
    def synthesize(self, text: str, voice: str, speed: float = 1.0) -> Audio:
        """Return audio for `text`. Raise EngineError on failure."""

    @abstractmethod
    def voices(self) -> tuple[Voice, ...]:
        """List the voices this engine can use."""

    def warm_up(self) -> None:  # noqa: B027 - optional hook, default is a no-op
        """Load models so the first real synthesize call is fast."""

    def supports_word_timings(self) -> bool:
        return False


def clamp_speed(speed: float) -> float:
    if not isinstance(speed, int | float) or speed != speed:  # NaN check
        raise ValueError(f"speed must be a number, got {speed!r}")
    return max(MIN_SPEED, min(MAX_SPEED, float(speed)))
