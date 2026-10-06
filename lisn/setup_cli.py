"""`lisn setup`: install the agent skill and register the MCP server with coding-agent CLIs."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from lisn.errors import LisnError

SKILL_NAME = "lisn"


@dataclass(frozen=True)
class AgentCli:
    name: str
    binary: str
    skills_dir: Path
    mcp_add: tuple[str, ...]
    mcp_remove: tuple[str, ...]


def known_clis(home: Path | None = None) -> tuple[AgentCli, ...]:
    base = home or Path.home()
    return (
        AgentCli(
            "claude",
            "claude",
            base / ".claude" / "skills",
            ("claude", "mcp", "add", "--scope", "user", "lisn", "--", "lisn", "mcp"),
            ("claude", "mcp", "remove", "--scope", "user", "lisn"),
        ),
        AgentCli(
            "codex",
            "codex",
            base / ".codex" / "skills",
            ("codex", "mcp", "add", "lisn", "--", "lisn", "mcp"),
            ("codex", "mcp", "remove", "lisn"),
        ),
        AgentCli(
            "gemini",
            "gemini",
            base / ".gemini" / "skills",
            ("gemini", "mcp", "add", "--scope", "user", "lisn", "lisn", "mcp"),
            ("gemini", "mcp", "remove", "--scope", "user", "lisn"),
        ),
    )


def skill_source() -> str:
    try:
        return resources.files("lisn.assets.skill").joinpath("SKILL.md").read_text(encoding="utf-8")
    except (FileNotFoundError, OSError) as exc:
        raise LisnError(f"Bundled SKILL.md is missing: {exc}") from exc


def install_skill(cli: AgentCli) -> Path:
    target = cli.skills_dir / SKILL_NAME
    try:
        target.mkdir(parents=True, exist_ok=True)
        (target / "SKILL.md").write_text(skill_source(), encoding="utf-8")
    except OSError as exc:
        raise LisnError(f"Could not write the skill to {target}: {exc}") from exc
    return target


def remove_skill(cli: AgentCli) -> bool:
    target = cli.skills_dir / SKILL_NAME
    if not target.exists():
        return False
    shutil.rmtree(target, ignore_errors=True)
    return True


def register_mcp(cli: AgentCli, runner=subprocess.run) -> str:  # type: ignore[no-untyped-def]
    """Run the CLI's own `mcp add`. Returns a short human message."""
    if shutil.which(cli.binary) is None:
        return f"{cli.name}: CLI not found on PATH, skipped MCP registration"
    result = runner(list(cli.mcp_add), capture_output=True, text=True, timeout=60)
    if result.returncode == 0:
        return f"{cli.name}: MCP server 'lisn' registered"
    detail = (result.stderr or result.stdout or "").strip().splitlines()
    message = detail[-1] if detail else f"exit code {result.returncode}"
    if "already exists" in message.lower():
        return f"{cli.name}: MCP server 'lisn' was already registered"
    return f"{cli.name}: MCP registration failed ({message})"


def unregister_mcp(cli: AgentCli, runner=subprocess.run) -> str:  # type: ignore[no-untyped-def]
    if shutil.which(cli.binary) is None:
        return f"{cli.name}: CLI not found on PATH, skipped"
    result = runner(list(cli.mcp_remove), capture_output=True, text=True, timeout=60)
    return f"{cli.name}: MCP server removed" if result.returncode == 0 else f"{cli.name}: nothing to remove"
