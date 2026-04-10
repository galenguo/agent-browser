"""Session lifecycle script for agent-browser skill.

Entry point for all skill session operations. Loads ~/.agent-browser/skill.yaml,
detects missing config, and routes to the correct backend transparently.

Usage (from Claude Code):
    from agent_browser.skill.scripts.session import check_config, create, snapshot, ...

Missing skill.yaml returns a structured dict — never raises, never calls input().
Claude Code reads the dict and uses AskUserQuestion to guide the user.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

SKILL_YAML = Path.home() / ".agent-browser" / "skill.yaml"

_MODES = {
    "local": "Direct CloakBrowser CDP -- no server needed (default)",
    "remote-aio": "Remote all-in-one server -- needs api_url + vnc_url",
    "remote-distributed": "Remote distributed -- needs api_url (vnc URL returned per-session by API)",
}


def check_config() -> dict[str, Any]:
    """Return config status. If skill.yaml is missing, return a guided setup prompt.

    Returns:
        {"configured": True} if skill.yaml exists.
        {"configured": False, "prompt": str, "modes": dict, "next_step": str} otherwise.
    """
    if SKILL_YAML.exists():
        return {"configured": True}
    return {
        "configured": False,
        "prompt": (
            f"skill.yaml not found at {SKILL_YAML}\n"
            "Choose your deployment mode:\n"
            "  local            -- direct CloakBrowser CDP (no server)\n"
            "  remote-aio       -- remote all-in-one server (api_url + vnc_url required)\n"
            "  remote-distributed -- remote distributed (api_url required)\n"
        ),
        "modes": _MODES,
        "next_step": "python -m agent_browser.skill.scripts.setup --mode <choice> [--api-url <url>] [--vnc-url <url>]",
    }


def _require_config() -> dict[str, Any] | None:
    """Return config-missing dict if not configured, else None."""
    status = check_config()
    if not status["configured"]:
        return status
    return None


async def create(cdp_url: str | None = None, mode: str | None = None, api_url: str | None = None) -> str | dict:
    """Create a browser session using skill.yaml config.

    Returns session_id string, or config-missing guidance dict if skill.yaml absent.
    """
    missing = _require_config()
    if missing:
        return missing
    from agent_browser import create_session
    return await create_session(cdp_url=cdp_url, mode=mode, api_url=api_url)


async def open_page(session_id: str, url: str) -> dict | None:
    """Navigate to url. Returns config-missing dict if skill.yaml absent."""
    missing = _require_config()
    if missing:
        return missing
    from agent_browser import open_page as _open_page
    await _open_page(session_id, url)
    return None


async def snapshot(session_id: str, interactive_only: bool = False) -> dict:
    """Snapshot current page. Returns config-missing dict if skill.yaml absent."""
    missing = _require_config()
    if missing:
        return missing
    from agent_browser import snapshot as _snapshot
    return await _snapshot(session_id, interactive_only)


async def click(session_id: str, ref: str) -> dict | None:
    """Click element by ref (@eN). Returns config-missing dict if skill.yaml absent."""
    missing = _require_config()
    if missing:
        return missing
    from agent_browser import click as _click
    await _click(session_id, ref)
    return None


async def fill(session_id: str, ref: str, text: str) -> dict | None:
    """Fill input element. Returns config-missing dict if skill.yaml absent."""
    missing = _require_config()
    if missing:
        return missing
    from agent_browser import fill as _fill
    await _fill(session_id, ref, text)
    return None


async def scroll(session_id: str, direction: str = "down", amount: int = 500) -> dict | None:
    """Scroll page. Returns config-missing dict if skill.yaml absent."""
    missing = _require_config()
    if missing:
        return missing
    from agent_browser import scroll as _scroll
    await _scroll(session_id, direction, amount)
    return None


async def delete(session_id: str) -> dict | None:
    """Delete browser session. Returns config-missing dict if skill.yaml absent."""
    missing = _require_config()
    if missing:
        return missing
    from agent_browser import delete_session
    await delete_session(session_id)
    return None


async def run_task(
    session_id: str,
    task: str,
    intelligence: str = "agent",
    max_steps: int = 6,
) -> dict:
    """Run autonomous agent task. Returns config-missing dict if skill.yaml absent."""
    missing = _require_config()
    if missing:
        return missing
    from agent_browser import run_task as _run_task
    return await _run_task(session_id, task, intelligence=intelligence, max_steps=max_steps)
