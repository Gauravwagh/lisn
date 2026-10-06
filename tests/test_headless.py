from rich.console import Console

from lisn.config import Config
from lisn.player.audio import SilentOutput
from lisn.player.engine import Player, Status
from lisn.player.headless import HeadlessController, HeadlessRenderer, format_clock, run_headless


def test_format_clock():
    assert format_clock(5) == "0:05"
    assert format_clock(65) == "1:05"
    assert format_clock(3725) == "1:02:05"


def test_controller_keys_and_render(small_document, fake_engine, monkeypatch):
    console = Console(file=open("/dev/null", "w"), width=80)
    renderer = HeadlessRenderer(small_document, console=console)
    player = Player(
        small_document, fake_engine, Config(voice="fake_voice"), output=SilentOutput(time_scale=4), cache=None
    )
    renderer.attach(player)
    marks = []
    controller = HeadlessController(
        player, renderer, on_bookmark=lambda i: marks.append(i) or "ok", voices=("fake_voice", "other")
    )
    answers = iter(["50", "Final", "2", "zzz"])
    monkeypatch.setattr("lisn.player.headless.read_line", lambda echo=None: next(answers))
    player.start()
    for key in (
        "space",
        "right",
        "+",
        "-",
        "]",
        "[",
        "h",
        "b",
        "g",
        "/",
        "t",
        "v",
        "r",
        "n",
        "p",
        "down",
        "up",
        "a",
        "s",
        "q",
    ):
        controller.handle(key)
    assert controller.quit_requested
    assert marks == [0]
    assert renderer.highlight == "sentence"
    renderer.render(player.state)
    player.close()
    controller.handle("/")  # "zzz" not found
    assert "not found" in renderer.message


def test_run_headless_non_interactive(small_document, fake_engine):
    console = Console(file=open("/dev/null", "w"), width=80)
    renderer = HeadlessRenderer(small_document, console=console)
    player = Player(
        small_document, fake_engine, Config(voice="fake_voice"), output=SilentOutput(time_scale=8), cache=None
    )
    run_headless(player, renderer, interactive=False)
    assert player.state.status == Status.FINISHED
