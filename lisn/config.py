"""User configuration: a small JSON file in the OS config dir, read/written immutably."""

from __future__ import annotations

import json
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any

from lisn.errors import ConfigError
from lisn.paths import config_file
from lisn.tts.base import MAX_SPEED, MIN_SPEED

HIGHLIGHT_MODES = ("word", "sentence")


@dataclass(frozen=True)
class Config:
    engine: str = "kokoro"
    voice: str = "af_heart"
    speed: float = 1.0
    volume: float = 1.0
    highlight: str = "word"
    autoscroll: bool = True
    prefetch: int = 3
    read_code: bool = False
    server_token: str = ""

    def with_overrides(self, **overrides: Any) -> Config:
        clean = {k: v for k, v in overrides.items() if v is not None}
        return validate(replace(self, **clean))


def load_config(path: Path | None = None) -> Config:
    file = path or config_file()
    if not file.exists():
        return Config()
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Config file {file} is unreadable: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"Config file {file} must contain a JSON object.")
    known = {f.name for f in fields(Config)}
    return validate(Config(**{k: v for k, v in raw.items() if k in known}))


def save_config(config: Config, path: Path | None = None) -> Path:
    file = path or config_file()
    file.parent.mkdir(parents=True, exist_ok=True)
    payload = {f.name: getattr(config, f.name) for f in fields(Config)}
    try:
        file.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Could not write config to {file}: {exc}") from exc
    return file


def set_value(config: Config, key: str, raw_value: str) -> Config:
    """Return a new Config with `key` parsed from its string form (for `lisn config set`)."""
    known = {f.name: f.type for f in fields(Config)}
    if key not in known:
        raise ConfigError(f"Unknown config key '{key}'. Known keys: {', '.join(known)}")
    current = getattr(config, key)
    try:
        if isinstance(current, bool):
            value: Any = raw_value.strip().lower() in {"1", "true", "yes", "on"}
        elif isinstance(current, int):
            value = int(raw_value)
        elif isinstance(current, float):
            value = float(raw_value)
        else:
            value = raw_value
    except ValueError as exc:
        raise ConfigError(f"'{raw_value}' is not a valid value for {key}.") from exc
    return validate(replace(config, **{key: value}))


def validate(config: Config) -> Config:
    if not (MIN_SPEED <= config.speed <= MAX_SPEED):
        raise ConfigError(f"speed must be between {MIN_SPEED} and {MAX_SPEED}, got {config.speed}")
    if not (0.0 <= config.volume <= 2.0):
        raise ConfigError(f"volume must be between 0 and 2, got {config.volume}")
    if config.highlight not in HIGHLIGHT_MODES:
        raise ConfigError(f"highlight must be one of {HIGHLIGHT_MODES}, got {config.highlight!r}")
    if not (1 <= config.prefetch <= 10):
        raise ConfigError(f"prefetch must be between 1 and 10, got {config.prefetch}")
    if not config.engine or not config.voice:
        raise ConfigError("engine and voice must not be empty")
    return config
