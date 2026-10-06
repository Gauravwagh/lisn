import pytest

from lisn.config import Config
from lisn.mcp.server import build_server
from lisn.player.audio import SilentOutput
from lisn.server.sessions import SessionManager

pytestmark = pytest.mark.asyncio


@pytest.fixture
def manager(fake_engine):
    created = SessionManager(fake_engine, Config(voice="fake_voice"), output_factory=lambda: SilentOutput(time_scale=4))
    yield created
    created.close_current()


async def test_mcp_tools(manager, tmp_path):
    server = build_server(manager)
    names = {tool.name for tool in await server.list_tools()}
    assert {"read_aloud", "pause", "resume", "stop", "status", "skip", "set_speed", "export_audio"} <= names

    idle = await server.call_tool("status", {})
    assert _payload(idle)["status"] == "idle"

    started = _payload(await server.call_tool("read_aloud", {"text": "One two. Three four. Five six."}))
    assert started["sentences"] == 3
    paused = _payload(await server.call_tool("pause", {}))
    assert paused["status"] in ("paused", "finished", "loading")
    skipped = _payload(await server.call_tool("skip", {"sentences": 1}))
    assert skipped["index"] >= 1
    faster = _payload(await server.call_tool("set_speed", {"speed": 2.0}))
    assert faster["speed"] == 2.0
    resumed = _payload(await server.call_tool("resume", {}))
    assert "sentence" in resumed
    stopped = _payload(await server.call_tool("stop", {}))
    assert stopped["status"] == "stopped"

    out = tmp_path / "out.wav"
    exported = _payload(await server.call_tool("export_audio", {"text": "Hello.", "out_path": str(out)}))
    assert out.exists() and exported["chapters"] == 1


def _payload(result):
    """MCP 2.x returns (content, structured) or a CallToolResult; unwrap to the dict."""
    if isinstance(result, tuple):
        return result[1] if isinstance(result[1], dict) else result[1].get("result", result[1])
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        return structured.get("result", structured)
    import json

    return json.loads(result.content[0].text)
