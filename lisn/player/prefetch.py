"""Synthesize sentences ahead of playback on a single worker thread, through the cache."""

from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor

from lisn.model import Sentence
from lisn.tts.base import Audio, TTSEngine
from lisn.tts.cache import AudioCache
from lisn.tts.timing import display_word_timings


class SentenceSynthesizer:
    """engine + cache -> Audio whose timings are already mapped to display words."""

    def __init__(self, engine: TTSEngine, cache: AudioCache | None) -> None:
        self.engine = engine
        self.cache = cache

    def synthesize(self, sentence: Sentence, voice: str, speed: float) -> Audio:
        key = AudioCache.key(self.engine.name, voice, speed, sentence.speech_text)
        cached = self.cache.get(key) if self.cache else None
        if cached is not None:
            return cached
        raw = self.engine.synthesize(sentence.speech_text, voice, speed)
        audio = Audio(
            samples=raw.samples,
            sample_rate=raw.sample_rate,
            timings=display_word_timings(sentence, raw.timings, raw.duration),
        )
        if self.cache:
            self.cache.put(key, audio)
        return audio


class Prefetcher:
    """Keeps futures for a window of sentence indices; one worker so the engine is never
    called concurrently. Changing voice/speed invalidates everything (different audio)."""

    def __init__(self, synthesizer: SentenceSynthesizer, sentences: tuple[Sentence, ...]) -> None:
        self._synth = synthesizer
        self._sentences = sentences
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lisn-tts")
        self._futures: dict[tuple[int, str, float], Future[Audio]] = {}
        self._lock = threading.Lock()

    def future(self, index: int, voice: str, speed: float) -> Future[Audio]:
        key = (index, voice, round(speed, 2))
        with self._lock:
            existing = self._futures.get(key)
            if existing is not None:
                return existing
            sentence = self._sentences[index]
            created = self._executor.submit(self._synth.synthesize, sentence, voice, speed)
            self._futures[key] = created
            return created

    def ensure_window(self, start: int, count: int, voice: str, speed: float) -> None:
        for index in range(start, min(start + count, len(self._sentences))):
            self.future(index, voice, speed)
        self._prune(start, count, voice, speed)

    def _prune(self, start: int, count: int, voice: str, speed: float) -> None:
        keep = {(i, voice, round(speed, 2)) for i in range(max(0, start - 1), start + count)}
        with self._lock:
            for key, fut in list(self._futures.items()):
                if key not in keep and fut.cancel():
                    del self._futures[key]

    def shutdown(self) -> None:
        with self._lock:
            for fut in self._futures.values():
                fut.cancel()
            self._futures = {}
        self._executor.shutdown(wait=False, cancel_futures=True)
