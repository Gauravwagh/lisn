"""FastAPI app: bound to 127.0.0.1, bearer-token auth, SSE events for live highlighting."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from lisn import __version__
from lisn.errors import LisnError
from lisn.server.sessions import SessionManager, state_payload
from lisn.tts.base import MAX_SPEED, MIN_SPEED

DEFAULT_PORT = 7391
ACTIONS = {
    "play",
    "pause",
    "toggle",
    "stop",
    "next",
    "prev",
    "next_paragraph",
    "prev_paragraph",
    "next_chapter",
    "prev_chapter",
    "repeat",
    "goto",
    "goto_percent",
    "speed",
    "volume",
    "voice",
    "search",
}


class SessionRequest(BaseModel):
    text: str | None = Field(default=None, max_length=5_000_000)
    url: str | None = Field(default=None, max_length=4096)
    path: str | None = Field(default=None, max_length=4096)
    title: str = Field(default="", max_length=500)
    voice: str | None = Field(default=None, max_length=100)
    speed: float | None = Field(default=None, ge=MIN_SPEED, le=MAX_SPEED)
    start_index: int = Field(default=0, ge=0)
    autoplay: bool = True


class ControlRequest(BaseModel):
    action: str = Field(max_length=32)
    value: float | str | None = None


class ExportRequest(BaseModel):
    text: str | None = Field(default=None, max_length=5_000_000)
    url: str | None = Field(default=None, max_length=4096)
    path: str | None = Field(default=None, max_length=4096)
    out: str = Field(max_length=4096)
    voice: str | None = None
    speed: float | None = Field(default=None, ge=MIN_SPEED, le=MAX_SPEED)


def create_app(manager: SessionManager, token: str) -> FastAPI:
    app = FastAPI(title="lisn", version=__version__, docs_url=None, redoc_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^(chrome-extension|moz-extension|safari-web-extension)://.*$|^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_methods=["*"],
        allow_headers=["*"],
    )

    async def require_token(request: Request, token_query: str | None = Query(default=None, alias="token")) -> None:
        header = request.headers.get("authorization", "")
        presented = header[7:] if header.lower().startswith("bearer ") else token_query
        if not presented or not _constant_equal(presented, token):
            raise HTTPException(status_code=401, detail="Invalid or missing token.")

    auth = Depends(require_token)

    @app.exception_handler(LisnError)
    async def _lisn_error(_request: Request, exc: LisnError):  # type: ignore[no-untyped-def]
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "version": __version__, "engine": manager.engine.name, "voice": manager.config.voice}

    @app.get("/voices", dependencies=[auth])
    async def voices() -> list[dict[str, str]]:
        return [asdict(v) for v in manager.engine.voices()]

    @app.post("/session", dependencies=[auth])
    async def create_session(body: SessionRequest) -> dict[str, Any]:
        session = await asyncio.to_thread(
            manager.create,
            text=body.text,
            url=body.url,
            path=body.path,
            title=body.title,
            voice=body.voice,
            speed=body.speed,
            start_index=body.start_index,
            autoplay=body.autoplay,
        )
        return asdict(session.info())

    @app.get("/session", dependencies=[auth])
    async def current_session() -> dict[str, Any]:
        session = manager.current
        if session is None:
            raise HTTPException(status_code=404, detail="No active session.")
        return {
            **asdict(session.info()),
            "state": state_payload(session.player.state, session.player.percent_complete()),
        }

    @app.get("/session/{session_id}/state", dependencies=[auth])
    async def session_state(session_id: str) -> dict[str, Any]:
        session = manager.get(session_id)
        return state_payload(session.player.state, session.player.percent_complete())

    @app.post("/session/{session_id}/control", dependencies=[auth])
    async def control(session_id: str, body: ControlRequest) -> dict[str, Any]:
        session = manager.get(session_id)
        if body.action not in ACTIONS:
            raise HTTPException(status_code=400, detail=f"Unknown action '{body.action}'.")
        _dispatch(session.player, body.action, body.value)
        await asyncio.sleep(0.05)  # let the player thread apply the command
        return state_payload(session.player.state, session.player.percent_complete())

    @app.delete("/session/{session_id}", dependencies=[auth])
    async def delete_session(session_id: str) -> dict[str, bool]:
        manager.get(session_id)
        await asyncio.to_thread(manager.close_current)
        return {"ok": True}

    @app.get("/session/{session_id}/events", dependencies=[auth])
    async def events(session_id: str) -> StreamingResponse:
        session = manager.get(session_id)
        queue = session.subscribe()

        async def stream() -> AsyncIterator[str]:
            try:
                yield _sse({"kind": "state", **state_payload(session.player.state, session.player.percent_complete())})
                while True:
                    try:
                        payload = await asyncio.wait_for(queue.get(), timeout=15)
                    except TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    yield _sse(payload)
                    if payload.get("kind") == "finished":
                        break
            finally:
                session.unsubscribe(queue)

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @app.post("/export", dependencies=[auth])
    async def export(body: ExportRequest) -> dict[str, Any]:
        from lisn.export import export_document, render_document

        document = await asyncio.to_thread(manager._document, body.text, body.url, body.path, "")
        config = manager.config.with_overrides(voice=body.voice, speed=body.speed)
        rendered = await asyncio.to_thread(
            render_document, document, manager.engine, config.voice, config.speed, manager.cache
        )
        out = await asyncio.to_thread(export_document, rendered, Path(body.out).expanduser(), document.title)
        return {"path": str(out), "duration": rendered.duration, "chapters": len(rendered.chapters)}

    return app


def _dispatch(player, action: str, value: float | str | None) -> None:  # type: ignore[no-untyped-def]
    simple = {
        "play": player.play,
        "pause": player.pause,
        "toggle": player.toggle,
        "stop": player.stop,
        "next": player.next_sentence,
        "prev": player.prev_sentence,
        "next_paragraph": player.next_paragraph,
        "prev_paragraph": player.prev_paragraph,
        "next_chapter": player.next_chapter,
        "prev_chapter": player.prev_chapter,
        "repeat": player.repeat,
    }
    if action in simple:
        simple[action]()
        return
    if value is None:
        raise HTTPException(status_code=400, detail=f"'{action}' needs a value.")
    try:
        if action == "goto":
            player.goto(int(float(value)))
        elif action == "goto_percent":
            player.goto_percent(float(value))
        elif action == "speed":
            player.set_speed(float(value))
        elif action == "volume":
            player.set_volume(float(value))
        elif action == "voice":
            player.set_voice(str(value))
        elif action == "search":
            player.search(str(value))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Bad value for '{action}': {value!r}") from exc


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _constant_equal(a: str, b: str) -> bool:
    import hmac

    return hmac.compare_digest(a.encode(), b.encode())
