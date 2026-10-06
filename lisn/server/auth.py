"""Random bearer token stored in the user config; the extension sends it on every request."""

from __future__ import annotations

import secrets

from lisn.config import Config, load_config, save_config


def ensure_token(config: Config | None = None) -> tuple[Config, str]:
    """Return (config, token), generating and persisting a token on first use."""
    current = config or load_config()
    if current.server_token:
        return current, current.server_token
    updated = current.with_overrides(server_token=secrets.token_urlsafe(24))
    save_config(updated)
    return updated, updated.server_token


def rotate_token(config: Config | None = None) -> tuple[Config, str]:
    current = config or load_config()
    updated = current.with_overrides(server_token=secrets.token_urlsafe(24))
    save_config(updated)
    return updated, updated.server_token
