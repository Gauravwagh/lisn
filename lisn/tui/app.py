"""The lisn Textual app: document view with sentence/word highlighting and all controls."""

from __future__ import annotations

from collections.abc import Callable

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Footer, Input

from lisn.model import Document
from lisn.player.engine import Player, PlayerEvent, PlayerState, Status
from lisn.tui.widgets import HighlightSpec, ParagraphView, ProgressLine, StatusBar


class LisnApp(App[None]):
    TITLE = "lisn"
    CSS = """
    Screen { layout: vertical; }
    #reader { height: 1fr; }
    #prompt { dock: bottom; display: none; }
    #prompt.visible { display: block; }
    """
    BINDINGS = [
        Binding("space", "toggle", "Play/Pause"),
        Binding("s", "stop", "Stop"),
        Binding("right", "next_sentence", "Next sentence"),
        Binding("left", "prev_sentence", "Prev sentence"),
        Binding("down", "next_paragraph", "Next paragraph", show=False),
        Binding("up", "prev_paragraph", "Prev paragraph", show=False),
        Binding("n", "next_chapter", "Next chapter"),
        Binding("p", "prev_chapter", "Prev chapter", show=False),
        Binding("plus,equals_sign", "speed_up", "Faster"),
        Binding("minus", "speed_down", "Slower"),
        Binding("right_square_bracket", "volume_up", "Vol+", show=False),
        Binding("left_square_bracket", "volume_down", "Vol-", show=False),
        Binding("g", "jump", "Jump %"),
        Binding("slash", "search", "Search"),
        Binding("v", "voice", "Voice"),
        Binding("h", "toggle_highlight", "Word/Sentence"),
        Binding("a", "toggle_autoscroll", "Auto-scroll", show=False),
        Binding("b", "bookmark", "Bookmark"),
        Binding("r", "repeat", "Repeat", show=False),
        Binding("t", "sleep", "Sleep timer", show=False),
        Binding("q", "quit_app", "Quit"),
    ]

    def __init__(
        self,
        document: Document,
        player: Player,
        highlight: str = "word",
        autoscroll: bool = True,
        voices: tuple[str, ...] = (),
        on_bookmark: Callable[[int], str] | None = None,
        on_exit: Callable[[PlayerState], None] | None = None,
    ) -> None:
        super().__init__()
        self.document = document
        self.player = player
        self.highlight = highlight
        self.autoscroll = autoscroll
        self.voices = voices
        self.on_bookmark = on_bookmark
        self.on_exit = on_exit
        self._paragraphs: dict[int, ParagraphView] = {}
        self._by_sentence: dict[int, int] = {}
        self._active_paragraph: int | None = None
        self._prompt_kind = ""

    # ---- layout ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield StatusBar(id="status")
        yield ProgressLine(id="progress")
        with VerticalScroll(id="reader"):
            for paragraph_id, sentences in _group_paragraphs(self.document):
                is_heading = any(c.start_sentence == sentences[0].index for c in self.document.chapters)
                view = ParagraphView(sentences, is_heading)
                self._paragraphs[paragraph_id] = view
                for sentence in sentences:
                    self._by_sentence[sentence.index] = paragraph_id
                yield view
        yield Input(placeholder="", id="prompt")
        yield Footer()

    def on_mount(self) -> None:
        self.sub_title = self.document.title
        self.player.start()
        self.player.play()
        self.set_interval(0.5, self._refresh_status)
        self._apply_state(self.player.state)

    # ---- player events (arrive on the player thread) -------------------------------

    def player_event(self, event: PlayerEvent) -> None:
        try:
            self.call_from_thread(self._apply_state, event.state, event.kind)
        except RuntimeError:
            pass  # app is shutting down

    def _apply_state(self, state: PlayerState, kind: str = "state") -> None:
        active = state.status in (Status.PLAYING, Status.PAUSED, Status.LOADING)
        paragraph_id = self._by_sentence.get(state.index)
        if self._active_paragraph is not None and self._active_paragraph != paragraph_id:
            self._paragraphs[self._active_paragraph].apply(None)
        if paragraph_id is not None:
            view = self._paragraphs[paragraph_id]
            view.apply(HighlightSpec(state.index, state.word_index, self.highlight, active))
            if kind == "sentence" and self.autoscroll and paragraph_id != self._active_paragraph:
                self.query_one("#reader", VerticalScroll).scroll_to_widget(view, center=True, animate=False)
        self._active_paragraph = paragraph_id
        self._refresh_status(state)
        if state.status == Status.FINISHED:
            self.notify("Finished.", timeout=3)

    def _refresh_status(self, state: PlayerState | None = None) -> None:
        state = state or self.player.state
        elapsed, total = self.player.time_estimate()
        self.query_one("#status", StatusBar).show(self.document, state, elapsed, total, self.player.sleep_remaining())
        self.query_one("#progress", ProgressLine).show(self.player.percent_complete())

    # ---- actions -----------------------------------------------------------------

    def action_toggle(self) -> None:
        self.player.toggle()

    def action_stop(self) -> None:
        self.player.stop()

    def action_next_sentence(self) -> None:
        self.player.next_sentence()

    def action_prev_sentence(self) -> None:
        self.player.prev_sentence()

    def action_next_paragraph(self) -> None:
        self.player.next_paragraph()

    def action_prev_paragraph(self) -> None:
        self.player.prev_paragraph()

    def action_next_chapter(self) -> None:
        self.player.next_chapter()

    def action_prev_chapter(self) -> None:
        self.player.prev_chapter()

    def action_speed_up(self) -> None:
        self.player.speed_up()

    def action_speed_down(self) -> None:
        self.player.speed_down()

    def action_volume_up(self) -> None:
        self.player.volume_up()

    def action_volume_down(self) -> None:
        self.player.volume_down()

    def action_repeat(self) -> None:
        self.player.repeat()

    def action_jump(self) -> None:
        self._open_prompt("jump", "Jump to percent, e.g. 40")

    def action_search(self) -> None:
        self._open_prompt("search", "Search text")

    def action_sleep(self) -> None:
        self._open_prompt("sleep", "Sleep timer in minutes (0 clears)")

    def action_voice(self) -> None:
        current = self.player.state.voice
        if self.voices and current in self.voices:
            following = self.voices[(self.voices.index(current) + 1) % len(self.voices)]
            self.player.set_voice(following)
            self.notify(f"voice: {following}", timeout=2)
        else:
            self._open_prompt("voice", "Voice id, e.g. af_heart")

    def action_toggle_highlight(self) -> None:
        self.highlight = "sentence" if self.highlight == "word" else "word"
        self._apply_state(self.player.state)
        self.notify(f"highlight: {self.highlight}", timeout=2)

    def action_toggle_autoscroll(self) -> None:
        self.autoscroll = not self.autoscroll
        self.notify(f"auto-scroll {'on' if self.autoscroll else 'off'}", timeout=2)

    def action_bookmark(self) -> None:
        if self.on_bookmark is None:
            self.notify("Bookmarks are not available for this source.", severity="warning")
            return
        self.notify(self.on_bookmark(self.player.state.index), timeout=2)

    def action_quit_app(self) -> None:
        self.exit()

    # ---- prompt ------------------------------------------------------------------

    def _open_prompt(self, kind: str, placeholder: str) -> None:
        self._prompt_kind = kind
        prompt = self.query_one("#prompt", Input)
        prompt.placeholder = placeholder
        prompt.value = ""
        prompt.add_class("visible")
        prompt.focus()

    def _close_prompt(self) -> None:
        prompt = self.query_one("#prompt", Input)
        prompt.remove_class("visible")
        prompt.blur()
        self._prompt_kind = ""

    @on(Input.Submitted, "#prompt")
    def _prompt_submitted(self, event: Input.Submitted) -> None:
        kind, value = self._prompt_kind, event.value.strip()
        self._close_prompt()
        if not value:
            return
        if kind == "jump":
            self._jump(value)
        elif kind == "search":
            if self.player.search(value) is None:
                self.notify(f"'{value}' not found", severity="warning")
        elif kind == "sleep":
            self._sleep(value)
        elif kind == "voice":
            self.player.set_voice(value)

    def _jump(self, value: str) -> None:
        try:
            self.player.goto_percent(float(value.rstrip("%")))
        except ValueError:
            self.notify("Enter a number between 0 and 100", severity="warning")

    def _sleep(self, value: str) -> None:
        try:
            minutes = float(value)
        except ValueError:
            self.notify("Enter minutes as a number", severity="warning")
            return
        self.player.set_sleep_timer(minutes if minutes > 0 else None)
        self.notify(f"sleep timer: {minutes:g} min" if minutes > 0 else "sleep timer cleared", timeout=2)

    def on_key(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.key == "escape" and self._prompt_kind:
            self._close_prompt()
            event.stop()

    @on(ParagraphView.Clicked)
    def _paragraph_clicked(self, message: ParagraphView.Clicked) -> None:
        self.player.goto(message.sentence_index)
        if self.player.state.status not in (Status.PLAYING, Status.LOADING):
            self.player.play()

    # ---- shutdown ----------------------------------------------------------------

    async def on_unmount(self) -> None:
        self.player.close()
        if self.on_exit is not None:
            self.on_exit(self.player.state)


def _group_paragraphs(document: Document) -> list[tuple[int, tuple]]:
    groups: dict[int, list] = {}
    for sentence in document.sentences:
        groups.setdefault(sentence.paragraph, []).append(sentence)
    return [(paragraph_id, tuple(sentences)) for paragraph_id, sentences in groups.items()]
