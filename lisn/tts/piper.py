"""Piper engine: small ONNX voices, many languages (incl. Hindi). No word timings -> proportional."""

from __future__ import annotations

import logging
import re
import threading
from pathlib import Path
from typing import Any

import numpy as np

from lisn.errors import EngineError, EngineUnavailableError
from lisn.paths import data_dir
from lisn.tts.base import Audio, TTSEngine, Voice, clamp_speed

VOICE_RE = re.compile(r"^[a-z]{2,3}_[A-Z]{2}-[a-z0-9_]+-(x_low|low|medium|high)$")

# Curated subset of https://huggingface.co/rhasspy/piper-voices; any id matching VOICE_RE works.
PIPER_VOICES: tuple[tuple[str, str], ...] = (
    ("en_US-lessac-medium", "American English, neutral (default)"),
    ("en_US-amy-medium", "American English, female"),
    ("en_US-ryan-high", "American English, male"),
    ("en_US-joe-medium", "American English, male"),
    ("en_US-libritts_r-medium", "American English, multi-speaker"),
    ("en_GB-alan-medium", "British English, male"),
    ("en_GB-alba-medium", "Scottish English, female"),
    ("en_GB-cori-high", "British English, female"),
    ("hi_IN-pratham-medium", "Hindi, male"),
    ("hi_IN-priyamvada-medium", "Hindi, female"),
    ("de_DE-thorsten-medium", "German, male"),
    ("fr_FR-siwis-medium", "French, female"),
    ("es_ES-davefx-medium", "Spanish, male"),
    ("es_MX-claude-high", "Mexican Spanish, male"),
    ("it_IT-paola-medium", "Italian, female"),
    ("pt_BR-faber-medium", "Brazilian Portuguese, male"),
    ("nl_NL-mls-medium", "Dutch"),
    ("ru_RU-irina-medium", "Russian, female"),
    ("zh_CN-huayan-medium", "Mandarin, female"),
    ("ar_JO-kareem-medium", "Arabic, male"),
    ("tr_TR-dfki-medium", "Turkish"),
    ("vi_VN-vais1000-medium", "Vietnamese"),
)


class PiperEngine(TTSEngine):
    name = "piper"
    default_voice = "en_US-lessac-medium"

    def __init__(self, voices_dir: Path | None = None) -> None:
        self.voices_dir = voices_dir or (data_dir() / "piper")
        self._loaded: dict[str, Any] = {}
        self._lock = threading.Lock()

    def voices(self) -> tuple[Voice, ...]:
        return tuple(
            Voice(
                id=voice_id,
                engine=self.name,
                language=voice_id.split("-")[0].replace("_", "-"),
                gender="female" if "female" in description else ("male" if "male" in description else ""),
                description=description,
            )
            for voice_id, description in PIPER_VOICES
        )

    def warm_up(self) -> None:
        self._voice(self.default_voice)

    def synthesize(self, text: str, voice: str, speed: float = 1.0) -> Audio:
        if not text or not text.strip():
            raise EngineError("Cannot synthesize empty text.")
        if not VOICE_RE.match(voice or ""):
            raise EngineError(f"'{voice}' is not a Piper voice id (expected e.g. en_US-lessac-medium).")
        model = self._voice(voice)
        from piper.config import SynthesisConfig

        config = SynthesisConfig(length_scale=1.0 / clamp_speed(speed))
        chunks: list[np.ndarray] = []
        sample_rate = 0
        try:
            with self._lock:
                for chunk in model.synthesize(text, config):
                    chunks.append(np.asarray(chunk.audio_float_array, dtype=np.float32))
                    sample_rate = chunk.sample_rate
        except Exception as exc:
            raise EngineError(f"Piper failed on '{text[:60]}': {exc}") from exc
        if not chunks:
            raise EngineError(f"Piper produced no audio for '{text[:60]}'.")
        return Audio(samples=np.concatenate(chunks), sample_rate=sample_rate, timings=())

    def _voice(self, voice: str) -> Any:
        with self._lock:
            if voice in self._loaded:
                return self._loaded[voice]
            try:
                from piper import PiperVoice
                from piper.download_voices import download_voice
            except ImportError as exc:
                raise EngineUnavailableError("Piper is not installed. Run: pip install piper-tts") from exc
            self.voices_dir.mkdir(parents=True, exist_ok=True)
            model_path = self.voices_dir / f"{voice}.onnx"
            if not model_path.exists():
                logging.getLogger("lisn").info("Downloading Piper voice %s", voice)
                try:
                    download_voice(voice, self.voices_dir)
                except Exception as exc:
                    raise EngineError(f"Could not download Piper voice '{voice}': {exc}") from exc
            try:
                loaded = PiperVoice.load(str(model_path))
            except Exception as exc:
                raise EngineError(f"Could not load Piper voice '{voice}': {exc}") from exc
            self._loaded[voice] = loaded
            return loaded
