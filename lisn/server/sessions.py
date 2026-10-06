"""One reading session at a time: a Document, a Player, and event fan-out to subscribers."""

from __future__ import annotations

import asyncio
import secrets
import threading
from dataclasses import asdict, dataclass
from typing import Any

from lisn.config import Config
from lisn.errors import LisnError
from lisn.extract import extract
from lisn.extract.base import Extracted
from lisn.extract.text import blocks_from_markdown
from lisn.model import Document
from lisn.player.audio import Output
from lisn.player.engine import Player, PlayerEvent, PlayerState
from lisn.text.pipeline import build_document
from lisn.tts.base import TTSEngine
from lisn.tts.cache import AudioCache


@dataclass(frozen=True)
class SessionInfo:
    id: str
    title: str
    source: str
    sentences: list[dict[str, Any]]
    chapters: list[dict[str, Any]]


def state_payload(state: PlayerState, percent: float) -> dict[str, Any]:
    payload = asdict(state)
    payload["status"] = state.status.value
    payload["percent"] = round(percent, 2)
    payload.pop("sleep_deadline", None)
    return payload


class Session:
    def __init__(self, document: Document, player: Player) -> None:
        self.id = secrets.token_hex(8)
        self.document = document
        self.player = player
        self._subscribers: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []
        self._lock = threading.Lock()

    def info(self) -> SessionInfo:
        return SessionInfo(
            id=self.id,
            title=self.document.title,
            source=self.document.source,
            sentences=[
                {"id": s.id, "index": s.index, "text": s.text, "paragraph": s.paragraph, "chapter": s.chapter}
                for s in self.document.sentences
            ],
            chapters=[
                {"index": c.index, "title": c.title, "start_sentence": c.start_sentence} for c in self.document.chapters
            ],
        )

    def on_event(self, event: PlayerEvent) -> None:
        payload = {"kind": event.kind, **state_payload(event.state, self.player.percent_complete())}
        with self._lock:
            targets = list(self._subscribers)
        for loop, queue in targets:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, payload)
            except RuntimeError:
                self.unsubscribe(queue)

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        with self._lock:
            self._subscribers.append((asyncio.get_running_loop(), queue))
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers = [(loop, q) for loop, q in self._subscribers if q is not queue]

    def close(self) -> None:
        self.player.close()


class SessionManager:
    """Owns the engine and the single active session."""

    def __init__(self, engine: TTSEngine, config: Config, output_factory=None, cache: AudioCache | None = None) -> None:  # type: ignore[no-untyped-def]
        self.engine = engine
        self.config = config
        self.cache = cache
        self._output_factory = output_factory
        self._session: Session | None = None
        self._lock = threading.Lock()

    @property
    def current(self) -> Session | None:
        return self._session

    def get(self, session_id: str) -> Session:
        session = self._session
        if session is None or session.id != session_id:
            raise LisnError("No such session (it may have been replaced by a newer one).")
        return session

    def create(
        self,
        *,
        text: str | None = None,
        url: str | None = None,
        path: str | None = None,
        title: str = "",
        voice: str | None = None,
        speed: float | None = None,
        start_index: int = 0,
        autoplay: bool = True,
    ) -> Session:
        document = self._document(text, url, path, title)
        config = self.config.with_overrides(voice=voice, speed=speed)
        with self._lock:
            self.close_current()
            output: Output | None = self._output_factory() if self._output_factory else None
            player = Player(document, self.engine, config, output=output, cache=self.cache, start_index=start_index)
            session = Session(document, player)
            player._listener = session.on_event
            self._session = session
        player.start()
        if autoplay:
            player.play()
        return session

    def close_current(self) -> None:
        session, self._session = self._session, None
        if session is not None:
            session.close()

    def _document(self, text: str | None, url: str | None, path: str | None, title: str) -> Document:
        if text and text.strip():
            extracted = Extracted(
                title=title or "Browser", source=url or "extension", blocks=blocks_from_markdown(text)
            )
        elif url:
            extracted = extract(url)
        elif path:
            extracted = extract(path)
        else:
            raise LisnError("Provide text, url or path.")
        try:
            return build_document(extracted)
        except ValueError as exc:
            raise LisnError(str(exc)) from exc
