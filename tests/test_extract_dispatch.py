import pytest

from lisn.errors import ExtractionError
from lisn.extract import extract, extract_clipboard, extract_stdin


def test_directory_rejected(tmp_path):
    with pytest.raises(ExtractionError):
        extract(str(tmp_path))


def test_stdin_empty(monkeypatch):
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO("  "))
    with pytest.raises(ExtractionError):
        extract_stdin()


def test_stdin_markdown(monkeypatch):
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO("# T\n\nbody"))
    extracted = extract("-")
    assert extracted.blocks[0].text == "T" and extracted.source == "stdin"


def test_clipboard(monkeypatch):
    import types

    fake = types.SimpleNamespace(paste=lambda: "copied text", PyperclipException=RuntimeError)
    monkeypatch.setitem(__import__("sys").modules, "pyperclip", fake)
    assert extract_clipboard().blocks[0].text == "copied text"
    fake_empty = types.SimpleNamespace(paste=lambda: "", PyperclipException=RuntimeError)
    monkeypatch.setitem(__import__("sys").modules, "pyperclip", fake_empty)
    with pytest.raises(ExtractionError):
        extract_clipboard()
