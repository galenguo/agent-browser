"""API Key authentication for stealth-browser server.

Keys are loaded from a YAML file at startup (path configurable via API_KEYS_FILE env var).
Set API_AUTH_DISABLED=true to bypass auth entirely (local dev / testing only).
"""

from __future__ import annotations

import json
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
    """Load enabled API keys from keys.yaml into memory. Called once at server startup.

    Priority:
      1. keys.yaml file (if exists)
      2. API_KEYS env var (JSON array or comma-separated)
      3. API_KEY env var (single key fallback)
    """
    global _valid_keys
    if _AUTH_DISABLED:
        logger.warning("API auth disabled via API_AUTH_DISABLED — all requests will pass through")
        return

    # 1. Try keys.yaml file
    if _KEYS_FILE.exists():
        with open(_KEYS_FILE) as f:
            data = yaml.safe_load(f) or {}
        _valid_keys = {
            entry["key"]
            for entry in data.get("keys", [])
            if entry.get("enabled", True) and entry.get("key")
        }
        if _valid_keys:
            logger.info(f"Loaded {len(_valid_keys)} API key(s) from {_KEYS_FILE}")
            return

    # 2. Try API_KEYS env var (JSON array or comma-separated)
    api_keys_raw = os.getenv("API_KEYS", "")
    if api_keys_raw:
        try:
            keys_list = json.loads(api_keys_raw)
            if isinstance(keys_list, list):
                _valid_keys = {k for k in keys_list if k}
            else:
                _valid_keys = set()
        except (json.JSONDecodeError, TypeError):
            _valid_keys = {k.strip() for k in api_keys_raw.split(",") if k.strip()}
        if _valid_keys:
            logger.info(f"Loaded {len(_valid_keys)} API key(s) from API_KEYS env var")
            return

    # 3. Try API_KEY env var (single key)
    fallback = os.getenv("API_KEY", "")
    if fallback:
        _valid_keys = {fallback}
        logger.info("Loaded API key from API_KEY env var")
        return

    logger.warning(f"No API keys configured (no keys.yaml, no API_KEYS/API_KEY env var)")
    _valid_keys = set()


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
