"""The Player: a state machine on its own thread that drives Output and Prefetcher.

Public methods enqueue commands; the loop applies them and emits PlayerEvents to the
listener (TUI, headless renderer, HTTP server). State is exposed as an immutable
PlayerState snapshot.
"""

from __future__ import annotations

import bisect
import enum
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from lisn.config import Config
from lisn.errors import LisnError
from lisn.model import Document
from lisn.player.audio import DeviceOutput, Output
from lisn.player.prefetch import Prefetcher, SentenceSynthesizer
from lisn.tts.base import MAX_SPEED, MIN_SPEED, Audio, TTSEngine, clamp_speed
from lisn.tts.cache import AudioCache

TICK_SECONDS = 0.02
DEFAULT_CHARS_PER_SECOND = 15.0
SPEED_STEP = 0.1
VOLUME_STEP = 0.1


class Status(enum.Enum):
    IDLE = "idle"
    LOADING = "loading"
    PLAYING = "playing"
    PAUSED = "paused"
    STOPPED = "stopped"
    FINISHED = "finished"
    ERROR = "error"


@dataclass(frozen=True)
class PlayerState:
    status: Status
    index: int
    word_index: int
    voice: str
    speed: float
    volume: float
    position: float  # seconds into the current sentence
    duration: float  # seconds of the current sentence
    elapsed_chars: int
    error: str = ""
    sleep_deadline: float | None = None  # time.monotonic() value


@dataclass(frozen=True)
class PlayerEvent:
    kind: str  # "state" | "sentence" | "word" | "finished" | "error"
    state: PlayerState


Listener = Callable[[PlayerEvent], None]


class Player:
    def __init__(
        self,
        document: Document,
        engine: TTSEngine,
        config: Config,
        output: Output | None = None,
        cache: AudioCache | None = None,
        listener: Listener | None = None,
        start_index: int = 0,
    ) -> None:
        if not document.sentences:
            raise LisnError("The document has no sentences to read.")
        self.document = document
        self._output = output or DeviceOutput(volume=config.volume)
        self._prefetcher = Prefetcher(SentenceSynthesizer(engine, cache), document.sentences)
        self._prefetch_count = config.prefetch
        self._listener = listener or (lambda event: None)
        self._commands: queue.Queue[tuple[str, Any]] = queue.Queue()
        first = max(0, min(start_index, len(document.sentences) - 1))
        self._state = PlayerState(
            status=Status.IDLE,
            index=first,
            word_index=-1,
            voice=config.voice,
            speed=clamp_speed(config.speed),
            volume=config.volume,
            position=0.0,
            duration=0.0,
            elapsed_chars=sum(len(s.text) for s in document.sentences[:first]),
        )
        self._audio: Audio | None = None
        self._rate_chars = 0.0
        self._rate_seconds = 0.0
        self._word_starts: list[float] = []
        self._pending: Any = None
        self._resume_at = 0.0
        self._closing = threading.Event()
        self._done = threading.Event()
        self._thread = threading.Thread(target=self._run, name="lisn-player", daemon=True)

    # ---- public API (thread-safe) ------------------------------------------------

    @property
    def state(self) -> PlayerState:
        return self._state

    def start(self) -> None:
        self._thread.start()

    def play(self) -> None:
        self._commands.put(("play", None))

    def pause(self) -> None:
        self._commands.put(("pause", None))

    def toggle(self) -> None:
        self._commands.put(("toggle", None))

    def stop(self) -> None:
        self._commands.put(("stop", None))

    def repeat(self) -> None:
        self._commands.put(("goto", self._state.index))

    def next_sentence(self) -> None:
        self._commands.put(("goto", self._state.index + 1))

    def prev_sentence(self) -> None:
        self._commands.put(("goto", self._state.index - 1))

    def next_paragraph(self) -> None:
        self._commands.put(("goto", self._paragraph_jump(+1)))

    def prev_paragraph(self) -> None:
        self._commands.put(("goto", self._paragraph_jump(-1)))

    def next_chapter(self) -> None:
        self._commands.put(("goto", self._chapter_jump(+1)))

    def prev_chapter(self) -> None:
        self._commands.put(("goto", self._chapter_jump(-1)))

    def goto(self, index: int) -> None:
        self._commands.put(("goto", index))

    def goto_percent(self, percent: float) -> None:
        self._commands.put(("goto", self.index_at_percent(percent)))

    def set_speed(self, speed: float) -> None:
        self._commands.put(("speed", clamp_speed(speed)))

    def speed_up(self) -> None:
        self.set_speed(round(self._state.speed + SPEED_STEP, 2))

    def speed_down(self) -> None:
        self.set_speed(round(self._state.speed - SPEED_STEP, 2))

    def set_volume(self, volume: float) -> None:
        self._commands.put(("volume", max(0.0, min(2.0, volume))))

    def volume_up(self) -> None:
        self.set_volume(round(self._state.volume + VOLUME_STEP, 2))

    def volume_down(self) -> None:
        self.set_volume(round(self._state.volume - VOLUME_STEP, 2))

    def set_voice(self, voice: str) -> None:
        self._commands.put(("voice", voice))

    def search(self, query: str) -> int | None:
        """Jump to the next sentence containing `query`; returns its index or None."""
        found = self.document.search(query, start_after=self._state.index)
        if found is not None:
            self.goto(found)
        return found

    def set_sleep_timer(self, minutes: float | None) -> None:
        self._commands.put(("sleep", minutes))

    def sleep_remaining(self) -> float | None:
        deadline = self._state.sleep_deadline
        return None if deadline is None else max(0.0, deadline - time.monotonic())

    def time_estimate(self) -> tuple[float, float]:
        """(elapsed_seconds, total_seconds) estimated from the synthesis rate seen so far."""
        rate = (
            self._rate_chars / self._rate_seconds
            if self._rate_seconds > 0
            else DEFAULT_CHARS_PER_SECOND * self._state.speed
        )
        elapsed = self._state.elapsed_chars / rate + self._state.position
        return elapsed, self.document.total_chars / rate

    def wait(self, timeout: float | None = None) -> bool:
        """Block until playback finishes or the player is closed."""
        return self._done.wait(timeout)

    def close(self) -> None:
        self._closing.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._prefetcher.shutdown()
        self._output.close()
        self._done.set()

    def index_at_percent(self, percent: float) -> int:
        target = max(0.0, min(100.0, percent)) / 100.0 * self.document.total_chars
        seen = 0
        for sentence in self.document.sentences:
            if seen + len(sentence.text) >= target:
                return sentence.index
            seen += len(sentence.text)
        return len(self.document.sentences) - 1

    def percent_complete(self) -> float:
        if self.document.total_chars == 0:
            return 0.0
        return 100.0 * self._state.elapsed_chars / self.document.total_chars

    # ---- loop --------------------------------------------------------------------

    def _run(self) -> None:
        try:
            while not self._closing.is_set():
                self._drain_commands()
                self._tick()
                time.sleep(TICK_SECONDS)
        except Exception as exc:  # keep the thread from dying silently
            self._set(status=Status.ERROR, error=str(exc))
            self._emit("error")
        finally:
            self._done.set()

    def _drain_commands(self) -> None:
        while True:
            try:
                command, arg = self._commands.get_nowait()
            except queue.Empty:
                return
            handler = getattr(self, f"_cmd_{command}")
            handler(arg)

    def _tick(self) -> None:
        state = self._state
        if state.sleep_deadline is not None and time.monotonic() >= state.sleep_deadline:
            self._set(sleep_deadline=None)
            self._cmd_pause(None)
            return
        if state.status == Status.LOADING or (state.status == Status.PAUSED and self._pending is not None):
            self._poll_pending()
        elif state.status == Status.PLAYING:
            self._track_word()
            if self._output.finished():
                self._advance()

    # ---- commands ----------------------------------------------------------------

    def _cmd_play(self, _: Any) -> None:
        status = self._state.status
        if status == Status.PAUSED and self._audio is not None:
            self._output.resume()
            self._set(status=Status.PLAYING)
            self._emit("state")
        elif status == Status.PAUSED and self._pending is not None:
            self._set(status=Status.LOADING)  # paused while loading: resume once audio arrives
            self._emit("state")
        elif status in (Status.IDLE, Status.STOPPED, Status.FINISHED, Status.ERROR, Status.PAUSED):
            if status == Status.FINISHED:
                self._set(index=0, elapsed_chars=0)
            self._load_current()

    def _cmd_pause(self, _: Any) -> None:
        if self._state.status == Status.PLAYING:
            self._output.pause()
            self._set(status=Status.PAUSED)
            self._emit("state")
        elif self._state.status == Status.LOADING:
            self._set(status=Status.PAUSED)  # audio will be parked at the first word when it arrives
            self._emit("state")

    def _cmd_toggle(self, _: Any) -> None:
        if self._state.status == Status.PLAYING:
            self._cmd_pause(None)
        else:
            self._cmd_play(None)

    def _cmd_stop(self, _: Any) -> None:
        self._output.stop()
        self._audio = None
        self._pending = None
        self._set(status=Status.STOPPED, word_index=-1, position=0.0)
        self._emit("state")

    def _cmd_goto(self, index: int) -> None:
        clamped = max(0, min(int(index), len(self.document.sentences) - 1))
        resume = self._state.status in (Status.PLAYING, Status.LOADING, Status.PAUSED)
        self._output.stop()
        self._audio = None
        self._pending = None
        self._set(index=clamped, word_index=-1, position=0.0, duration=0.0, elapsed_chars=self._chars_before(clamped))
        if resume and self._state.status != Status.PAUSED:
            self._load_current()
        else:
            self._set(status=Status.PAUSED if resume else Status.STOPPED)
            self._emit("sentence")

    def _cmd_speed(self, speed: float) -> None:
        self._restart_with(speed=speed)

    def _cmd_voice(self, voice: str) -> None:
        self._restart_with(voice=voice)

    def _cmd_sleep(self, minutes: float | None) -> None:
        deadline = None if minutes is None or minutes <= 0 else time.monotonic() + minutes * 60
        self._set(sleep_deadline=deadline)
        self._emit("state")

    def _cmd_volume(self, volume: float) -> None:
        self._output.set_volume(volume)
        self._set(volume=volume)
        self._emit("state")

    def _restart_with(self, **changes: Any) -> None:
        """Re-synthesize the current sentence with new voice/speed, resuming at the current word."""
        was_playing = self._state.status in (Status.PLAYING, Status.LOADING)
        previous_speed = self._state.speed
        word_time = self._current_word_start()
        self._output.stop()
        self._audio = None
        self._pending = None
        self._set(**changes)
        if was_playing:
            self._resume_at = word_time * previous_speed / self._state.speed if "speed" in changes else word_time
            self._load_current()
        else:
            self._set(status=Status.PAUSED if self._state.status == Status.PAUSED else Status.STOPPED)
            self._emit("state")

    # ---- loading / playback ------------------------------------------------------

    def _load_current(self) -> None:
        state = self._state
        self._prefetcher.ensure_window(state.index, self._prefetch_count + 1, state.voice, state.speed)
        self._pending = self._prefetcher.future(state.index, state.voice, state.speed)
        self._set(status=Status.LOADING, word_index=-1, position=0.0)
        self._emit("sentence")

    def _poll_pending(self) -> None:
        if self._pending is None or not self._pending.done():
            return
        future, self._pending = self._pending, None
        try:
            audio = future.result()
        except Exception as exc:
            self._set(status=Status.ERROR, error=f"Synthesis failed: {exc}")
            self._emit("error")
            return
        self._audio = audio
        self._rate_chars += len(self.document.sentences[self._state.index].text)
        self._rate_seconds += audio.duration
        self._word_starts = [t.start for t in audio.timings]
        start_at = min(self._resume_at, max(0.0, audio.duration - 0.05))
        self._resume_at = 0.0
        self._output.play(audio.samples, audio.sample_rate, start_at)
        paused = self._state.status == Status.PAUSED
        if paused:
            self._output.pause()
        self._set(status=Status.PAUSED if paused else Status.PLAYING, duration=audio.duration, position=start_at)
        self._emit("state")
        self._track_word()

    def _track_word(self) -> None:
        if self._audio is None:
            return
        position = self._output.position()
        word_index = bisect.bisect_right(self._word_starts, position + 0.01) - 1
        if word_index != self._state.word_index:
            self._set(word_index=word_index, position=position)
            self._emit("word")
        else:
            self._set(position=position)

    def _advance(self) -> None:
        state = self._state
        finished_chars = state.elapsed_chars + len(self.document.sentences[state.index].text)
        next_index = state.index + 1
        self._audio = None
        if next_index >= len(self.document.sentences):
            self._output.stop()
            self._set(status=Status.FINISHED, elapsed_chars=finished_chars, word_index=-1, position=0.0)
            self._emit("finished")
            return
        self._set(index=next_index, elapsed_chars=finished_chars)
        self._load_current()

    # ---- helpers -----------------------------------------------------------------

    def _current_word_start(self) -> float:
        if self._audio is None or self._state.word_index < 0:
            return 0.0
        if self._state.word_index < len(self._audio.timings):
            return self._audio.timings[self._state.word_index].start
        return 0.0

    def _chars_before(self, index: int) -> int:
        return sum(len(s.text) for s in self.document.sentences[:index])

    def _paragraph_jump(self, direction: int) -> int:
        sentences = self.document.sentences
        current = sentences[self._state.index]
        if direction > 0:
            for sentence in sentences[self._state.index + 1 :]:
                if sentence.paragraph != current.paragraph:
                    return sentence.index
            return len(sentences) - 1
        first_of_current = next(s.index for s in sentences if s.paragraph == current.paragraph)
        if first_of_current < self._state.index:
            return first_of_current
        if first_of_current == 0:
            return 0
        previous = sentences[first_of_current - 1]
        return next(s.index for s in sentences if s.paragraph == previous.paragraph)

    def _chapter_jump(self, direction: int) -> int:
        chapters = self.document.chapters
        if not chapters:
            return 0 if direction < 0 else len(self.document.sentences) - 1
        current = self.document.chapter_of(self._state.index)
        if current is None:
            return self._state.index
        if direction > 0:
            target = current.index + 1
            return chapters[target].start_sentence if target < len(chapters) else len(self.document.sentences) - 1
        if current.start_sentence < self._state.index:
            return current.start_sentence
        return chapters[max(0, current.index - 1)].start_sentence

    def _set(self, **changes: Any) -> None:
        self._state = replace(self._state, **changes)

    def _emit(self, kind: str) -> None:
        try:
            self._listener(PlayerEvent(kind=kind, state=self._state))
        except Exception:  # a broken listener must never kill playback
            pass


__all__ = ["MAX_SPEED", "MIN_SPEED", "Player", "PlayerEvent", "PlayerState", "Status"]
