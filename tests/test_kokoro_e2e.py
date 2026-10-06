"""End-to-end: real Kokoro model -> WAV file. Skipped unless kokoro is importable."""

from pathlib import Path

import pytest

kokoro = pytest.importorskip("kokoro")


@pytest.mark.slow
def test_sample_to_wav(tmp_path: Path):
    import soundfile as sf
    from typer.testing import CliRunner

    from lisn.cli import app

    out = tmp_path / "sample.wav"
    result = CliRunner().invoke(app, ["sample", "Hello there. This is a test.", "--voice", "af_heart", "-o", str(out)])
    assert result.exit_code == 0, result.output
    data, rate = sf.read(str(out))
    assert rate == 24000
    assert len(data) / rate > 1.0


@pytest.mark.slow
def test_kokoro_word_timings_align_with_words():
    from lisn.tts.kokoro import KokoroEngine

    engine = KokoroEngine()
    audio = engine.synthesize("The quick brown fox jumps over the lazy dog.", "af_heart", 1.0)
    assert audio.sample_rate == 24000
    assert [t.word for t in audio.timings] == "The quick brown fox jumps over the lazy dog.".split()
    starts = [t.start for t in audio.timings]
    assert starts == sorted(starts)
    assert audio.timings[-1].end <= audio.duration + 0.05
