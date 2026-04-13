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
    api_url: str | None = None,
    **kwargs: Any,
) -> list[dict]:
    """
    Execute a site adapter command (deterministic, zero LLM cost).

    Args:
        site: Site name (e.g., "baidu")
        command: Command name (e.g., "search")
        session_id: Existing session ID (optional, auto-created if omitted)
        cdp_url: CDP connection address
        api_url: FastAPI server URL (optional, auto-detected if needed)
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
    switched_backend = False
    if not session_id:
        from agent_browser.main import create_session

        session_id = await create_session(cdp_url)
        own_session = True
    else:
        # Ensure external session is accessible via the current backend
        switched_backend = await _ensure_session_accessible(session_id, api_url)

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
        if switched_backend:
            await _cleanup_switched_backend()


async def _ensure_session_accessible(session_id: str, api_url: str | None = None) -> bool:
    """Ensure an external session is accessible via the middleware backend.

    Tries the current backend first. If the session is not found,
    falls back to API mode (reset + reconfigure middleware).

    Returns:
        True if backend was switched (caller should clean up after use).
    """
    from agent_browser.main import _ensure_middleware, reset, configure

    mw = await _ensure_middleware()
    try:
        await mw.get_page(session_id)
        return False  # Session found in current backend
    except (ValueError, KeyError):
        pass  # Not found, try API mode

    # Current backend doesn't have the session — switch to API mode
    effective_api_url = api_url or "http://localhost:8000"
    logger.info(
        f"Session {session_id} not in current backend, "
        f"switching to API mode ({effective_api_url})"
    )

    reset()
    configure(calling_mode="api", api_url=effective_api_url)
    mw = await _ensure_middleware()

    # Trigger auto-registration for external sessions
    await mw.get_page(session_id)

    return True  # Backend was switched


async def _cleanup_switched_backend():
    """Close aiohttp session on the API backend to prevent resource leaks."""
    try:
        from agent_browser.main import _middleware

        if _middleware and hasattr(_middleware, "_backend"):
            backend = _middleware._backend
            http_session = getattr(backend, "_http_session", None)
            if http_session and not http_session.closed:
                await http_session.close()
                logger.debug("Cleaned up API backend aiohttp session")
    except Exception:
        pass
