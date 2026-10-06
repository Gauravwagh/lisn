"""Unit tests for Piper / edge-tts helpers that need no model or network."""

import numpy as np
import pytest

from lisn.errors import EngineError, EngineUnavailableError
from lisn.tts.base import Audio
from lisn.tts.edge import EdgeEngine, align_boundaries
from lisn.tts.piper import PiperEngine
from lisn.tts.registry import get_engine


def test_registry_builds_optional_engines():
    assert get_engine("piper").name == "piper"
    assert get_engine("edge").name == "edge"
    with pytest.raises(EngineUnavailableError):
        get_engine("nope")


def test_piper_voice_validation(tmp_path):
    engine = PiperEngine(voices_dir=tmp_path)
    with pytest.raises(EngineError):
        engine.synthesize("hi", "not-a-voice")
    with pytest.raises(EngineError):
        engine.synthesize("  ", "en_US-lessac-medium")
    assert any(v.id == "hi_IN-pratham-medium" and v.language == "hi-IN" for v in engine.voices())


def test_piper_synthesize_with_fake_model(tmp_path, monkeypatch):
    class Chunk:
        sample_rate = 22050
        audio_float_array = np.ones(100, dtype=np.float32)

    class Model:
        def synthesize(self, text, config):
            assert abs(config.length_scale - 1 / 1.5) < 1e-9
            return [Chunk(), Chunk()]

    engine = PiperEngine(voices_dir=tmp_path)
    monkeypatch.setattr(engine, "_voice", lambda voice: Model())
    audio = engine.synthesize("Hello there.", "en_US-lessac-medium", 1.5)
    assert isinstance(audio, Audio) and len(audio.samples) == 200 and audio.timings == ()


def test_edge_align_boundaries():
    boundaries = [("Hello", 0.0, 0.3), ("world", 0.4, 0.8), ("it's", 0.9, 1.1), ("5", 1.2, 1.3)]
    timings = align_boundaries("Hello, world! It's 5.", boundaries)
    assert [t.word for t in timings] == ["Hello,", "world!", "It's", "5."]
    assert timings[0].start == 0.0 and timings[1].end == 0.8 and timings[3].start == 1.2
    assert align_boundaries("x", []) == ()


def test_edge_align_handles_missing():
    timings = align_boundaries("one two three", [("one", 0.0, 0.2)])
    assert [t.start for t in timings] == [0.0, 0.2, 0.2]


def test_edge_validation_and_fallback_voices(monkeypatch):
    engine = EdgeEngine()
    with pytest.raises(EngineError):
        engine.synthesize("", "en-US-AriaNeural")
    with pytest.raises(EngineError):
        engine.synthesize("hi", "bad")

    class FakeEdge:
        @staticmethod
        async def list_voices():
            raise OSError("offline")

    monkeypatch.setattr("lisn.tts.edge._import_edge", lambda: FakeEdge)
    assert any(v.id == "hi-IN-SwaraNeural" for v in engine.voices())


def test_edge_synthesize_with_fake_stream(monkeypatch):
    import io

    import soundfile as sf

    buffer = io.BytesIO()
    sf.write(buffer, np.zeros(2400, dtype=np.float32), 24000, format="WAV")
    wav_bytes = buffer.getvalue()

    class FakeCommunicate:
        def __init__(self, text, voice, rate, boundary):
            assert rate == "+20%" and boundary == "WordBoundary"

        def stream_sync(self):
            yield {"type": "audio", "data": wav_bytes}
            yield {"type": "WordBoundary", "offset": 0, "duration": 2_000_000, "text": "Hello"}
            yield {"type": "WordBoundary", "offset": 3_000_000, "duration": 2_000_000, "text": "there"}

    class FakeEdge:
        Communicate = FakeCommunicate

    monkeypatch.setattr("lisn.tts.edge._import_edge", lambda: FakeEdge)
    audio = EdgeEngine().synthesize("Hello there.", "en-US-AriaNeural", 1.2)
    assert audio.sample_rate == 24000 and len(audio.samples) == 2400
    assert [t.word for t in audio.timings] == ["Hello", "there."]
    assert audio.timings[1].start == pytest.approx(0.3)
