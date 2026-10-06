import pytest

from lisn.config import Config
from lisn.player.audio import SilentOutput
from lisn.player.engine import Player, Status
from lisn.tui.app import LisnApp
from lisn.tui.widgets import ParagraphView, StatusBar

pytestmark = pytest.mark.asyncio


def make_app(document, engine, marks=None, time_scale=4.0):
    player = Player(
        document, engine, Config(voice="fake_voice"), output=SilentOutput(time_scale=time_scale), cache=None
    )
    app = LisnApp(
        document,
        player,
        voices=("fake_voice", "other"),
        on_bookmark=(lambda i: (marks.append(i), "ok")[1]) if marks is not None else None,
    )
    player._listener = app.player_event
    return app, player


async def test_tui_renders_and_controls(small_document, fake_engine):
    marks = []
    fake_engine.seconds_per_word = 0.5  # keep playback going for the whole test
    app, player = make_app(small_document, fake_engine, marks, time_scale=1.0)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.3)
        assert len(app.query(ParagraphView)) == 5  # 2 headings + 3 paragraphs
        assert player.state.status in (Status.PLAYING, Status.LOADING)
        await pilot.press("space")
        await pilot.pause(0.2)
        assert player.state.status == Status.PAUSED
        await pilot.press("right", "plus", "right_square_bracket", "h", "a", "b", "r", "v", "n", "p", "down", "up")
        await pilot.pause(0.3)
        assert marks and app.highlight == "sentence" and app.autoscroll is False
        assert abs(player.state.speed - 1.1) < 1e-9 and abs(player.state.volume - 1.1) < 1e-9
        await pilot.press("g")
        await pilot.press(*"100")
        await pilot.press("enter")
        await pilot.pause(0.3)
        assert player.state.index == len(small_document) - 1
        await pilot.press("slash")
        await pilot.press(*"First")
        await pilot.press("enter")
        await pilot.pause(0.3)
        assert player.state.index == 1
        await pilot.press("t")
        await pilot.press("5", "enter")
        await pilot.pause(0.2)
        assert player.sleep_remaining() is not None
        assert "1.1x" in app.query_one("#status", StatusBar).last_text
        await pilot.press("s")
        await pilot.press("q")
    assert player.state.status in (Status.STOPPED, Status.PAUSED)


async def test_tui_plays_to_end(small_document, fake_engine):
    app, player = make_app(small_document, fake_engine)
    async with app.run_test(size=(80, 24)) as pilot:
        for _ in range(60):
            await pilot.pause(0.1)
            if player.state.status == Status.FINISHED:
                break
        assert player.state.status == Status.FINISHED
        await pilot.press("q")
