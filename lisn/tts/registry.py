"""Engine lookup by name. Engines are imported lazily so optional deps stay optional."""

from __future__ import annotations

from lisn.errors import EngineUnavailableError
from lisn.tts.base import TTSEngine

ENGINE_NAMES: tuple[str, ...] = ("kokoro", "piper", "edge")


def get_engine(name: str) -> TTSEngine:
    normalized = (name or "kokoro").strip().lower()
    if normalized == "kokoro":
        from lisn.tts.kokoro import KokoroEngine

        return KokoroEngine()
    if normalized == "piper":
        from lisn.tts.piper import PiperEngine

        return PiperEngine()
    if normalized == "edge":
        from lisn.tts.edge import EdgeEngine

        return EdgeEngine()
    raise EngineUnavailableError(f"Unknown engine '{name}'. Choose from: {', '.join(ENGINE_NAMES)}")
