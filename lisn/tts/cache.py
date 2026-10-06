"""On-disk audio cache keyed by hash(engine, voice, speed, text).

Each entry is a single .npz file holding samples, sample rate and timings. Reads and
writes are atomic enough for a single user: writes go to a temp file then rename.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np

from lisn.paths import audio_cache_dir
from lisn.tts.base import Audio, WordTiming


class AudioCache:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or audio_cache_dir()
        self.directory.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key(engine: str, voice: str, speed: float, text: str) -> str:
        payload = f"{engine}\x1f{voice}\x1f{speed:.2f}\x1f{text}".encode()
        return hashlib.sha256(payload).hexdigest()

    def path_for(self, key: str) -> Path:
        return self.directory / key[:2] / f"{key}.npz"

    def get(self, key: str) -> Audio | None:
        path = self.path_for(key)
        if not path.exists():
            return None
        try:
            with np.load(path, allow_pickle=False) as data:
                samples = np.asarray(data["samples"], dtype=np.float32)
                sample_rate = int(data["sample_rate"])
                timings = tuple(
                    WordTiming(word=str(t["word"]), start=float(t["start"]), end=float(t["end"]))
                    for t in json.loads(str(data["timings"]))
                )
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            _safe_unlink(path)
            return None
        return Audio(samples=samples, sample_rate=sample_rate, timings=timings)

    def put(self, key: str, audio: Audio) -> None:
        path = self.path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp.npz")
        timings_json = json.dumps([{"word": t.word, "start": t.start, "end": t.end} for t in audio.timings])
        try:
            np.savez(tmp, samples=audio.samples.astype(np.float32), sample_rate=audio.sample_rate, timings=timings_json)
            os.replace(tmp, path)
        except OSError:
            _safe_unlink(tmp)

    def clear(self) -> int:
        removed = 0
        for file in self.directory.rglob("*.npz"):
            _safe_unlink(file)
            removed += 1
        return removed

    def size_bytes(self) -> int:
        return sum(f.stat().st_size for f in self.directory.rglob("*.npz"))


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
