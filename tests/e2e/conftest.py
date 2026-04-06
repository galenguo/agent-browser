"""
E2E test shared fixtures.

Provides:
  - e2e_page: Ready-to-use page (from parent conftest's browser_page fixture)
  - e2e_reset: Auto-cleans agent_browser module-level singleton state between tests
"""

import pytest

from agent_browser import reset


@pytest.fixture
async def e2e_page(browser_page):
    """
    E2E page fixture -- already connected to CloakBrowser, ready to use.

    Usage::

        async def test_xxx(e2e_page):
            await e2e_page.goto("https://example.com")
            title = await e2e_page.title()
    """
    yield browser_page


@pytest.fixture(autouse=True)
async def _e2e_cleanup():
    """Reset agent_browser module singletons after each E2E test.

    Prevents sequential-test timeouts caused by stale middleware/backend
    state (e.g., held asyncio.Lock, orphaned sessions, cached connections).
    """
    yield
    reset()
