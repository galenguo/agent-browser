"""
Integration test fixtures — shared setup for all integration tests.

Three fixture tiers:
  Tier 1: mock_backend     — ABC-level mock, always available (~0ms)
  Tier 2: real_browser      — CloakBrowser on :19222, auto-skipped
  Tier 3: api_server        — FastAPI on :8000, auto-skipped

CRITICAL: autouse reset clears ALL module-level singletons between tests.
Without this, tests leak state through _config, _middleware, _registry, etc.
"""

from pathlib import Path
from unittest import mock

import pytest

# ── Path setup (mirrors parent conftest) ──
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Import ABCs from the new package path
from agent_browser.browser import BrowserBackend, BrowserPageHandle

# Skip legacy monolithic test (not pytest-compatible, calls sys.exit at import)
collect_ignore = ["test_skill_scenarios.py"]


# ════════════════════════════════════════════
#  GLOBAL STATE RESET (autouse)
# ══════════════════════════════════════════════


@pytest.fixture(autouse=True)
def reset_global_state():
    """Reset ALL module-level singletons before each test.

    Singletons that leak state:
      1. main.py:       _config, _middleware, _middleware_lock
      2. daemon.py:     BrowserDaemon class-level singleton
      3. adapters/loader.py: _registry dict
    NOTE: steps.STEPS is NOT cleared — it's populated by @register
          decorators at import time and is read-only thereafter.
    """
    # 1. Reset main module globals
    from agent_browser import main as skill_main

    skill_main.reset()

    # 2. Reset BrowserDaemon singleton
    try:
        from agent_browser.daemon import BrowserDaemon

        BrowserDaemon.reset()
    except ImportError:
        pass

    # 3. Clear adapter registry
    try:
        from agent_browser.adapters import loader

        loader._registry = {}
    except (ImportError, AttributeError):
        pass

    yield

    # Post-test cleanup
    try:
        from agent_browser.daemon import BrowserDaemon

        BrowserDaemon.reset()
    except ImportError:
        pass


# ════════════════════════════════════════════
#  TIER 1: Mock Backend (always available)
# ══════════════════════════════════════════════


@pytest.fixture
def mock_page_handle() -> mock.MagicMock:
    """Mock BrowserPageHandle at ABC interface level."""
    handle = mock.MagicMock(spec=BrowserPageHandle)
    handle.goto = mock.AsyncMock()
    handle.evaluate = mock.AsyncMock(return_value={"elements": [], "title": "test"})
    handle.snapshot = mock.AsyncMock(return_value={"elements": [{"tag": "div", "text": "hello"}], "title": "Test Page"})
    handle.click = mock.AsyncMock()
    handle.fill = mock.AsyncMock()
    handle.mouse_wheel = mock.AsyncMock()
    handle.mouse_move = mock.AsyncMock()
    handle.keyboard_press = mock.AsyncMock()
    handle.wait_for_selector = mock.AsyncMock()
    handle.title = mock.AsyncMock(return_value="Test Page")
    handle.url = mock.AsyncMock(return_value="http://example.com")
    handle.close = mock.AsyncMock()
    handle.go_back = mock.AsyncMock()
    # Expose raw_page for stealth wrapper compatibility
    handle.raw_page = None
    return handle


@pytest.fixture
def mock_backend(mock_page_handle) -> mock.MagicMock:
    """Mock BrowserBackend at ABC interface level.

    We mock at ABC level (spec=BrowserBackend), NOT LocalCDPBackend.
    Reason: LocalCDPBackend.__init__ creates BrowserDaemon + CDP connection,
    which is a rabbit hole in test environments.
    """
    backend = mock.MagicMock(spec=BrowserBackend)
    backend.connect = mock.AsyncMock()
    backend.disconnect = mock.AsyncMock()
    backend.is_connected = mock.AsyncMock(return_value=True)
    backend.create_session = mock.AsyncMock(return_value=mock_page_handle)
    backend.delete_session = mock.AsyncMock()
    backend.get_page = mock.AsyncMock(return_value=mock_page_handle)
    # snapshot() is optional on BrowserBackend ABC (hasattr check in middleware)
    # but needed for tests that exercise main.snapshot()
    backend.snapshot = mock.AsyncMock(return_value={"elements": [{"tag": "div", "text": "hello"}], "title": "Test"})
    return backend


@pytest.fixture
def skill_config_no_stealth():
    """SkillConfig with stealth disabled (avoids StealthEnhancer C extension)."""
    from agent_browser.config import SkillConfig

    return SkillConfig(
        calling_mode="cli",
        browser_mode="local",
        intelligence="llm",
        stealth_enabled=False,
    )


# ════════════════════════════════════════════
#  TIER 2: Real Browser (requires CloakBrowser :19222)
# ══════════════════════════════════════════════


@pytest.fixture
def real_cdp_url():
    """CDP URL for CloakBrowser. Skips test if not available."""
    import socket

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(("127.0.0.1", 19222))
        sock.close()
        if result != 0:
            pytest.skip("CloakBrowser not available on port 19222")
    except OSError:
        pytest.skip("Cannot check CloakBrowser port 19222")
    return "http://127.0.0.1:19222"


# ════════════════════════════════════════════
#  TIER 3: API Server (requires FastAPI :8000)
# ══════════════════════════════════════════════


@pytest.fixture
def api_server_url():
    """FastAPI server URL. Skips test if not available."""
    import socket

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(("127.0.0.1", 8000))
        sock.close()
        if result != 0:
            pytest.skip("FastAPI server not available on port 8000")
    except OSError:
        pytest.skip("Cannot check FastAPI port 8000")
    return "http://127.0.0.1:8000"


# ════════════════════════════════════════════
#  Pipeline Step Helpers
# ══════════════════════════════════════════════


@pytest.fixture
def mock_page_for_steps() -> mock.MagicMock:
    """Lightweight mock page for pipeline step execution tests."""
    page = mock.MagicMock()
    page.goto = mock.AsyncMock()
    page.evaluate = mock.AsyncMock(return_value=[{"text": "result"}])
    page.wait_for_selector = mock.AsyncMock()
    page.keyboard_press = mock.AsyncMock()
    return page


@pytest.fixture
def patched_get_handle(mock_page_for_steps):
    """Patch _get_handle() + _ensure_middleware() so steps don't need real backend.

    Used by pipeline execution and security tests that call step handlers directly.
    Also covers step_snapshot which calls _ensure_middleware() directly.
    """
    from agent_browser import main as skill_main
    from agent_browser.pipeline import steps

    async def _fake_handle(sid):
        return mock_page_for_steps

    _mock_mw = mock.AsyncMock()
    _mock_mw.get_page = mock.AsyncMock(return_value=mock_page_for_steps)

    with (
        mock.patch.object(steps, "_get_handle", side_effect=_fake_handle),
        mock.patch.object(skill_main, "_ensure_middleware", return_value=_mock_mw),
    ):
        yield mock_page_for_steps
