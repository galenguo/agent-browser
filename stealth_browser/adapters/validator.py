"""Adapter YAML Structure Validator — Pure dict checks, zero external dependencies.

Uses the actual STEPS registry as the sole data source for step names
(won't drift). Called from loader.py's _ensure_loaded() for load-time validation.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Known valid strategy values (including aliases)
VALID_STRATEGIES = {"public", "cookie", "intercept", "ui", "store-action", "header"}
VALID_ARG_TYPES = {"str", "int", "float", "bool"}


def validate_adapter(adapter: dict[str, Any]) -> list[str]:
    """
    Validate adapter dict structure completeness.

    Returns:
        Error list (empty list = pass).

    Checks:
        1. Required fields: site, name, pipeline
        2. pipeline is a non-empty list
        3. Each pipeline step has a known op name
        4. strategy value is valid
        5. args type annotations are valid
    """
    errors: list[str] = []

    if not adapter or not isinstance(adapter, dict):
        errors.append("Adapter is empty or not a dict")
        return errors

    # 1. Required fields
    for field in ("site", "name", "pipeline"):
        if field not in adapter:
            errors.append(f"Missing required field: {field}")

    # 2. Pipeline structure
    pipeline = adapter.get("pipeline")
    if not isinstance(pipeline, list):
        errors.append("pipeline must be a list")
    elif len(pipeline) == 0:
        errors.append("pipeline must not be empty")
    else:
        # Lazy import to avoid circular dependency
        from stealth_browser.pipeline.steps import STEPS

        for i, step in enumerate(pipeline):
            if not isinstance(step, dict) or len(step) != 1:
                errors.append(f"pipeline[{i}]: invalid step format (expected {{op: params}})")
            else:
                op = next(iter(step.keys()))
                if op not in STEPS:
                    errors.append(f"pipeline[{i}]: unknown step '{op}'")

    # 3. Strategy validation
    strategy = adapter.get("strategy", "")
    if strategy and strategy not in VALID_STRATEGIES:
        errors.append(f"Invalid strategy: '{strategy}'. Must be one of {sorted(VALID_STRATEGIES)}")

    # 4. Args type validation
    args = adapter.get("args", {})
    if isinstance(args, dict):
        for arg_name, arg_spec in args.items():
            if isinstance(arg_spec, dict):
                arg_type = arg_spec.get("type", "")
                if arg_type and arg_type not in VALID_ARG_TYPES:
                    errors.append(
                        f"args.{arg_name}: invalid type '{arg_type}'. Must be one of {sorted(VALID_ARG_TYPES)}"
                    )

    # 5. Browser consistency check (browser:false shouldn't have navigate steps)
    browser = adapter.get("browser", True)
    if browser is False and isinstance(pipeline, list):
        nav_ops = [next(iter(s.keys())) for s in pipeline if isinstance(s, dict) and len(s) == 1]
        if "navigate" in nav_ops:
            errors.append("browser=false but pipeline contains 'navigate' step (contradiction)")

    return errors


def validate_all_adapters() -> dict[str, list[str]]:
    """Batch-validate all loaded adapters. Returns {adapter_key: errors} dict."""
    from .loader import list_adapters

    # Trigger loading
    adapters = list_adapters()
    results: dict[str, list[str]] = {}

    for adapter_meta in adapters:
        key = f"{adapter_meta['site']}/{adapter_meta['name']}"
        from .loader import get_adapter

        adapter = get_adapter(adapter_meta["site"], adapter_meta["name"])
        if adapter:
            results[key] = validate_adapter(adapter)
        else:
            results[key] = ["Adapter not found in registry"]

    return results
