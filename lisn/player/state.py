"""Persistent reading state in SQLite: last position per document, history, bookmarks.

Documents are keyed by a fingerprint: the sha256 of the file bytes for files, the URL for
web sources, and the sha256 of the text for stdin/clipboard. Reopening the same content
resumes where you left off even if the file was moved.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from lisn.errors import LisnError
from lisn.model import Document
from lisn.paths import state_db

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    key TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    source TEXT NOT NULL,
    sentence_id TEXT NOT NULL,
    sentence_index INTEGER NOT NULL,
    total_sentences INTEGER NOT NULL,
    percent REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS bookmarks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_key TEXT NOT NULL,
    sentence_id TEXT NOT NULL,
    sentence_index INTEGER NOT NULL,
    excerpt TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS bookmarks_doc ON bookmarks(doc_key);
"""


@dataclass(frozen=True)
class Position:
    key: str
    title: str
    source: str
    sentence_id: str
    sentence_index: int
    total_sentences: int
    percent: float
    updated_at: float


@dataclass(frozen=True)
class Bookmark:
    id: int
    doc_key: str
    sentence_id: str
    sentence_index: int
    excerpt: str
    created_at: float


def document_key(document: Document) -> str:
    """Fingerprint for resume/history. Files hash their bytes, URLs are their own key."""
    source = document.source
    if source.startswith(("http://", "https://")):
        return source
    path = Path(source)
    if path.is_file():
        try:
            return "file:" + hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            pass
    text = "\n".join(s.text for s in document.sentences)
    return "text:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


class StateStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or state_db()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self):  # type: ignore[no-untyped-def]
        try:
            conn = sqlite3.connect(str(self.path), timeout=5)
        except sqlite3.Error as exc:
            raise LisnError(f"Cannot open state database {self.path}: {exc}") from exc
        try:
            conn.row_factory = sqlite3.Row
            yield conn
            conn.commit()
        except sqlite3.Error as exc:
            conn.rollback()
            raise LisnError(f"State database error: {exc}") from exc
        finally:
            conn.close()

    # ---- positions ----------------------------------------------------------------

    def save_position(self, key: str, document: Document, sentence_index: int, percent: float) -> Position:
        index = max(0, min(sentence_index, len(document.sentences) - 1))
        position = Position(
            key=key,
            title=document.title,
            source=document.source,
            sentence_id=document.sentences[index].id,
            sentence_index=index,
            total_sentences=len(document.sentences),
            percent=max(0.0, min(100.0, percent)),
            updated_at=time.time(),
        )
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO documents VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET "
                "title=excluded.title, source=excluded.source, sentence_id=excluded.sentence_id, "
                "sentence_index=excluded.sentence_index, total_sentences=excluded.total_sentences, "
                "percent=excluded.percent, updated_at=excluded.updated_at",
                (
                    position.key,
                    position.title,
                    position.source,
                    position.sentence_id,
                    position.sentence_index,
                    position.total_sentences,
                    position.percent,
                    position.updated_at,
                ),
            )
        return position

    def load_position(self, key: str) -> Position | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM documents WHERE key = ?", (key,)).fetchone()
        return _position(row) if row else None

    def resume_index(self, key: str, document: Document) -> int:
        """Where to resume: by sentence id first, falling back to the saved index."""
        saved = self.load_position(key)
        if saved is None or saved.percent >= 99.5:
            return 0
        by_id = document.index_of_id(saved.sentence_id)
        if by_id is not None:
            return by_id
        return max(0, min(saved.sentence_index, len(document.sentences) - 1))

    def history(self, limit: int = 20) -> tuple[Position, ...]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM documents ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
        return tuple(_position(row) for row in rows)

    def forget(self, key: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM documents WHERE key = ?", (key,))
            conn.execute("DELETE FROM bookmarks WHERE doc_key = ?", (key,))

    # ---- bookmarks ----------------------------------------------------------------

    def add_bookmark(self, key: str, document: Document, sentence_index: int) -> Bookmark:
        sentence = document.sentences[max(0, min(sentence_index, len(document.sentences) - 1))]
        created = time.time()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO bookmarks (doc_key, sentence_id, sentence_index, excerpt, created_at) VALUES (?,?,?,?,?)",
                (key, sentence.id, sentence.index, sentence.text[:120], created),
            )
            bookmark_id = int(cursor.lastrowid or 0)
        return Bookmark(bookmark_id, key, sentence.id, sentence.index, sentence.text[:120], created)

    def bookmarks(self, key: str | None = None, limit: int = 50) -> tuple[Bookmark, ...]:
        query = "SELECT * FROM bookmarks"
        params: tuple = ()
        if key is not None:
            query += " WHERE doc_key = ?"
            params = (key,)
        query += " ORDER BY created_at DESC LIMIT ?"
        with self._connect() as conn:
            rows = conn.execute(query, (*params, limit)).fetchall()
        return tuple(
            Bookmark(
                row["id"], row["doc_key"], row["sentence_id"], row["sentence_index"], row["excerpt"], row["created_at"]
            )
            for row in rows
        )

    def delete_bookmark(self, bookmark_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM bookmarks WHERE id = ?", (bookmark_id,))


def _position(row: sqlite3.Row) -> Position:
    return Position(
        key=row["key"],
        title=row["title"],
        source=row["source"],
        sentence_id=row["sentence_id"],
        sentence_index=row["sentence_index"],
        total_sentences=row["total_sentences"],
        percent=row["percent"],
        updated_at=row["updated_at"],
    )
