"""Well-known on-disk locations, resolved per OS with platformdirs."""

from __future__ import annotations

from pathlib import Path

from platformdirs import user_cache_dir, user_config_dir, user_data_dir

APP_NAME = "lisn"


def config_dir() -> Path:
    return _ensure(Path(user_config_dir(APP_NAME)))


def data_dir() -> Path:
    return _ensure(Path(user_data_dir(APP_NAME)))


def cache_dir() -> Path:
    return _ensure(Path(user_cache_dir(APP_NAME)))


def audio_cache_dir() -> Path:
    return _ensure(cache_dir() / "audio")


def config_file() -> Path:
    return config_dir() / "config.json"


def state_db() -> Path:
    return data_dir() / "state.sqlite3"


def _ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
