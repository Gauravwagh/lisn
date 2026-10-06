from pathlib import Path

import pytest
from typer.testing import CliRunner

from lisn import cli
from lisn.config import Config

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path, fake_engine):
    """Route config/cache to tmp, use the fake engine and silent output."""
    monkeypatch.setattr(cli, "load_config", lambda: Config(voice="fake_voice", engine="fake"))
    monkeypatch.setattr("lisn.tts.registry.get_engine", lambda name: fake_engine)
    monkeypatch.setattr("lisn.paths.user_config_dir", lambda app: str(tmp_path / "config"))
    monkeypatch.setattr("lisn.paths.user_cache_dir", lambda app: str(tmp_path / "cache"))
    monkeypatch.setattr("lisn.paths.user_data_dir", lambda app: str(tmp_path / "data"))
    return fake_engine


def run(*args: str, input: str | None = None):
    return CliRunner().invoke(cli.app, list(args), input=input)


def test_version():
    result = run("--version")
    assert result.exit_code == 0 and "lisn" in result.output


def test_read_markdown_headless(isolated):
    result = run("read", str(FIXTURES / "sample.md"), "--no-tui", "--no-audio", "--no-cache")
    assert result.exit_code == 0, result.output
    assert "finished" in result.output
    assert isolated.calls[0][0] == "The Little Reader"
    assert len(isolated.calls) == 10


def test_read_stdin_with_from_percent(isolated):
    result = run(
        "read", "-", "--no-tui", "--no-audio", "--from", "50%", input="One two. Three four. Five six. Seven eight."
    )
    assert result.exit_code == 0, result.output
    first_spoken = isolated.calls[0][0]
    assert first_spoken.startswith(("Three", "Five"))


def test_read_chapter_option(isolated):
    result = run("read", str(FIXTURES / "sample.md"), "--no-tui", "--no-audio", "--chapter", "2")
    assert result.exit_code == 0, result.output
    assert isolated.calls[0][0] == "Part Two"


def test_history_and_bookmarks_commands(isolated):
    run("read", str(FIXTURES / "sample.md"), "--no-tui", "--no-audio", "--no-cache")
    result = run("history")
    assert result.exit_code == 0 and "The Little Reader" in result.output
    assert run("bookmarks").exit_code == 0
    assert run("bookmarks", "nope.txt").exit_code != 0
    assert run("history", "--forget", str(FIXTURES / "sample.md")).exit_code == 0
    assert run("history", "--forget", "zzz").exit_code != 0
    assert "No history" in run("history").output


def test_read_resumes_and_no_resume(isolated, monkeypatch):
    from lisn.player.state import StateStore

    store = StateStore()
    from lisn.extract import extract
    from lisn.player.state import document_key
    from lisn.text.pipeline import build_document

    doc = build_document(extract(str(FIXTURES / "sample.md")))
    store.save_position(document_key(doc), doc, 4, 40.0)
    run("read", str(FIXTURES / "sample.md"), "--no-tui", "--no-audio", "--no-cache")
    assert isolated.calls[0][0] == doc.sentences[4].speech_text
    isolated.calls.clear()
    run("read", str(FIXTURES / "sample.md"), "--no-tui", "--no-audio", "--no-cache", "--no-resume")
    assert isolated.calls[0][0] == doc.sentences[0].speech_text


def test_read_bad_chapter_and_percent():
    assert run("read", str(FIXTURES / "sample.md"), "--no-audio", "--chapter", "9").exit_code != 0
    assert run("read", str(FIXTURES / "sample.md"), "--no-audio", "--from", "lots").exit_code != 0
    assert run("read", "--no-audio").exit_code != 0
    assert run("read", "missing.txt", "--no-audio").exit_code != 0


def test_sample_to_wav(tmp_path, isolated):
    out = tmp_path / "s.wav"
    result = run("sample", "Hello world.", "-o", str(out))
    assert result.exit_code == 0, result.output
    assert out.exists() and out.stat().st_size > 44


def test_sample_plays_silently(isolated):
    assert run("sample", "Hi there.", "--no-audio").exit_code == 0


def test_voices_lists_fake_engine():
    result = run("voices", "--engine", "fake")
    assert result.exit_code == 0 and "fake_voice" in result.output


def test_config_commands(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "load_config", lambda: Config())
    assert run("config", "show").exit_code == 0
    assert run("config", "path").exit_code == 0
    assert run("config", "get", "voice").output.strip() == "af_heart"
    saved = run("config", "set", "voice", "am_michael", "speed=1.3")
    assert saved.exit_code == 0, saved.output
    assert run("config", "set", "voice").exit_code != 0
    assert run("config", "set", "speed=9").exit_code != 0


def test_cache_command():
    assert run("cache").exit_code == 0
    assert run("cache", "--clear").exit_code == 0


def test_parse_assignments():
    assert cli._parse_assignments(["a=1", "b", "2"]) == [("a", "1"), ("b", "2")]
