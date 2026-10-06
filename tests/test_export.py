import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from lisn.errors import LisnError
from lisn.export import export_document, render_document
from lisn.export.writers import ffmetadata


def test_render_has_gaps_and_chapters(small_document, fake_engine):
    rendered = render_document(small_document, fake_engine, "fake_voice", 1.0, cache=None)
    assert rendered.sample_rate == 8000
    assert [c.title for c in rendered.chapters] == ["Chapter One", "Chapter Two"]
    assert rendered.chapters[0].start == 0.0
    assert rendered.chapters[0].end == pytest.approx(rendered.chapters[1].start)
    assert rendered.chapters[1].end == pytest.approx(rendered.duration)
    speech_seconds = sum(0.05 * len(s.speech_text.split()) for s in small_document.sentences)
    assert rendered.duration > speech_seconds + 1.0, "gaps should be inserted"


def test_render_progress_and_cache(small_document, fake_engine, tmp_path):
    from lisn.tts.cache import AudioCache

    seen = []
    cache = AudioCache(tmp_path)
    render_document(
        small_document, fake_engine, "fake_voice", 1.0, cache=cache, progress=lambda d, t: seen.append((d, t))
    )
    assert seen[-1] == (len(small_document), len(small_document))
    calls = len(fake_engine.calls)
    render_document(small_document, fake_engine, "fake_voice", 1.0, cache=cache)
    assert len(fake_engine.calls) == calls, "second render should hit the cache"


def test_ffmetadata_format(small_document, fake_engine):
    rendered = render_document(small_document, fake_engine, "fake_voice", 1.0)
    text = ffmetadata(rendered, "A=B;C")
    assert text.startswith(";FFMETADATA1\ntitle=A\\=B\\;C\n")
    assert text.count("[CHAPTER]") == 2 and "TIMEBASE=1/1000" in text


def test_export_wav(small_document, fake_engine, tmp_path):
    rendered = render_document(small_document, fake_engine, "fake_voice", 1.0)
    out = export_document(rendered, tmp_path / "out.wav")
    data, rate = sf.read(str(out))
    assert rate == 8000 and len(data) == len(rendered.samples)


def test_export_bad_format(small_document, fake_engine, tmp_path):
    rendered = render_document(small_document, fake_engine, "fake_voice", 1.0)
    with pytest.raises(LisnError):
        export_document(rendered, tmp_path / "out.ogg")


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg not installed")
@pytest.mark.parametrize("suffix", [".mp3", ".m4b"])
def test_export_with_ffmpeg(small_document, fake_engine, tmp_path, suffix):
    rendered = render_document(small_document, fake_engine, "fake_voice", 1.0)
    out = export_document(rendered, tmp_path / f"book{suffix}", title="Doc")
    assert out.exists() and out.stat().st_size > 1000
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_chapters", "-show_format", str(out)],
        capture_output=True,
        text=True,
        check=True,
    )
    info = json.loads(probe.stdout)
    assert float(info["format"]["duration"]) == pytest.approx(rendered.duration, abs=0.3)
    if suffix == ".m4b":
        assert [c["tags"]["title"] for c in info["chapters"]] == ["Chapter One", "Chapter Two"]


def test_export_missing_ffmpeg(monkeypatch, small_document, fake_engine, tmp_path):
    monkeypatch.setattr("lisn.export.writers.ffmpeg_path", lambda: None)
    rendered = render_document(small_document, fake_engine, "fake_voice", 1.0)
    with pytest.raises(LisnError, match="ffmpeg"):
        export_document(rendered, tmp_path / "x.mp3")


def test_cli_export(tmp_path, monkeypatch, fake_engine):
    from typer.testing import CliRunner

    from lisn import cli
    from lisn.config import Config

    monkeypatch.setattr(cli, "load_config", lambda: Config(voice="fake_voice", engine="fake"))
    monkeypatch.setattr("lisn.tts.registry.get_engine", lambda name: fake_engine)
    monkeypatch.setattr("lisn.paths.user_cache_dir", lambda app: str(tmp_path / "cache"))
    out = tmp_path / "sample.wav"
    result = CliRunner().invoke(cli.app, ["export", str(Path(__file__).parent / "fixtures/sample.md"), "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert out.exists() and "chapter" in result.output
    data, _ = sf.read(str(out))
    assert isinstance(data, np.ndarray) and len(data) > 0
