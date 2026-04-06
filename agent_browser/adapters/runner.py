"""Adapter Runner — Find adapter → Create session → Execute pipeline → Return result."""

import logging
from typing import Any

from agent_browser.pipeline.executor import execute_pipeline

from .loader import get_adapter

logger = logging.getLogger(__name__)


async def run_adapter(
    site: str,
    command: str,
    session_id: str | None = None,
    cdp_url: str = "http://127.0.0.1:19222",
    **kwargs: Any,
) -> list[dict]:
    """
    Execute a site adapter command (deterministic, zero LLM cost).

    Args:
        site: Site name (e.g., "baidu")
        command: Command name (e.g., "search")
        session_id: Existing session ID (optional, auto-created if omitted)
        cdp_url: CDP connection address
        **kwargs: Adapter parameters

    Returns:
        Extracted data list.
    """
    # Ensure adapters are loaded (get_adapter calls _ensure_loaded internally)

    adapter = get_adapter(site, command)
    if not adapter:
        raise ValueError(f"Adapter not found: {site}/{command}")

    # Validate required parameters
    args_spec = adapter.get("args", {})
    for arg_name, arg_spec in args_spec.items():
        if arg_spec.get("required") and arg_name not in kwargs:
            # Use default value
            if "default" in arg_spec:
                kwargs[arg_name] = arg_spec["default"]
            else:
                raise ValueError(f"Missing required arg: {arg_name}")

    # Fill in defaults
    for arg_name, arg_spec in args_spec.items():
        if arg_name not in kwargs and "default" in arg_spec:
            kwargs[arg_name] = arg_spec["default"]

    # Manage session
    own_session = False
    if not session_id:
        from agent_browser.main import create_session, delete_session

        session_id = await create_session(cdp_url)
        own_session = True

    try:
        # Stealth configuration
        stealth = adapter.get("stealth", {})

        # Execute pipeline
        pipeline = adapter.get("pipeline", [])
        result = await execute_pipeline(
            steps=pipeline,
            session_id=session_id,
            args=kwargs,
            stealth_config=stealth,
        )

        return result if isinstance(result, list) else [result] if result else []

    finally:
        if own_session:
            try:
                from agent_browser.main import delete_session

                await delete_session(session_id)
            except Exception:
                pass
