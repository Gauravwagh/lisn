"""Kokoro-82M engine (default). CPU works; CUDA/MPS are used automatically if present.

Word timings come straight from the model's predicted phoneme durations (English voices).
Other languages are phonemized by the bundled espeak-ng and get proportional timings.
"""

from __future__ import annotations

import logging
import os
import threading
import warnings
from typing import Any

import numpy as np

from lisn.errors import EngineError, EngineUnavailableError
from lisn.tts.base import Audio, TTSEngine, Voice, WordTiming, clamp_speed
from lisn.tts.timing import proportional_timings

REPO_ID = "hexgrad/Kokoro-82M"
SAMPLE_RATE = 24_000
LANG_NAMES = {
    "a": "en-US",
    "b": "en-GB",
    "e": "es",
    "f": "fr",
    "h": "hi",
    "i": "it",
    "j": "ja",
    "p": "pt-BR",
    "z": "zh",
}

# Voices shipped in hexgrad/Kokoro-82M (v1.0). Grade in the HF model card; "+" = higher quality.
KOKORO_VOICES: tuple[tuple[str, str], ...] = (
    ("af_heart", "American female, warm (best overall)"),
    ("af_bella", "American female, expressive"),
    ("af_nicole", "American female, soft/ASMR"),
    ("af_sarah", "American female, clear"),
    ("af_sky", "American female, bright"),
    ("af_alloy", "American female"),
    ("af_aoede", "American female"),
    ("af_jessica", "American female"),
    ("af_kore", "American female"),
    ("af_nova", "American female"),
    ("af_river", "American female"),
    ("am_michael", "American male, steady"),
    ("am_fenrir", "American male, deep"),
    ("am_puck", "American male, lively"),
    ("am_adam", "American male"),
    ("am_echo", "American male"),
    ("am_eric", "American male"),
    ("am_liam", "American male"),
    ("am_onyx", "American male, deep"),
    ("am_santa", "American male, Santa"),
    ("bf_emma", "British female, warm"),
    ("bf_isabella", "British female"),
    ("bf_alice", "British female"),
    ("bf_lily", "British female"),
    ("bm_george", "British male, narrator"),
    ("bm_fable", "British male, storyteller"),
    ("bm_lewis", "British male"),
    ("bm_daniel", "British male"),
    ("hf_alpha", "Hindi female"),
    ("hf_beta", "Hindi female"),
    ("hm_omega", "Hindi male"),
    ("hm_psi", "Hindi male"),
    ("ef_dora", "Spanish female"),
    ("em_alex", "Spanish male"),
    ("em_santa", "Spanish male"),
    ("ff_siwis", "French female"),
    ("if_sara", "Italian female"),
    ("im_nicola", "Italian male"),
    ("pf_dora", "Brazilian Portuguese female"),
    ("pm_alex", "Brazilian Portuguese male"),
    ("pm_santa", "Brazilian Portuguese male"),
    ("jf_alpha", "Japanese female (needs misaki[ja])"),
    ("jm_kumo", "Japanese male (needs misaki[ja])"),
    ("zf_xiaobei", "Mandarin female (needs misaki[zh])"),
    ("zm_yunxi", "Mandarin male (needs misaki[zh])"),
)


class KokoroEngine(TTSEngine):
    name = "kokoro"
    default_voice = "af_heart"

    def __init__(self, device: str | None = None) -> None:
        self._device = device
        self._model: Any = None
        self._pipelines: dict[str, Any] = {}
        self._lock = threading.Lock()

    def supports_word_timings(self) -> bool:
        return True

    def voices(self) -> tuple[Voice, ...]:
        return tuple(
            Voice(
                id=voice_id,
                engine=self.name,
                language=LANG_NAMES.get(voice_id[0], voice_id[0]),
                gender="female" if voice_id[1] == "f" else "male",
                description=description,
            )
            for voice_id, description in KOKORO_VOICES
        )

    def warm_up(self) -> None:
        self._pipeline("a")

    def synthesize(self, text: str, voice: str, speed: float = 1.0) -> Audio:
        if not text or not text.strip():
            raise EngineError("Cannot synthesize empty text.")
        validate_voice(voice)
        lang = voice[0].lower()
        rate = clamp_speed(speed)
        pipeline = self._pipeline(lang)
        chunks: list[np.ndarray] = []
        timings: list[WordTiming] = []
        offset = 0.0
        try:
            with self._lock:
                results = list(pipeline(text, voice=voice, speed=rate, split_pattern=None))
        except Exception as exc:  # the model raises a wide range of errors
            raise EngineError(f"Kokoro failed on '{text[:60]}...': {exc}") from exc
        for result in results:
            if result.audio is None:
                continue
            samples = np.asarray(result.audio.detach().cpu().numpy(), dtype=np.float32)
            chunk_duration = len(samples) / SAMPLE_RATE
            chunk_timings = _timings_from_tokens(result.tokens, offset) if lang in "ab" else ()
            if not chunk_timings:
                chunk_timings = proportional_timings(tuple(result.graphemes.split()), chunk_duration, offset)
            chunks.append(samples)
            timings.extend(chunk_timings)
            offset += chunk_duration
        if not chunks:
            raise EngineError(f"Kokoro produced no audio for '{text[:60]}'.")
        return Audio(samples=np.concatenate(chunks), sample_rate=SAMPLE_RATE, timings=tuple(timings))

    def _pipeline(self, lang: str) -> Any:
        with self._lock:
            if lang in self._pipelines:
                return self._pipelines[lang]
            KPipeline, KModel = _import_kokoro()
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    if self._model is None:
                        self._model = KModel(repo_id=REPO_ID).to(_pick_device(self._device)).eval()
                    pipeline = KPipeline(lang_code=lang, repo_id=REPO_ID, model=self._model)
            except Exception as exc:
                raise EngineError(f"Could not load Kokoro for language '{lang}': {exc}") from exc
            self._pipelines[lang] = pipeline
            return pipeline


def validate_voice(voice: str) -> None:
    known = {v for v, _ in KOKORO_VOICES}
    if not isinstance(voice, str) or not voice:
        raise EngineError("A voice id is required, e.g. af_heart.")
    for part in voice.split(","):  # Kokoro allows blends like "af_heart,af_sky"
        if part.strip() not in known:
            raise EngineError(f"Unknown Kokoro voice '{part.strip()}'. Run `lisn voices` to list them.")


def _timings_from_tokens(tokens: Any, offset: float) -> tuple[WordTiming, ...]:
    """Group misaki tokens into whitespace-delimited words and take min/max timestamps."""
    if not tokens:
        return ()
    words: list[WordTiming] = []
    group_text = ""
    group_start: float | None = None
    group_end: float | None = None
    for token in tokens:
        group_text += token.text
        if token.start_ts is not None and token.end_ts is not None:
            group_start = token.start_ts if group_start is None else min(group_start, token.start_ts)
            group_end = token.end_ts if group_end is None else max(group_end, token.end_ts)
        if token.whitespace:
            words.append(_finish_group(group_text, group_start, group_end, words, offset))
            group_text, group_start, group_end = "", None, None
    if group_text:
        words.append(_finish_group(group_text, group_start, group_end, words, offset))
    return tuple(words)


def _finish_group(
    text: str, start: float | None, end: float | None, previous: list[WordTiming], offset: float
) -> WordTiming:
    last_end = previous[-1].end if previous else offset
    if start is None or end is None:
        return WordTiming(word=text, start=last_end, end=last_end)
    return WordTiming(word=text, start=start + offset, end=end + offset)


def _pick_device(requested: str | None) -> str:
    if requested:
        return requested
    env = os.environ.get("LISN_DEVICE")
    if env:
        return env
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
    except Exception:  # pragma: no cover - torch import problems surface elsewhere
        pass
    return "cpu"  # MPS is slower than CPU for this small model and less stable


def _import_kokoro() -> tuple[Any, Any]:
    logging.getLogger("kokoro").setLevel(logging.ERROR)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from kokoro import KModel, KPipeline
    except ImportError as exc:
        raise EngineUnavailableError("Kokoro is not installed. Run: pip install kokoro") from exc
    return KPipeline, KModel
