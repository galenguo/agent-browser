"""
browser-use Agent connected to industrial-grade stealth browser.

Integration approach:
  1. Launch CloakBrowser via patchright (driver-level patches)
  2. browser-use BrowserSession connects via cdp_url
  3. Agent uses browser-use DOM compression + structured action operations

Key references:
  - browser-use/examples/browser/using_cdp.py — CDP connection example
  - browser-use/browser_use/browser/session.py — BrowserSession.connect()
  - browser-use/browser_use/browser/profile.py — cdp_url field
"""

import logging
import os
from typing import Any

# Activate rebrowser Runtime.Enable addBinding fix (env var, compatible with patchright)
os.environ.setdefault("REBROWSER_PATCHES_RUNTIME_FIX_MODE", "addBinding")

import contextlib

from browser_use import Agent, Tools
from browser_use.browser import BrowserProfile, BrowserSession

from agent_browser.browser.human_behavior import HumanBehaviorSimulator
from agent_browser.browser.stealth_launcher import close_browser, launch_stealth_browser
from agent_browser.session.session_manager import SessionProfileManager

logger = logging.getLogger(__name__)

# Global singleton: persistent session (avoid repeated launch/close)
_pw = None
_browser = None
_browser_session: BrowserSession | None = None
_session_manager = SessionProfileManager()


async def _ensure_browser_running(proxy: str | None = None) -> str:
    """Ensure CloakBrowser is running, return cdp_url. Singleton pattern, avoid repeated launches."""
    global _pw, _browser

    if _browser is not None:
        try:
            # Check if browser is still alive (compatible with Browser and BrowserContext)
            # Note: patchright and playwright have different types, use attribute detection not isinstance
            if hasattr(_browser, "pages") and not hasattr(_browser, "contexts"):
                _ = _browser.pages  # BrowserContext: use .pages to check
            else:
                _ = _browser.contexts  # Browser: use .contexts to check
            return f"http://127.0.0.1:{int(os.getenv('CDP_PORT', '19222'))}"
        except Exception:
            logger.warning("Browser died, relaunching...")
            _pw = None
            _browser = None

    _pw, _browser, cdp_url = await launch_stealth_browser(
        headless=os.getenv("HEADLESS", "false").lower() == "true",
        proxy=proxy,
    )
    return cdp_url


async def run_agent_task(
    task: str,
    llm: Any,
    *,
    proxy: str | None = None,
    max_steps: int = 50,
    warmup: bool = True,
    model_name: str = "unknown",
) -> str:
    """
    Run a single browser-use Agent task.

    Args:
        task: Task description
        llm: LangChain / browser-use compatible LLM instance
        proxy: Proxy address, e.g., "http://user:pass@host:port"
        max_steps: Maximum step count
        warmup: Whether to do warmup browsing before executing task
        model_name: For logging purposes

    Returns:
        Task execution result string.

    Example:
        from browser_use.llm import ChatAnthropic
        llm = ChatAnthropic(model="claude-haiku-4-5-20251001")
        result = await run_agent_task("Search for Python developer jobs on Boss Zhipin", llm)
    """
    cdp_url = await _ensure_browser_running(proxy=proxy)

    # Create browser-use BrowserSession (connect to already-running CloakBrowser)
    # is_local=True tells browser-use this is local CDP, don't try launching new browser
    browser_session = BrowserSession(
        browser_profile=BrowserProfile(
            cdp_url=cdp_url,
            is_local=True,
            headless=False,
            highlight_elements=True,
            minimum_wait_page_load_time=0.5,
            wait_for_network_idle_page_load_time=1.0,
        )
    )

    # Warmup browsing: establish normal user baseline (only on first task)
    if warmup:
        try:
            sim = HumanBehaviorSimulator()
            # Warmup via temporary page (not through browser-use)
            # Note: patchright and playwright have different types, use attribute detection
            if _browser:
                if hasattr(_browser, "pages") and not hasattr(_browser, "contexts"):
                    # BrowserContext: use pages directly
                    pages = _browser.pages
                    if pages:
                        await sim.warmup_browsing(pages[0])
                elif hasattr(_browser, "contexts") and _browser.contexts:
                    # Browser: get via contexts
                    ctx = _browser.contexts[0]
                    pages = ctx.pages
                    if pages:
                        await sim.warmup_browsing(pages[0])
        except Exception as e:
            logger.warning(f"Warmup failed (non-fatal): {e}")

    tools = Tools()
    # use_vision=False: disable screenshot input, avoids errors for models without vision support
    agent = Agent(
        task=task,
        llm=llm,
        tools=tools,
        browser_session=browser_session,
        max_actions_per_step=5,
        use_vision=False,
    )

    logger.info(f"Starting agent task (model={model_name}, max_steps={max_steps}): {task[:80]}")

    try:
        result = await agent.run(max_steps=max_steps)
        logger.info(f"Task completed: {str(result)[:200]}")
        return str(result)
    except Exception as e:
        logger.error(f"Agent task failed: {e}")
        raise
    finally:
        # Don't close browser (keep persistent session), only close browser-use session object
        with contextlib.suppress(Exception):
            await browser_session.kill()


async def shutdown_browser() -> None:
    """Shutdown global browser instance (call on program exit)."""
    global _pw, _browser
    if _browser is not None:
        await close_browser(_pw, _browser)
        _pw = None
        _browser = None
        logger.info("Global browser instance closed")
