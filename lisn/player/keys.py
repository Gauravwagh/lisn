"""Minimal cross-platform raw keyboard reader for headless mode (no curses, no Textual).

Yields key names: single characters, "space", "enter", "backspace", "escape", "left",
"right", "up", "down". Unix uses termios cbreak mode; Windows uses msvcrt.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager

_ARROWS = {"A": "up", "B": "down", "C": "right", "D": "left"}
_WIN_ARROWS = {"H": "up", "P": "down", "M": "right", "K": "left"}


def is_interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


@contextmanager
def raw_terminal():  # type: ignore[no-untyped-def]
    """Put the terminal in cbreak mode (Unix) for the duration of the block."""
    if os.name == "nt" or not sys.stdin.isatty():
        yield
        return
    import termios
    import tty

    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def read_key(timeout: float = 0.1) -> str | None:
    """Return the next key name, or None if nothing arrived within `timeout` seconds."""
    if os.name == "nt":
        return _read_key_windows(timeout)
    return _read_key_unix(timeout)


def read_line(prompt_echo=None) -> str:  # type: ignore[no-untyped-def]
    """Read characters until Enter; Escape cancels and returns ''. Calls prompt_echo(buffer)."""
    buffer = ""
    while True:
        key = read_key(timeout=0.5)
        if key is None:
            continue
        if key == "enter":
            return buffer
        if key == "escape":
            return ""
        if key == "backspace":
            buffer = buffer[:-1]
        elif len(key) == 1:
            buffer += key
        if prompt_echo is not None:
            prompt_echo(buffer)


def _read_key_unix(timeout: float) -> str | None:
    import select

    ready, _, _ = select.select([sys.stdin], [], [], timeout)
    if not ready:
        return None
    char = os.read(sys.stdin.fileno(), 1).decode("utf-8", errors="ignore")
    if char == "\x1b":
        ready, _, _ = select.select([sys.stdin], [], [], 0.05)
        if not ready:
            return "escape"
        seq = os.read(sys.stdin.fileno(), 2).decode("utf-8", errors="ignore")
        if len(seq) == 2 and seq[0] == "[" and seq[1] in _ARROWS:
            return _ARROWS[seq[1]]
        return "escape"
    return _name(char)


def _read_key_windows(timeout: float) -> str | None:
    import msvcrt
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if msvcrt.kbhit():
            char = msvcrt.getwch()
            if char in ("\x00", "\xe0"):
                return _WIN_ARROWS.get(msvcrt.getwch(), "escape")
            return _name(char)
        time.sleep(0.01)
    return None


def _name(char: str) -> str:
    if char in ("\r", "\n"):
        return "enter"
    if char in ("\x7f", "\x08"):
        return "backspace"
    if char == " ":
        return "space"
    if char == "\x03":
        raise KeyboardInterrupt
    return char


def iter_keys(stop) -> Iterator[str]:  # type: ignore[no-untyped-def]
    """Yield keys until stop() is true."""
    while not stop():
        key = read_key()
        if key is not None:
            yield key
