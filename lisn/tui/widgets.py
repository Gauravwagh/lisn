"""Widgets for the reader: one ParagraphView per paragraph, a status bar and a prompt."""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text
from textual.message import Message
from textual.widgets import Static

from lisn.model import Document, Sentence
from lisn.player.engine import PlayerState, Status


@dataclass(frozen=True)
class HighlightSpec:
    """What the current paragraph should emphasise."""

    sentence_index: int
    word_index: int
    mode: str  # "word" | "sentence"
    active: bool


class ParagraphView(Static):
    """Renders the sentences of one paragraph; only the active paragraph is re-rendered."""

    DEFAULT_CSS = """
    ParagraphView { padding: 0 1 1 1; }
    ParagraphView.heading { text-style: bold; color: $accent; padding-top: 1; }
    """

    class Clicked(Message):
        def __init__(self, sentence_index: int) -> None:
            super().__init__()
            self.sentence_index = sentence_index

    def __init__(self, sentences: tuple[Sentence, ...], is_heading: bool) -> None:
        super().__init__(classes="heading" if is_heading else "")
        self.sentences = sentences
        self.spec: HighlightSpec | None = None
        self.can_focus = False

    def on_mount(self) -> None:
        self.update(self.build())

    def apply(self, spec: HighlightSpec | None) -> None:
        if spec == self.spec:
            return
        self.spec = spec
        self.update(self.build(), layout=False)

    def build(self) -> Text:
        text = Text()
        for position, sentence in enumerate(self.sentences):
            if position:
                text.append(" ")
            self._append_sentence(text, sentence)
        return text

    def _append_sentence(self, text: Text, sentence: Sentence) -> None:
        spec = self.spec
        current = spec is not None and spec.active and spec.sentence_index == sentence.index
        words = sentence.words
        for word_index, word in enumerate(words):
            style = ""
            if current:
                style = "on $surface-lighten-2" if spec.mode == "word" else "bold on $surface-lighten-2"
                if spec.mode == "word" and word_index == spec.word_index:
                    style = "bold $warning on $surface-lighten-2"
            text.append(word, style=_textual_style(style))
            if word_index < len(words) - 1:
                text.append(" ", style=_textual_style("on $surface-lighten-2") if current else "")

    def on_click(self, event) -> None:  # type: ignore[no-untyped-def]
        # Approximate: map the clicked line to a sentence by cumulative width.
        target = self.sentences[0].index
        if len(self.sentences) > 1 and self.size.width > 0:
            offset = event.y * self.size.width + event.x
            seen = 0
            for sentence in self.sentences:
                seen += len(sentence.text) + 1
                target = sentence.index
                if seen > offset:
                    break
        self.post_message(self.Clicked(target))


def _textual_style(style: str) -> str:
    """Rich Text styles cannot use Textual CSS variables; map to plain colours."""
    return style.replace("$surface-lighten-2", "grey23").replace("$warning", "yellow").replace("$accent", "cyan")


class StatusBar(Static):
    DEFAULT_CSS = "StatusBar { height: 1; background: $primary-background; color: $text; padding: 0 1; }"
    last_text = ""

    def show(self, document: Document, state: PlayerState, elapsed: float, total: float, sleep: float | None) -> None:
        chapter = document.chapter_of(state.index)
        parts = [
            f"{state.status.value:8}",
            f"{state.index + 1}/{len(document)}",
            f"{state.speed:.1f}x",
            f"vol {int(state.volume * 100)}%",
            state.voice,
            f"{_clock(elapsed)} / ~{_clock(total)}",
        ]
        if chapter:
            parts.append(chapter.title[:40])
        if sleep is not None:
            parts.append(f"sleep {_clock(sleep)}")
        if state.status == Status.ERROR:
            parts.append(f"ERROR: {state.error}")
        self.last_text = "  ".join(parts)
        self.update(self.last_text)


class ProgressLine(Static):
    DEFAULT_CSS = "ProgressLine { height: 1; padding: 0 1; color: $accent; }"

    def show(self, percent: float) -> None:
        width = max(10, self.size.width - 10)
        filled = int(width * percent / 100)
        self.update(Text("█" * filled + "░" * (width - filled) + f" {percent:5.1f}%"))


def _clock(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"
