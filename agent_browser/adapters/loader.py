"""Adapter Loader — Scan adapters/ directory, parse YAML, register in memory.

Supports both native and compatible format YAML adapters.
Compatible top-level fields are accepted and normalized internally.
"""
import os
import logging
from typing import Dict, List, Optional
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# In-memory registry: {(site, name): adapter_dict}
_registry: Dict[tuple, dict] = {}

# Default adapter directory (adapters/ under project root)
# File is at: agent_browser/adapters/loader.py
# parents[0]=adapters, [1]=agent_browser, [2]=project_root
_ADAPTER_DIR = str(Path(__file__).resolve().parents[2] / "adapters")

# Strategy value mapping
_STRATEGY_MAP = {
    "intercept": "cookie",   # 'intercept' = cookie-based fetch interception
    # Other values pass through: public, ui, store-action, header, cookie
}


def _normalize_adapter(adapter: dict) -> dict:
    """
    Normalize an adapter dict to internal format.

    Transformations:
      - domain → site (alias)
      - intercept strategy → cookie (internal mapping)
      - navigateBefore → prepended as first pipeline step
    """
    if not adapter:
        return adapter

    adapter = dict(adapter)  # shallow copy

    # 'domain' is alias for 'site'
    if "domain" in adapter and "site" not in adapter:
        adapter["site"] = adapter.pop("domain")

    # Normalize strategy values
    raw_strategy = adapter.get("strategy", "")
    if raw_strategy in _STRATEGY_MAP:
        adapter["strategy"] = _STRATEGY_MAP[raw_strategy]

    # Handle navigateBefore (pre-navigation step)
    nav_before = adapter.pop("navigateBefore", None)
    if nav_before and isinstance(nav_before, str):
        pipeline = adapter.get("pipeline", [])
        # Prepend navigate step
        pipeline.insert(0, {"navigate": nav_before})
        adapter["pipeline"] = pipeline

    return adapter


def _ensure_loaded():
    """Ensure adapters are loaded (lazy scan)."""
    if _registry:
        return
    adapter_dir = _ADAPTER_DIR
    if not os.path.isdir(adapter_dir):
        logger.warning(f"Adapter directory not found: {adapter_dir}")
        return

    for root, dirs, files in os.walk(adapter_dir):
        if "_shared" in root:
            continue
        for fname in files:
            if not fname.endswith((".yaml", ".yml")):
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    adapter = yaml.safe_load(f)
                # Normalize format to internal
                adapter = _normalize_adapter(adapter)
                if not adapter or "site" not in adapter or "name" not in adapter:
                    logger.debug(f"Skipping invalid adapter: {fpath}")
                    continue

                # Validate structure (warn but still register for backward compat)
                from .validator import validate_adapter
                errs = validate_adapter(adapter)
                if errs:
                    logger.warning(f"Adapter validation warnings for {fpath}: {errs}")
                    adapter["_validation_errors"] = errs
                    logger.debug(f"Skipping invalid adapter: {fpath}")
                    continue
                key = (adapter["site"], adapter["name"])
                adapter["_file"] = fpath
                _registry[key] = adapter
                logger.debug(f"Loaded adapter: {key}")
            except Exception as e:
                logger.warning(f"Failed to load adapter {fpath}: {e}")

    logger.info(f"Loaded {len(_registry)} adapters from {adapter_dir}")


def list_adapters() -> List[dict]:
    """List all registered adapters."""
    _ensure_loaded()
    return [
        {
            "site": key[0],
            "name": key[1],
            "description": adapter.get("description", ""),
            "strategy": adapter.get("strategy", "public"),
            "columns": adapter.get("columns", []),
            "args": list(adapter.get("args", {}).keys()),
        }
        for key, adapter in _registry.items()
    ]


def get_adapter(site: str, name: str) -> Optional[dict]:
    """Get a specific adapter by site and name."""
    _ensure_loaded()
    return _registry.get((site, name))
