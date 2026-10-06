"""Common output type for every extractor: an ordered tuple of Blocks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

BlockKind = Literal["heading", "paragraph"]


@dataclass(frozen=True)
class Block:
    """A heading or a paragraph of raw (not yet normalized) text.

    `level` is the heading depth (1 = chapter) and is ignored for paragraphs.
    """

    kind: BlockKind
    text: str
    level: int = 0


@dataclass(frozen=True)
class Extracted:
    title: str
    source: str
    blocks: tuple[Block, ...]


def heading(text: str, level: int = 1) -> Block:
    return Block(kind="heading", text=text, level=level)


def paragraph(text: str) -> Block:
    return Block(kind="paragraph", text=text)
