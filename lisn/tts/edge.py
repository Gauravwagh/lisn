"""edge-tts engine: Microsoft Edge's free online neural voices. Off by default (needs network).

Word timings come from the service's WordBoundary events.
"""

from __future__ import annotations

import io
import re
import threading
from typing import Any

import numpy as np

from lisn.errors import EngineError, EngineUnavailableError
from lisn.tts.base import Audio, TTSEngine, Voice, WordTiming, clamp_speed

TICKS_PER_SECOND = 10_000_000  # WordBoundary offsets are in 100 ns units
_PUNCT_RE = re.compile(r"[^\w']+", re.UNICODE)

# Shown when the voice list cannot be fetched; any valid ShortName works.
FALLBACK_VOICES: tuple[tuple[str, str, str], ...] = (
    ("en-US-AriaNeural", "en-US", "female"),
    ("en-US-GuyNeural", "en-US", "male"),
    ("en-US-JennyNeural", "en-US", "female"),
    ("en-GB-SoniaNeural", "en-GB", "female"),
    ("en-GB-RyanNeural", "en-GB", "male"),
    ("en-IN-NeerjaNeural", "en-IN", "female"),
    ("en-IN-PrabhatNeural", "en-IN", "male"),
    ("hi-IN-SwaraNeural", "hi-IN", "female"),
    ("hi-IN-MadhurNeural", "hi-IN", "male"),
)


class EdgeEngine(TTSEngine):
    name = "edge"
    default_voice = "en-US-AriaNeural"

    def __init__(self) -> None:
        self._voices: tuple[Voice, ...] | None = None
        self._lock = threading.Lock()

    def supports_word_timings(self) -> bool:
        return True

    def voices(self) -> tuple[Voice, ...]:
        if self._voices is not None:
            return self._voices
        edge_tts = _import_edge()
        try:
            import asyncio

            raw = asyncio.run(edge_tts.list_voices())
            found = tuple(
                Voice(
                    id=v["ShortName"],
                    engine=self.name,
                    language=v["Locale"],
                    gender=v["Gender"].lower(),
                    description=v.get("FriendlyName", ""),
                )
                for v in raw
            )
        except Exception:  # offline: show a useful subset
            found = tuple(Voice(id=i, engine=self.name, language=lang, gender=g) for i, lang, g in FALLBACK_VOICES)
        self._voices = found
        return found

    def synthesize(self, text: str, voice: str, speed: float = 1.0) -> Audio:
        if not text or not text.strip():
            raise EngineError("Cannot synthesize empty text.")
        if not voice or "-" not in voice:
            raise EngineError(f"'{voice}' is not an edge-tts voice (e.g. en-US-AriaNeural).")
        edge_tts = _import_edge()
        rate = f"{int(round((clamp_speed(speed) - 1.0) * 100)):+d}%"
        audio_bytes = bytearray()
        boundaries: list[tuple[str, float, float]] = []
        try:
            with self._lock:
                communicate = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
                for chunk in communicate.stream_sync():
                    if chunk["type"] == "audio":
                        audio_bytes.extend(chunk.get("data", b""))
                    elif chunk["type"] == "WordBoundary":
                        start = float(chunk["offset"]) / TICKS_PER_SECOND
                        boundaries.append(
                            (str(chunk["text"]), start, start + float(chunk["duration"]) / TICKS_PER_SECOND)
                        )
        except Exception as exc:
            raise EngineError(f"edge-tts failed (is the network up?): {exc}") from exc
        if not audio_bytes:
            raise EngineError("edge-tts returned no audio.")
        samples, sample_rate = _decode_mp3(bytes(audio_bytes))
        return Audio(samples=samples, sample_rate=sample_rate, timings=align_boundaries(text, boundaries))


def align_boundaries(text: str, boundaries: list[tuple[str, float, float]]) -> tuple[WordTiming, ...]:
    """Merge service word boundaries into whitespace-delimited words of `text`."""
    words = text.split()
    if not boundaries or not words:
        return ()
    timings: list[WordTiming] = []
    cursor = 0
    for word in words:
        target = _PUNCT_RE.sub("", word).lower()
        start = end = None
        collected = ""
        while cursor < len(boundaries) and (not target or len(collected) < len(target)):
            piece, b_start, b_end = boundaries[cursor]
            cleaned = _PUNCT_RE.sub("", piece).lower()
            if target and cleaned and cleaned not in target:
                break
            collected += cleaned
            start = b_start if start is None else start
            end = b_end
            cursor += 1
            if not target:
                break
        if start is None or end is None:
            previous_end = timings[-1].end if timings else 0.0
            timings.append(WordTiming(word, previous_end, previous_end))
        else:
            timings.append(WordTiming(word, start, end))
    return tuple(timings)


def _decode_mp3(data: bytes) -> tuple[np.ndarray, int]:
    try:
        import soundfile as sf

        samples, sample_rate = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
    except Exception as exc:
        raise EngineError(f"Could not decode edge-tts audio (libsndfile without MP3 support?): {exc}") from exc
    return np.ascontiguousarray(samples.mean(axis=1), dtype=np.float32), int(sample_rate)


def _import_edge() -> Any:
    try:
        import edge_tts
    except ImportError as exc:
        raise EngineUnavailableError("edge-tts is not installed. Run: pip install edge-tts") from exc
    return edge_tts
