import time

from lisn.config import Config
from lisn.player.audio import SilentOutput
from lisn.player.engine import Player, Status


def wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def make_player(document, engine, events, **kwargs):
    return Player(
        document,
        engine,
        Config(voice="fake_voice", speed=1.0, prefetch=3),
        output=SilentOutput(time_scale=4.0),
        cache=None,
        listener=events.append,
        **kwargs,
    )


def test_plays_through_and_emits_words(small_document, fake_engine):
    events = []
    player = make_player(small_document, fake_engine, events)
    player.start()
    player.play()
    assert wait_for(lambda: player.state.status == Status.FINISHED, timeout=10)
    player.close()
    sentence_events = [e.state.index for e in events if e.kind == "sentence"]
    assert sentence_events == list(range(len(small_document)))
    word_events = [e for e in events if e.kind == "word"]
    assert word_events, "expected word highlight events"
    assert any(e.kind == "finished" for e in events)
    assert player.percent_complete() == 100.0


def test_prefetches_ahead(small_document, fake_engine):
    events = []
    player = make_player(small_document, fake_engine, events)
    player.start()
    player.play()
    assert wait_for(lambda: player.state.status == Status.PLAYING)
    assert wait_for(lambda: len(fake_engine.calls) >= 4)
    player.close()


def test_pause_resume_and_navigation(small_document, fake_engine):
    events = []
    player = make_player(small_document, fake_engine, events)
    player.start()
    player.play()
    assert wait_for(lambda: player.state.status == Status.PLAYING)
    player.pause()
    assert wait_for(lambda: player.state.status == Status.PAUSED)
    position = player.state.position
    time.sleep(0.1)
    assert player.state.position == position
    player.next_sentence()
    assert wait_for(lambda: player.state.index == 1 and player.state.status == Status.PAUSED)
    player.play()
    assert wait_for(lambda: player.state.status == Status.PLAYING)
    player.next_chapter()
    assert wait_for(lambda: player.state.index == 4)
    player.prev_chapter()
    assert wait_for(lambda: player.state.index == 0)
    player.next_paragraph()
    assert wait_for(lambda: player.state.index == 1)
    player.goto_percent(100)
    assert wait_for(lambda: player.state.index == len(small_document) - 1)
    player.stop()
    assert wait_for(lambda: player.state.status == Status.STOPPED)
    player.close()


def test_speed_change_resynthesizes(small_document, fake_engine):
    events = []
    player = make_player(small_document, fake_engine, events)
    player.start()
    player.play()
    assert wait_for(lambda: player.state.status == Status.PLAYING)
    player.set_speed(1.5)
    assert wait_for(lambda: player.state.speed == 1.5 and player.state.status == Status.PLAYING)
    assert any(abs(call[2] - 1.5) < 1e-9 for call in fake_engine.calls)
    player.speed_up()
    assert wait_for(lambda: abs(player.state.speed - 1.6) < 1e-9)
    player.close()


def test_start_index_and_volume(small_document, fake_engine):
    events = []
    player = make_player(small_document, fake_engine, events, start_index=3)
    assert player.state.index == 3
    player.start()
    player.volume_up()
    assert wait_for(lambda: abs(player.state.volume - 1.1) < 1e-9)
    player.close()


def test_engine_error_is_reported(small_document, fake_engine):
    def boom(*_args, **_kwargs):
        raise RuntimeError("no model")

    fake_engine.synthesize = boom  # type: ignore[method-assign]
    events = []
    player = make_player(small_document, fake_engine, events)
    player.start()
    player.play()
    assert wait_for(lambda: player.state.status == Status.ERROR)
    assert "no model" in player.state.error
    player.close()


def test_search_sleep_and_estimate(small_document, fake_engine):
    events = []
    player = make_player(small_document, fake_engine, events)
    player.start()
    player.play()
    assert wait_for(lambda: player.state.status == Status.PLAYING)
    assert player.search("Final") == 5
    assert wait_for(lambda: player.state.index == 5)
    assert player.search("nope") is None
    player.set_sleep_timer(0.0001)
    assert wait_for(lambda: player.state.status == Status.PAUSED)
    assert player.sleep_remaining() is None
    player.set_sleep_timer(10)
    assert wait_for(lambda: player.sleep_remaining() is not None)
    player.set_sleep_timer(None)
    elapsed, total = player.time_estimate()
    assert total > 0 and 0 <= elapsed <= total + 1
    player.close()


def test_pause_while_loading_parks_audio(small_document, fake_engine):
    events = []
    player = make_player(small_document, fake_engine, events)
    player.start()
    player.play()
    player.pause()  # arrives while the first sentence is still loading
    assert wait_for(lambda: player.state.status == Status.PAUSED and player.state.duration > 0)
    time.sleep(0.1)
    assert player.state.status == Status.PAUSED and player.state.index == 0
    player.play()
    assert wait_for(lambda: player.state.status == Status.PLAYING)
    player.close()
