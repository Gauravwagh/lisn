"""Unicode and whitespace normalization applied to every extracted block of text.

The output is still "display" text: it keeps punctuation and casing, but replaces
typographic variants (ligatures, smart quotes, odd spaces) with plain equivalents so
that both the screen and the TTS engine see the same clean characters.
"""

from __future__ import annotations

import re
import unicodedata

_LIGATURES = {
    "ﬀ": "ff",
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
    "ﬅ": "st",
    "ﬆ": "st",
    "Œ": "OE",
    "œ": "oe",
}

_QUOTES = {
    "‘": "'",
    "’": "'",
    "‚": "'",
    "‛": "'",
    "′": "'",
    "“": '"',
    "”": '"',
    "„": '"',
    "‟": '"',
    "″": '"',
    "«": '"',
    "»": '"',
}

_HYPHENS = {
    "‐": "-",
    "‑": "-",
    "‒": "-",
    "−": "-",
}

_OTHER = {
    "…": "...",
    " ": " ",
    " ": " ",
    " ": " ",
    "　": " ",
    " ": " ",
    " ": " ",
    " ": "\n",
    " ": "\n\n",
    "\t": " ",
}

_DELETE = "".join(["­", "​", "‌", "‍", "⁠", "﻿"])

_TRANSLATION = str.maketrans({**_LIGATURES, **_QUOTES, **_HYPHENS, **_OTHER})
_DELETE_TABLE = str.maketrans("", "", _DELETE)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SPACE_RUN_RE = re.compile(r"[ ]{2,}")
_BLANK_LINES_RE = re.compile(r"\n{3,}")
_TRAILING_SPACE_RE = re.compile(r"[ ]+\n")


def normalize(text: str) -> str:
    """Return a cleaned copy of `text`; never mutates the input."""
    if not isinstance(text, str):
        raise TypeError(f"normalize expects str, got {type(text).__name__}")
    cleaned = unicodedata.normalize("NFC", text)
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = cleaned.translate(_DELETE_TABLE).translate(_TRANSLATION)
    cleaned = _CONTROL_RE.sub("", cleaned)
    cleaned = _SPACE_RUN_RE.sub(" ", cleaned)
    cleaned = _TRAILING_SPACE_RE.sub("\n", cleaned)
    cleaned = _BLANK_LINES_RE.sub("\n\n", cleaned)
    return cleaned.strip()


def collapse_whitespace(text: str) -> str:
    """Collapse all whitespace (including newlines) to single spaces."""
    return " ".join(text.split())
