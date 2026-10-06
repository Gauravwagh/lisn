"""Start the local server: `lisn serve`."""

from __future__ import annotations

from lisn.config import Config
from lisn.errors import LisnError
from lisn.server.api import DEFAULT_PORT, create_app
from lisn.server.auth import ensure_token
from lisn.server.sessions import SessionManager
from lisn.tts.cache import AudioCache
from lisn.tts.registry import get_engine


def serve(config: Config, port: int = DEFAULT_PORT, host: str = "127.0.0.1", warm: bool = True) -> None:
    try:
        import uvicorn
    except ImportError as exc:
        raise LisnError("The server needs 'pip install \"lisn[server]\"' (fastapi + uvicorn).") from exc
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise LisnError("lisn serve only binds to localhost; remote access is not supported.")
    config, token = ensure_token(config)
    engine = get_engine(config.engine)
    if warm:
        engine.warm_up()
    manager = SessionManager(engine, config, cache=AudioCache())
    app = create_app(manager, token)
    try:
        uvicorn.run(app, host=host, port=port, log_level="warning")
    finally:
        manager.close_current()
