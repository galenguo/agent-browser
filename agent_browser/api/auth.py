"""API Key authentication for agent-browser server.

Keys are loaded from a YAML file at startup (path configurable via API_KEYS_FILE env var).
Set API_AUTH_DISABLED=true to bypass auth entirely (local dev / testing only).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml
from fastapi import Header, HTTPException

logger = logging.getLogger(__name__)

_AUTH_DISABLED = os.getenv("API_AUTH_DISABLED", "").lower() in ("1", "true", "yes")
_KEYS_FILE = Path(os.getenv("API_KEYS_FILE", "/app/config/keys.yaml"))

_valid_keys: set[str] = set()


def load_keys() -> None:
    """Load enabled API keys from keys.yaml into memory. Called once at server startup."""
    global _valid_keys
    if _AUTH_DISABLED:
        logger.warning("API auth disabled via API_AUTH_DISABLED — all requests will pass through")
        return
    if not _KEYS_FILE.exists():
        logger.warning(f"API keys file not found: {_KEYS_FILE} — all authenticated requests will be rejected")
        _valid_keys = set()
        return
    with open(_KEYS_FILE) as f:
        data = yaml.safe_load(f) or {}
    _valid_keys = {
        entry["key"]
        for entry in data.get("keys", [])
        if entry.get("enabled", True) and entry.get("key")
    }
    logger.info(f"Loaded {len(_valid_keys)} API key(s) from {_KEYS_FILE}")


async def require_api_key(x_api_key: str | None = Header(None)) -> str:
    """FastAPI dependency: validate X-API-Key header.

    Returns the validated key string (used downstream for session ownership checks).
    Raises HTTP 401 if key is missing or invalid.
    """
    if _AUTH_DISABLED:
        return x_api_key or "__dev__"
    if not x_api_key or x_api_key not in _valid_keys:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return x_api_key
