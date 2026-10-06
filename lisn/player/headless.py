"""Headless (no TUI) playback: a rich Live panel plus the same key controls as the TUI."""

from __future__ import annotations

import threading
from collections.abc import Callable

from rich.console import Console, Group
from rich.live import Live
from rich.text import Text

from lisn.model import Document
from lisn.player.engine import Player, PlayerEvent, PlayerState, Status
from lisn.player.keys import is_interactive, raw_terminal, read_key, read_line

HELP = (
    "space play/pause  ←/→ sentence  ↑/↓ paragraph  n/p chapter  +/- speed  [/] volume  "
    "g jump%  / search  b bookmark  r repeat  t sleep  h highlight  q quit"
)


def format_clock(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


class HeadlessRenderer:
    def __init__(self, document: Document, console: Console | None = None, highlight: str = "word") -> None:
        self.document = document
        self.console = console or Console()
        self.highlight = highlight
        self.message = ""
        self._player: Player | None = None
        self._live: Live | None = None
        self._lock = threading.Lock()

    def attach(self, player: Player) -> None:
        self._player = player

    def __enter__(self) -> HeadlessRenderer:
        self._live = Live(Text(""), console=self.console, refresh_per_second=15, transient=False)
        self._live.__enter__()
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._live is not None:
            self._live.__exit__(*exc_info)

    def on_event(self, event: PlayerEvent) -> None:
        self.refresh(event.state)

    def refresh(self, state: PlayerState | None = None) -> None:
        with self._lock:
            if self._live is None:
                return
            current = state or (self._player.state if self._player else None)
            if current is not None:
                self._live.update(self.render(current))

    def render(self, state: PlayerState) -> Group:
        sentence = self.document.sentences[state.index]
        return Group(
            self._status_line(state), self._progress_line(state), self._sentence_line(sentence, state), self._footer()
        )

    def _status_line(self, state: PlayerState) -> Text:
        chapter = self.document.chapter_of(state.index)
        line = Text(style="dim")
        line.append(f"{self.document.title}  ")
        line.append(f"[{state.index + 1}/{len(self.document)}] ")
        line.append(f"{state.status.value}  {state.speed:.1f}x  vol {int(state.volume * 100)}%  {state.voice}")
        if chapter:
            line.append(f"  · {chapter.title}")
        if self._player and (remaining := self._player.sleep_remaining()) is not None:
            line.append(f"  · sleep {format_clock(remaining)}")
        return line

    def _progress_line(self, state: PlayerState) -> Text:
        width = max(10, min(60, self.console.width - 30))
        percent = self._player.percent_complete() if self._player else 0.0
        filled = int(width * percent / 100)
        elapsed, total = self._player.time_estimate() if self._player else (0.0, 0.0)
        line = Text()
        line.append("█" * filled + "░" * (width - filled), style="cyan")
        line.append(f" {percent:5.1f}%  {format_clock(elapsed)} / ~{format_clock(total)}", style="dim")
        return line

    def _sentence_line(self, sentence, state: PlayerState) -> Text:  # type: ignore[no-untyped-def]
        text = Text("\n")
        words = sentence.words
        active = state.status in (Status.PLAYING, Status.PAUSED, Status.LOADING)
        for word_index, word in enumerate(words):
            if self.highlight == "word" and active and word_index == state.word_index:
                text.append(word, style="bold yellow")
            elif self.highlight == "sentence" and active:
                text.append(word, style="bold")
            else:
                text.append(word)
            if word_index < len(words) - 1:
                text.append(" ")
        if state.status == Status.ERROR:
            text.append(f"\n{state.error}", style="red")
        return text

    def _footer(self) -> Text:
        footer = Text("\n")
        if self.message:
            footer.append(self.message + "\n", style="green")
        footer.append(HELP, style="dim")
        return footer


class HeadlessController:
    """Maps key presses to Player commands; prompts (g, /, v, t) read a line of input."""

    def __init__(
        self,
        player: Player,
        renderer: HeadlessRenderer,
        on_bookmark: Callable[[int], str] | None = None,
        voices: tuple[str, ...] = (),
    ) -> None:
        self.player = player
        self.renderer = renderer
        self.on_bookmark = on_bookmark
        self.voices = voices
        self.quit_requested = False

    def handle(self, key: str) -> None:
        handler = _KEYMAP.get(key)
        if handler is not None:
            handler(self)
            self.renderer.refresh()

    def _prompt(self, label: str) -> str:
        self.renderer.message = label
        self.renderer.refresh()
        value = read_line(lambda buffer: self._echo(label, buffer))
        self.renderer.message = ""
        return value

    def _echo(self, label: str, buffer: str) -> None:
        self.renderer.message = f"{label}{buffer}"
        self.renderer.refresh()

    def jump_percent(self) -> None:
        value = self._prompt("jump to %: ")
        try:
            self.player.goto_percent(float(value.rstrip("%")))
        except ValueError:
            self.renderer.message = "not a number" if value else ""

    def search(self) -> None:
        value = self._prompt("search: ")
        if value and self.player.search(value) is None:
            self.renderer.message = f"'{value}' not found"

    def change_voice(self) -> None:
        current = self.player.state.voice
        if self.voices and current in self.voices:
            self.player.set_voice(self.voices[(self.voices.index(current) + 1) % len(self.voices)])
            return
        value = self._prompt("voice: ")
        if value:
            self.player.set_voice(value.strip())

    def sleep_timer(self) -> None:
        value = self._prompt("sleep in minutes (0 to clear): ")
        try:
            minutes = float(value)
        except ValueError:
            return
        self.player.set_sleep_timer(minutes if minutes > 0 else None)
        self.renderer.message = f"sleep timer: {minutes:g} min" if minutes > 0 else "sleep timer cleared"

    def bookmark(self) -> None:
        if self.on_bookmark is None:
            self.renderer.message = "bookmarks unavailable"
            return
        self.renderer.message = self.on_bookmark(self.player.state.index)

    def toggle_highlight(self) -> None:
        self.renderer.highlight = "sentence" if self.renderer.highlight == "word" else "word"
        self.renderer.message = f"highlight: {self.renderer.highlight}"

    def quit(self) -> None:
        self.quit_requested = True


_KEYMAP: dict[str, Callable[[HeadlessController], None]] = {
    "space": lambda c: c.player.toggle(),
    "s": lambda c: c.player.stop(),
    "right": lambda c: c.player.next_sentence(),
    "left": lambda c: c.player.prev_sentence(),
    "down": lambda c: c.player.next_paragraph(),
    "up": lambda c: c.player.prev_paragraph(),
    "n": lambda c: c.player.next_chapter(),
    "p": lambda c: c.player.prev_chapter(),
    "+": lambda c: c.player.speed_up(),
    "=": lambda c: c.player.speed_up(),
    "-": lambda c: c.player.speed_down(),
    "]": lambda c: c.player.volume_up(),
    "[": lambda c: c.player.volume_down(),
    "g": HeadlessController.jump_percent,
    "/": HeadlessController.search,
    "v": HeadlessController.change_voice,
    "t": HeadlessController.sleep_timer,
    "b": HeadlessController.bookmark,
    "r": lambda c: c.player.repeat(),
    "h": HeadlessController.toggle_highlight,
    "a": lambda c: None,  # auto-scroll only applies to the TUI
    "q": HeadlessController.quit,
    "escape": HeadlessController.quit,
}


def run_headless(
    player: Player,
    renderer: HeadlessRenderer,
    controller: HeadlessController | None = None,
    interactive: bool | None = None,
) -> None:
    """Play until the end, `q`, or Ctrl-C. Keys are read only on an interactive terminal."""
    renderer.attach(player)
    interactive = is_interactive() if interactive is None else interactive
    controller = controller or HeadlessController(player, renderer)
    with renderer:
        player.start()
        player.play()
        try:
            with raw_terminal():
                while not controller.quit_requested:
                    if player.state.status in (Status.FINISHED, Status.ERROR):
                        break
                    if interactive:
                        key = read_key(timeout=0.1)
                        if key is not None:
                            controller.handle(key)
                    else:
                        player.wait(timeout=0.1)
                    renderer.refresh()
        except KeyboardInterrupt:
            player.stop()
        finally:
            player.close()
