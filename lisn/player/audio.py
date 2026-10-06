"""Audio output with a callback-driven stream so pause/seek are sample-accurate.

The stream always runs; when there is nothing to play it emits silence. A clip is a
float32 mono array. Only one clip is active at a time; the player swaps clips as it
moves between sentences. `SilentOutput` has the same interface and uses the wall
clock instead of a device, for tests and `--no-audio` runs.
"""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod

import numpy as np

from lisn.errors import PlaybackError


class Output(ABC):
    @abstractmethod
    def play(self, samples: np.ndarray, sample_rate: int, start_seconds: float = 0.0) -> None: ...

    @abstractmethod
    def position(self) -> float: ...

    @abstractmethod
    def finished(self) -> bool: ...

    @abstractmethod
    def pause(self) -> None: ...

    @abstractmethod
    def resume(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def set_volume(self, volume: float) -> None: ...

    @abstractmethod
    def close(self) -> None: ...


class DeviceOutput(Output):
    """Plays through the default output device via sounddevice."""

    def __init__(self, volume: float = 1.0, device: int | str | None = None) -> None:
        self._lock = threading.Lock()
        self._clip: np.ndarray | None = None
        self._cursor = 0
        self._paused = False
        self._volume = float(volume)
        self._sample_rate = 0
        self._device = device
        self._stream = None

    def play(self, samples: np.ndarray, sample_rate: int, start_seconds: float = 0.0) -> None:
        clip = np.ascontiguousarray(samples, dtype=np.float32)
        self._ensure_stream(sample_rate)
        with self._lock:
            self._clip = clip
            self._cursor = min(len(clip), max(0, int(start_seconds * sample_rate)))
            self._paused = False

    def position(self) -> float:
        with self._lock:
            return self._cursor / self._sample_rate if self._sample_rate else 0.0

    def finished(self) -> bool:
        with self._lock:
            return self._clip is None or self._cursor >= len(self._clip)

    def pause(self) -> None:
        with self._lock:
            self._paused = True

    def resume(self) -> None:
        with self._lock:
            self._paused = False

    def stop(self) -> None:
        with self._lock:
            self._clip = None
            self._cursor = 0

    def set_volume(self, volume: float) -> None:
        with self._lock:
            self._volume = max(0.0, min(2.0, float(volume)))

    def close(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:  # device already gone; nothing useful to do
                pass

    def _ensure_stream(self, sample_rate: int) -> None:
        if self._stream is not None and self._sample_rate == sample_rate:
            return
        self.close()
        try:
            import sounddevice as sd
        except (ImportError, OSError) as exc:
            raise PlaybackError(
                "sounddevice/PortAudio is not available. Install PortAudio (brew install portaudio / "
                "apt install libportaudio2) or run with --no-audio."
            ) from exc
        try:
            self._stream = sd.OutputStream(
                samplerate=sample_rate,
                channels=1,
                dtype="float32",
                callback=self._callback,
                device=self._device,
                blocksize=0,
                latency="low",
            )
            self._stream.start()
        except Exception as exc:
            raise PlaybackError(f"Could not open the audio output device: {exc}") from exc
        self._sample_rate = sample_rate

    def _callback(self, outdata: np.ndarray, frames: int, _time_info, status) -> None:
        with self._lock:
            clip, cursor, paused, volume = self._clip, self._cursor, self._paused, self._volume
            if clip is None or paused or cursor >= len(clip):
                outdata.fill(0)
                return
            end = min(cursor + frames, len(clip))
            count = end - cursor
            outdata[:count, 0] = clip[cursor:end] * volume
            if count < frames:
                outdata[count:, 0] = 0
            self._cursor = end


class SilentOutput(Output):
    """Wall-clock simulated playback (no device). Used by tests and --no-audio."""

    def __init__(self, volume: float = 1.0, time_scale: float = 1.0) -> None:
        self._lock = threading.Lock()
        self._duration = 0.0
        self._started_at: float | None = None
        self._elapsed_before_pause = 0.0
        self._paused = False
        self._has_clip = False
        self._time_scale = time_scale
        self.volume = volume

    def play(self, samples: np.ndarray, sample_rate: int, start_seconds: float = 0.0) -> None:
        with self._lock:
            self._duration = len(samples) / float(sample_rate)
            self._elapsed_before_pause = max(0.0, start_seconds)
            self._started_at = time.monotonic()
            self._paused = False
            self._has_clip = True

    def position(self) -> float:
        with self._lock:
            return min(self._duration, self._elapsed_locked())

    def finished(self) -> bool:
        with self._lock:
            return not self._has_clip or self._elapsed_locked() >= self._duration

    def pause(self) -> None:
        with self._lock:
            if not self._paused:
                self._elapsed_before_pause = self._elapsed_locked()
                self._paused = True

    def resume(self) -> None:
        with self._lock:
            if self._paused:
                self._started_at = time.monotonic()
                self._paused = False

    def stop(self) -> None:
        with self._lock:
            self._has_clip = False
            self._duration = 0.0

    def set_volume(self, volume: float) -> None:
        self.volume = volume

    def close(self) -> None:
        self.stop()

    def _elapsed_locked(self) -> float:
        if self._paused or self._started_at is None:
            return self._elapsed_before_pause
        return self._elapsed_before_pause + (time.monotonic() - self._started_at) * self._time_scale
