"""Render an SVG screenshot of the TUI with a fake engine: python docs/make_screenshot.py"""

from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np

from lisn.config import Config
from lisn.extract import extract
from lisn.player.audio import SilentOutput
from lisn.player.engine import Player
from lisn.text.pipeline import build_document
from lisn.tts.base import Audio, TTSEngine, Voice, WordTiming
from lisn.tui.app import LisnApp

HERE = Path(__file__).parent


class SlowFakeEngine(TTSEngine):
    name = "fake"

    def voices(self) -> tuple[Voice, ...]:
        return (Voice("af_heart", "fake", "en-US"),)

    def synthesize(self, text: str, voice: str, speed: float = 1.0) -> Audio:
        words = text.split()
        timings = tuple(WordTiming(w, i * 0.4, (i + 1) * 0.4) for i, w in enumerate(words))
        return Audio(np.zeros(int(8000 * 0.4 * len(words)), dtype=np.float32), 8000, timings)


async def main() -> None:
    document = build_document(extract(str(HERE.parent / "tests/fixtures/sample.md")))
    player = Player(document, SlowFakeEngine(), Config(), output=SilentOutput(), cache=None, start_index=1)
    app = LisnApp(document, player, voices=("af_heart",))
    player._listener = app.player_event
    async with app.run_test(size=(90, 22)) as pilot:
        await pilot.pause(1.6)
        app.save_screenshot(str(HERE / "tui.svg"))
        await pilot.press("q")
    print("wrote", HERE / "tui.svg")


if __name__ == "__main__":
    asyncio.run(main())
