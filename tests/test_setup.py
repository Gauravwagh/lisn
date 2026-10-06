from pathlib import Path

from typer.testing import CliRunner

from lisn import cli
from lisn.setup_cli import install_skill, known_clis, register_mcp, remove_skill, skill_source, unregister_mcp


def test_skill_source_has_frontmatter():
    text = skill_source()
    assert text.startswith("---\nname: lisn\n") and "read_aloud" in text


def test_install_and_remove_skill(tmp_path):
    clis = known_clis(home=tmp_path)
    assert [c.name for c in clis] == ["claude", "codex", "gemini"]
    target = install_skill(clis[0])
    assert target == tmp_path / ".claude" / "skills" / "lisn"
    assert (target / "SKILL.md").read_text().startswith("---")
    assert remove_skill(clis[0]) is True and remove_skill(clis[0]) is False


def test_register_mcp_outcomes(tmp_path, monkeypatch):
    cli_def = known_clis(home=tmp_path)[1]
    monkeypatch.setattr("lisn.setup_cli.shutil.which", lambda name: None)
    assert "not found" in register_mcp(cli_def)
    monkeypatch.setattr("lisn.setup_cli.shutil.which", lambda name: "/usr/bin/codex")

    class Result:
        def __init__(self, code, err=""):
            self.returncode, self.stderr, self.stdout = code, err, ""

    calls = []
    assert "registered" in register_mcp(cli_def, runner=lambda cmd, **k: calls.append(cmd) or Result(0))
    assert calls[0][:3] == ["codex", "mcp", "add"]
    assert "already" in register_mcp(cli_def, runner=lambda cmd, **k: Result(1, "error: server already exists"))
    assert "failed" in register_mcp(cli_def, runner=lambda cmd, **k: Result(2, "boom"))
    assert "removed" in unregister_mcp(cli_def, runner=lambda cmd, **k: Result(0))


def test_setup_command(tmp_path, monkeypatch):
    monkeypatch.setattr("lisn.setup_cli.Path.home", lambda: tmp_path)
    result = CliRunner().invoke(cli.app, ["setup", "--codex", "--no-mcp"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".codex" / "skills" / "lisn" / "SKILL.md").exists()
    assert not (tmp_path / ".claude" / "skills").exists()
    result = CliRunner().invoke(cli.app, ["setup", "--codex", "--no-mcp", "--uninstall"])
    assert result.exit_code == 0 and "removed" in result.output
    assert not Path(tmp_path / ".codex" / "skills" / "lisn").exists()
