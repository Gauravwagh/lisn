"""`lisn mcp`: stdio MCP server with read_aloud / pause / resume / stop / status / export_audio.

Audio plays on this machine's speakers (the agent runs locally). One session at a time.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from lisn.config import Config
from lisn.errors import LisnError
from lisn.server.sessions import SessionManager, state_payload
from lisn.tts.cache import AudioCache
from lisn.tts.registry import get_engine


def build_server(manager: SessionManager):  # type: ignore[no-untyped-def]
    try:
        from mcp.server.mcpserver import MCPServer
    except ImportError as exc:
        raise LisnError("The MCP server needs 'pip install \"lisn[mcp]\"'.") from exc

    server = MCPServer(
        name="lisn",
        instructions=(
            "lisn reads text aloud on the user's machine with a local TTS voice. Use read_aloud to start, "
            "pause/resume/stop to control playback, status to check progress, export_audio to write an mp3/m4b."
        ),
    )

    @server.tool(description="Read text, a local file (pdf/docx/epub/md/txt) or a URL aloud. Returns the session id.")
    def read_aloud(
        text: str | None = None,
        path: str | None = None,
        url: str | None = None,
        voice: str | None = None,
        speed: float | None = None,
    ) -> dict[str, Any]:
        session = manager.create(text=text, url=url, path=path, voice=voice, speed=speed)
        return {"session_id": session.id, "title": session.document.title, "sentences": len(session.document)}

    @server.tool(description="Pause playback.")
    def pause() -> dict[str, Any]:
        return _control("pause")

    @server.tool(description="Resume playback.")
    def resume() -> dict[str, Any]:
        return _control("play")

    @server.tool(description="Stop playback and close the session.")
    def stop() -> dict[str, Any]:
        session = manager.current
        if session is None:
            return {"ok": True, "status": "idle"}
        manager.close_current()
        return {"ok": True, "status": "stopped"}

    @server.tool(description="Skip forward (sentences > 0) or back (sentences < 0).")
    def skip(sentences: int = 1) -> dict[str, Any]:
        session = _session()
        session.player.goto(session.player.state.index + int(sentences))
        return _settled(session)

    @server.tool(description="Change the speech rate (0.5–3.0).")
    def set_speed(speed: float) -> dict[str, Any]:
        session = _session()
        session.player.set_speed(speed)
        return _settled(session)

    @server.tool(description="Current playback status: sentence index, text, percent complete.")
    def status() -> dict[str, Any]:
        session = manager.current
        if session is None:
            return {"status": "idle"}
        return _status(session)

    @server.tool(description="Export text, a file or a URL to an audio file (.mp3, .m4b with chapters, or .wav).")
    def export_audio(
        out_path: str,
        text: str | None = None,
        path: str | None = None,
        url: str | None = None,
        voice: str | None = None,
        speed: float | None = None,
    ) -> dict[str, Any]:
        from lisn.export import export_document, render_document

        document = manager._document(text, url, path, "")
        config = manager.config.with_overrides(voice=voice, speed=speed)
        rendered = render_document(document, manager.engine, config.voice, config.speed, manager.cache)
        out = export_document(rendered, Path(out_path).expanduser(), document.title)
        return {"path": str(out), "duration_seconds": round(rendered.duration, 1), "chapters": len(rendered.chapters)}

    def _session():  # type: ignore[no-untyped-def]
        session = manager.current
        if session is None:
            raise LisnError("Nothing is playing. Call read_aloud first.")
        return session

    def _control(action: str) -> dict[str, Any]:
        session = _session()
        getattr(session.player, action)()
        return _settled(session)

    def _settled(session) -> dict[str, Any]:  # type: ignore[no-untyped-def]
        time.sleep(0.08)  # let the player thread apply the queued command before reporting
        return _status(session)

    def _status(session) -> dict[str, Any]:  # type: ignore[no-untyped-def]
        state = session.player.state
        payload = state_payload(state, session.player.percent_complete())
        payload["sentence"] = session.document.sentences[state.index].text
        payload["title"] = session.document.title
        return payload

    return server


def run_mcp(config: Config) -> None:
    import threading

    engine = get_engine(config.engine)
    threading.Thread(target=_quiet_warm_up, args=(engine,), name="lisn-warmup", daemon=True).start()
    manager = SessionManager(engine, config, cache=AudioCache())
    server = build_server(manager)
    try:
        server.run(transport="stdio")
    finally:
        manager.close_current()


def _quiet_warm_up(engine) -> None:  # type: ignore[no-untyped-def]
    try:
        engine.warm_up()
    except LisnError:
        pass  # surfaces with context on the first read_aloud call
