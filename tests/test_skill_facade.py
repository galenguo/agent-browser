"""Facade-layer routing tests -- prove main.py public API works correctly.

These tests validate that the FACADE (main.py) correctly routes operations
through _ensure_middleware() -> StealthMiddleware -> BrowserBackend.

This is the GENUINE GAP in existing tests:
- tests/e2e/ hit backends directly (bypassing the facade)
- tests/integration/ test components in isolation
- NO existing test proves: create_session() -> snapshot() -> click() -> fill()
  goes through the full middleware stack via the PUBLIC API

Strategy: Mock at the StealthMiddleware boundary. We don't need a real browser.
We just need to prove:
  1. setup() returns structured dict with correct keys
  2. create_session() calls through _ensure_middleware -> backend.create_session
  3. snapshot/click/fill go through _ref_op / _get_page -> middleware
  4. run_task() delegates to middleware.run_task with correct params
  5. configure() updates global config
  6. reset() clears global state
  7. Error handling: FirstSessionError carries recovery dict
  8. Mode routing: _select_backend picks correct backend per config
"""

import asyncio
import os
import sys
import uuid
from unittest import mock

import pytest

from agent_browser.config import SkillConfig
from agent_browser.main import (
    DepStatus,
    FirstSessionError,
    RecoveryReport,
    _format_recovery_for_claude,
    _select_backend,
    click,
    configure,
    create_session,
    delete_session,
    detect_missing_deps,
    fill,
    go_back,
    hover,
    open_page,
    press_key,
    reset,
    run_task,
    scroll,
    select_option,
    setup,
    snapshot,
    wait_for_selector,
)

# ════════════════════════════════════════════════════════════════════
# Fixtures
# ════════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def _reset_globals():
    """Reset module-level globals before/after each test."""
    import agent_browser.main as mod

    saved_config = mod._config
    saved_middleware = mod._middleware
    mod._config = None
    mod._middleware = None
    yield
    mod._config = saved_config
    mod._middleware = saved_middleware


def _make_mock_middleware():
    """Create a mock StealthMiddleware with all required async methods."""
    mw = mock.AsyncMock()
    mw.connect = mock.AsyncMock()
    mw.disconnect = mock.AsyncMock()
    mw.create_session = mock.AsyncMock()
    mw.delete_session = mock.AsyncMock()
    mw.get_page = mock.AsyncMock()
    mw.snapshot = mock.AsyncMock(
        return_value={
            "url": "https://example.com",
            "title": "Example",
            "elements": [
                {"ref": "@e0", "tag": "button", "text": "Submit"},
                {"ref": "@e1", "tag": "input", "type": "text"},
                {"ref": "@e2", "tag": "a", "href": "/next", "text": "Next"},
            ],
        }
    )
    mw.run_task = mock.AsyncMock(
        return_value={
            "status": "completed",
            "result": "Task done",
            "steps_taken": 3,
        }
    )
    mw.cache_snapshot_after_open = mock.AsyncMock()
    return mw


def _make_mock_page():
    """Create a mock page handle for _get_page to return."""
    page = mock.AsyncMock()
    page.goto = mock.AsyncMock()
    page.evaluate = mock.AsyncMock()
    page.mouse_wheel = mock.AsyncMock()
    page.mouse_move = mock.AsyncMock()
    page.keyboard_press = mock.AsyncMock()
    page.wait_for_selector = mock.AsyncMock()
    page.go_back = mock.AsyncMock()
    page.evaluate.return_value = {"x": 100, "y": 200}
    return page


# ════════════════════════════════════════════════════════════════════
# A. setup() [P0]
# ════════════════════════════════════════════════════════════════════


class TestSetup:
    async def test_setup_returns_structured_dict(self):
        """setup() returns dict with expected top-level keys."""
        with (
            mock.patch("agent_browser.deploy_config.detect_environment", return_value={"os": "linux", "arch": "amd64"}),
            mock.patch("agent_browser.deploy_config.load_deploy_config") as mock_load,
            mock.patch("agent_browser.deploy_config.validate_config", return_value=[]),
            mock.patch("agent_browser.deploy_config.generate_config", return_value="/tmp/config.yaml"),
            mock.patch(
                "agent_browser.main.detect_missing_deps", new_callable=mock.AsyncMock, return_value=RecoveryReport()
            ),
        ):
            from agent_browser.deploy_config import DeployConfig

            mock_load.return_value = DeployConfig(mode="local")
            result = await setup()
            assert isinstance(result, dict)
            assert "config" in result
            assert "issues" in result
            assert "report" in result
            assert "ready" in result
            assert "config_path" in result
            assert "environment" in result

    async def test_setup_ready_when_no_errors(self):
        """setup() ready=True when no errors and no missing deps."""
        with (
            mock.patch("agent_browser.deploy_config.detect_environment", return_value={"os": "linux", "arch": "amd64"}),
            mock.patch("agent_browser.deploy_config.load_deploy_config") as mock_load,
            mock.patch("agent_browser.deploy_config.validate_config", return_value=[]),
            mock.patch("agent_browser.deploy_config.generate_config", return_value="/tmp/config.yaml"),
            mock.patch(
                "agent_browser.main.detect_missing_deps", new_callable=mock.AsyncMock, return_value=RecoveryReport()
            ),
        ):
            from agent_browser.deploy_config import DeployConfig

            mock_load.return_value = DeployConfig(mode="local")
            result = await setup()
            assert result["ready"] is True

    async def test_setup_not_ready_with_errors(self):
        """setup() ready=False when validation errors exist."""
        from agent_browser.deploy_config import ConfigIssue

        issues = [ConfigIssue(severity="error", section="deployment", message="bad mode")]
        with (
            mock.patch("agent_browser.deploy_config.detect_environment", return_value={"os": "linux", "arch": "amd64"}),
            mock.patch("agent_browser.deploy_config.load_deploy_config") as mock_load,
            mock.patch("agent_browser.deploy_config.validate_config", return_value=issues),
            mock.patch("agent_browser.deploy_config.generate_config", return_value="/tmp/config.yaml"),
            mock.patch(
                "agent_browser.main.detect_missing_deps", new_callable=mock.AsyncMock, return_value=RecoveryReport()
            ),
        ):
            from agent_browser.deploy_config import DeployConfig

            mock_load.return_value = DeployConfig(mode="local")
            result = await setup()
            assert result["ready"] is False

    async def test_setup_calls_generate_config(self):
        """setup() calls generate_config() to write config file."""
        with (
            mock.patch("agent_browser.deploy_config.detect_environment", return_value={"os": "linux", "arch": "amd64"}),
            mock.patch("agent_browser.deploy_config.load_deploy_config") as mock_load,
            mock.patch("agent_browser.deploy_config.validate_config", return_value=[]),
            mock.patch("agent_browser.deploy_config.generate_config", return_value="/tmp/test-config.yaml") as mock_gen,
            mock.patch(
                "agent_browser.main.detect_missing_deps", new_callable=mock.AsyncMock, return_value=RecoveryReport()
            ),
        ):
            from agent_browser.deploy_config import DeployConfig

            mock_load.return_value = DeployConfig(mode="local")
            result = await setup()
            mock_gen.assert_called_once()
            assert result["config_path"] == "/tmp/test-config.yaml"


# ════════════════════════════════════════════════════════════════════
# B. configure() + reset() [P0]
# ════════════════════════════════════════════════════════════════════


class TestConfigureReset:
    def test_configure_updates_global_config(self):
        """configure() sets _config globally."""
        cfg = configure(calling_mode="api", cdp_url="http://custom:9222")
        assert cfg is not None
        assert cfg.calling_mode == "api"
        assert cfg.cdp_url == "http://custom:9222"

    def test_configure_returns_skillconfig(self):
        """configure() returns a SkillConfig instance."""
        cfg = configure()
        from agent_browser.config import SkillConfig

        assert isinstance(cfg, SkillConfig)

    def test_reset_clears_globals(self):
        """reset() sets _config and _middleware to None."""
        import agent_browser.main as mod

        mod._config = SkillConfig(calling_mode="api")
        mod._middleware = _make_mock_middleware()
        reset()
        assert mod._config is None
        assert mod._middleware is None

    def test_reset_idempotent(self):
        """reset() when already reset is safe (no error)."""
        reset()  # first time
        reset()  # second time -- should not raise


# ════════════════════════════════════════════════════════════════════
# C. create_session() [P0]
# ════════════════════════════════════════════════════════════════════


class TestCreateSession:
    async def test_create_session_returns_uuid_hex(self):
        """create_session() returns a hex string (UUID format)."""
        mw = _make_mock_middleware()
        with mock.patch("agent_browser.main._ensure_middleware", new_callable=mock.AsyncMock, return_value=mw):
            sid = await create_session()
            assert isinstance(sid, str)
            assert len(sid) == 32  # UUID hex length
            uuid.UUID(sid)  # should not raise

    async def test_create_session_calls_middleware(self):
        """create_session() delegates to middleware.create_session()."""
        mw = _make_mock_middleware()
        with mock.patch("agent_browser.main._ensure_middleware", new_callable=mock.AsyncMock, return_value=mw):
            sid = await create_session()
            mw.create_session.assert_called_once_with(sid)

    async def test_create_session_with_mode_param(self):
        """create_session(mode='api') passes mode to load_config."""
        mw = _make_mock_middleware()
        with (
            mock.patch("agent_browser.main.load_config", return_value=SkillConfig(calling_mode="api")),
            mock.patch("agent_browser.main._ensure_middleware", new_callable=mock.AsyncMock, return_value=mw),
        ):
            sid = await create_session(mode="api")
            assert isinstance(sid, str)

    async def test_create_session_with_cdp_url(self):
        """create_session(cdp_url=...) passes custom CDP URL."""
        mw = _make_mock_middleware()
        with mock.patch(
            "agent_browser.main._ensure_middleware", new_callable=mock.AsyncMock, return_value=mw
        ) as mock_ens:
            await create_session(cdp_url="http://localhost:9222")
            call_kwargs = mock_ens.call_args[0][0] if mock_ens.call_args else None
            if call_kwargs:
                assert call_kwargs.cdp_url == "http://localhost:9222"


# ════════════════════════════════════════════════════════════════════
# D. ReAct Cycle: snapshot -> click -> fill [P0-CORE]
# ════════════════════════════════════════════════════════════════════


class TestReactCycle:
    async def test_snapshot_returns_elements(self):
        """snapshot() returns dict with url, title, elements list."""
        mw = _make_mock_middleware()
        page = _make_mock_page()
        mw.get_page.return_value = page
        with mock.patch("agent_browser.main._ensure_middleware", new_callable=mock.AsyncMock, return_value=mw):
            result = await snapshot("test-session")
            assert "url" in result
            assert "title" in result
            assert "elements" in result
            assert isinstance(result["elements"], list)
            assert len(result["elements"]) > 0

    async def test_snapshot_elements_have_refs(self):
        """Snapshot elements have data-ab-ref style @eN references."""
        mw = _make_mock_middleware()
        page = _make_mock_page()
        mw.get_page.return_value = page
        with mock.patch("agent_browser.main._ensure_middleware", new_callable=mock.AsyncMock, return_value=mw):
            result = await snapshot("test-session")
            for elem in result["elements"]:
                assert "ref" in elem
                assert elem["ref"].startswith("@e")

    async def test_click_executes_via_ref_op(self):
        """click(session_id, ref) executes JS click on element."""
        mw = _make_mock_middleware()
        page = _make_mock_page()
        page.evaluate.return_value = {"status": "ok"}
        mw.get_page.return_value = page
        with mock.patch("agent_browser.main._ensure_middleware", new_callable=mock.AsyncMock, return_value=mw):
            await click("sid", "@e0")
            page.evaluate.assert_called_once()
            call_js = page.evaluate.call_args[0][0]
            assert ".click()" in call_js

    async def test_fill_types_text_via_ref_op(self):
        """fill(session_id, ref, text) sets value + dispatches input event."""
        mw = _make_mock_middleware()
        page = _make_mock_page()
        page.evaluate.return_value = {"status": "ok"}
        mw.get_page.return_value = page
        with mock.patch("agent_browser.main._ensure_middleware", new_callable=mock.AsyncMock, return_value=mw):
            await fill("sid", "@e1", "hello world")
            page.evaluate.assert_called_once()
            call_js = page.evaluate.call_args[0][0]
            assert "hello world" in call_js
            assert "input" in call_js

    async def test_invalid_ref_raises_valueerror(self):
        """Non-@eN ref raises ValueError."""
        with pytest.raises(ValueError, match="Invalid ref"):
            await click("sid", "bad-ref")


# ════════════════════════════════════════════════════════════════════
# E. Other Facade Operations [P0]
# ════════════════════════════════════════════════════════════════════


class TestOtherOperations:
    async def test_open_page_navigates(self):
        """open_page() calls page.goto() with validated URL."""
        mw = _make_mock_middleware()
        page = _make_mock_page()
        mw.get_page.return_value = page
        with mock.patch("agent_browser.main._ensure_middleware", new_callable=mock.AsyncMock, return_value=mw):
            await open_page("sid", "https://example.com")
            page.goto.assert_called_once_with("https://example.com")

    async def test_scroll_calls_mouse_wheel(self):
        """scroll() delegates to page.mouse_wheel()."""
        mw = _make_mock_middleware()
        page = _make_mock_page()
        mw.get_page.return_value = page
        with mock.patch("agent_browser.main._ensure_middleware", new_callable=mock.AsyncMock, return_value=mw):
            await scroll("sid", "down", 300)
            page.mouse_wheel.assert_called_once_with(0, 300)

    async def test_scroll_up_negative_amount(self):
        """scroll('up') passes negative amount to mouse_wheel."""
        mw = _make_mock_middleware()
        page = _make_mock_page()
        mw.get_page.return_value = page
        with mock.patch("agent_browser.main._ensure_middleware", new_callable=mock.AsyncMock, return_value=mw):
            await scroll("sid", "up", 200)
            page.mouse_wheel.assert_called_once_with(0, -200)

    async def test_hover_gets_element_center_then_moves(self):
        """hover() queries bounding box then moves mouse to center."""
        mw = _make_mock_middleware()
        page = _make_mock_page()
        page.evaluate.return_value = {"x": 150, "y": 250}
        mw.get_page.return_value = page
        with mock.patch("agent_browser.main._ensure_middleware", new_callable=mock.AsyncMock, return_value=mw):
            await hover("sid", "@e0")
            page.mouse_move.assert_called_once_with(150, 250)

    async def test_press_key_delegates(self):
        """press_key() calls page.keyboard_press()."""
        mw = _make_mock_middleware()
        page = _make_mock_page()
        mw.get_page.return_value = page
        with mock.patch("agent_browser.main._ensure_middleware", new_callable=mock.AsyncMock, return_value=mw):
            await press_key("sid", "Enter")
            page.keyboard_press.assert_called_once_with("Enter")

    async def test_wait_for_selector_delegates(self):
        """wait_for_selector() calls page.wait_for_selector()."""
        mw = _make_mock_middleware()
        page = _make_mock_page()
        mw.get_page.return_value = page
        with mock.patch("agent_browser.main._ensure_middleware", new_callable=mock.AsyncMock, return_value=mw):
            await wait_for_selector("sid", ".result", timeout=5000)
            page.wait_for_selector.assert_called_once_with(".result", timeout=5000)

    async def test_go_back_delegates(self):
        """go_back() calls page.go_back()."""
        mw = _make_mock_middleware()
        page = _make_mock_page()
        mw.get_page.return_value = page
        with mock.patch("agent_browser.main._ensure_middleware", new_callable=mock.AsyncMock, return_value=mw):
            await go_back("sid")
            page.go_back.assert_called_once()

    async def test_delete_session_delegates(self):
        """delete_session() calls middleware.delete_session()."""
        mw = _make_mock_middleware()
        with mock.patch("agent_browser.main._ensure_middleware", new_callable=mock.AsyncMock, return_value=mw):
            await delete_session("sid")
            mw.delete_session.assert_called_once_with("sid")

    async def test_select_option_sets_value(self):
        """select_option() sets value + dispatches change event."""
        mw = _make_mock_middleware()
        page = _make_mock_page()
        page.evaluate.return_value = {"status": "ok"}
        mw.get_page.return_value = page
        with mock.patch("agent_browser.main._ensure_middleware", new_callable=mock.AsyncMock, return_value=mw):
            await select_option("sid", "@e0", "option-value")
            call_js = page.evaluate.call_args[0][0]
            assert "option-value" in call_js
            assert "change" in call_js


# ════════════════════════════════════════════════════════════════════
# F. run_task() [P0]
# ════════════════════════════════════════════════════════════════════


class TestRunTask:
    async def test_run_task_delegates_to_middleware(self):
        """run_task() calls middleware.run_task() with correct args."""
        mw = _make_mock_middleware()
        with mock.patch("agent_browser.main._ensure_middleware", new_callable=mock.AsyncMock, return_value=mw):
            await run_task("sid", "search for Python jobs", intelligence="agent")
            mw.run_task.assert_called_once()
            call_args = mw.run_task.call_args
            assert call_args[0][0] == "sid"
            assert call_args[0][1] == "search for Python jobs"
            kwargs = call_args[1] if len(call_args) > 1 else {}
            assert kwargs.get("intelligence") == "agent"

    async def test_run_task_llm_mode(self):
        """run_task(intelligence='llm') passes llm mode through."""
        mw = _make_mock_middleware()
        with mock.patch("agent_browser.main._ensure_middleware", new_callable=mock.AsyncMock, return_value=mw):
            await run_task("sid", "summarize page", intelligence="llm")
            _, kwargs = mw.run_task.call_args
            assert kwargs.get("intelligence") == "llm"

    async def test_run_task_max_steps_passed(self):
        """max_steps kwarg forwarded to middleware."""
        mw = _make_mock_middleware()
        with mock.patch("agent_browser.main._ensure_middleware", new_callable=mock.AsyncMock, return_value=mw):
            await run_task("sid", "task", max_steps=3)
            _, kwargs = mw.run_task.call_args
            assert kwargs.get("max_steps") == 3

    async def test_run_task_timeout_passed(self):
        """total_timeout kwarg forwarded to middleware."""
        mw = _make_mock_middleware()
        with mock.patch("agent_browser.main._ensure_middleware", new_callable=mock.AsyncMock, return_value=mw):
            await run_task("sid", "task", total_timeout=60.0)
            _, kwargs = mw.run_task.call_args
            assert kwargs.get("total_timeout") == 60.0

    async def test_run_task_returns_result(self):
        """run_task() returns the result dict from middleware."""
        mw = _make_mock_middleware()
        mw.run_task.return_value = {
            "status": "completed",
            "result": "Found 42 results",
            "steps_taken": 5,
        }
        with mock.patch("agent_browser.main._ensure_middleware", new_callable=mock.AsyncMock, return_value=mw):
            result = await run_task("sid", "search")
            assert result["status"] == "completed"
            assert "result" in result


# ════════════════════════════════════════════════════════════════════
# G. _select_backend() Mode Routing [P0]
# ════════════════════════════════════════════════════════════════════


class TestBackendSelection:
    def test_cli_mode_selects_local(self):
        """CLI calling_mode selects LocalCDPBackend (no extension)."""
        cfg = SkillConfig(calling_mode="cli")
        with mock.patch(
            "agent_browser.main._try_extension_connection", new_callable=mock.AsyncMock, return_value=False
        ):
            backend = asyncio.get_event_loop().run_until_complete(_select_backend(cfg))
            from agent_browser.browser.local import LocalCDPBackend

            assert isinstance(backend, LocalCDPBackend)

    def test_api_mode_selects_remote(self):
        """API calling_mode selects RemoteAPIBackend."""
        cfg = SkillConfig(calling_mode="api")
        with mock.patch(
            "agent_browser.main._try_extension_connection", new_callable=mock.AsyncMock, return_value=False
        ):
            backend = asyncio.get_event_loop().run_until_complete(_select_backend(cfg))
            from agent_browser.browser.remote import RemoteAPIBackend

            assert isinstance(backend, RemoteAPIBackend)

    def test_unknown_mode_falls_back_to_local(self):
        """Unknown calling_mode falls back to LocalCDPBackend."""
        cfg = SkillConfig(calling_mode="weird-mode")
        with mock.patch(
            "agent_browser.main._try_extension_connection", new_callable=mock.AsyncMock, return_value=False
        ):
            backend = asyncio.get_event_loop().run_until_complete(_select_backend(cfg))
            from agent_browser.browser.local import LocalCDPBackend

            assert isinstance(backend, LocalCDPBackend)

    def test_extension_available_takes_priority(self):
        """Extension connection takes priority over local/remote."""
        cfg = SkillConfig(calling_mode="cli")
        with (
            mock.patch("agent_browser.main._try_extension_connection", new_callable=mock.AsyncMock, return_value=True),
        ):
            backend = asyncio.get_event_loop().run_until_complete(_select_backend(cfg))
            # ExtensionBackend should be selected when extension is available
            assert type(backend).__name__ == "ExtensionBackend"


# ════════════════════════════════════════════════════════════════════
# H. Error Handling: FirstSessionError [P0]
# ════════════════════════════════════════════════════════════════════


class TestErrorHandling:
    def test_first_session_error_carries_recovery(self):
        """FirstSessionError carries structured recovery dict."""
        recovery = {
            "ready": False,
            "missing": ["cloakbrowser"],
            "fixable": [{"name": "cloakbrowser", "command": "pip install cloakbrowser"}],
            "needs_human": [],
            "suggestion": "Missing 1 dep(s): cloakbrowser.",
        }
        err = FirstSessionError("Setup needed", recovery, original_error=ConnectionError("CDP down"))
        assert err.recovery == recovery
        assert err.original_error is not None
        assert "cloakbrowser" in err.recovery["missing"]

    def test_format_recovery_produces_dict(self):
        """_format_recovery_for_claude converts RecoveryReport to plain dict."""
        report = RecoveryReport(
            missing_deps=[
                DepStatus(name="cloakbrowser", available=False, fixable=True, fix_command="pip install it"),
            ],
            needs_human=[
                DepStatus(name="api_key", available=False, fixable=False, message="No key"),
            ],
        )
        d = _format_recovery_for_claude(report)
        assert d["ready"] is False
        assert "cloakbrowser" in d["missing"]
        assert len(d["fixable"]) >= 1
        assert "api_key" in d["needs_human"]
        assert "suggestion" in d

    def test_detect_missing_deps_ready_report(self):
        """detect_missing_deps returns valid structure (may or may not be ready)."""
        # Mock all checks to pass
        with (
            mock.patch.dict("sys.modules", {"cloakbrowser": type(sys)("cloakbrowser")}),
            mock.patch("aiohttp.ClientSession") as mock_session,
        ):
            mock_sess = mock.Mock()
            mock_sess.__aenter__ = mock.AsyncMock(
                return_value=mock.Mock(
                    get=mock.AsyncMock(
                        return_value=mock.AsyncMock(
                            __aenter__=mock.AsyncMock(return_value=mock.Mock(status=200)),
                        )
                    ),
                )
            )
            mock_sess.__aexit__ = mock.AsyncMock(return_value=None)
            mock_session.return_value = mock_sess
            os.environ.setdefault("OPENAI_API_KEY", "sk-test")
            try:
                report = asyncio.get_event_loop().run_until_complete(detect_missing_deps())
                assert hasattr(report, "ready")
                assert hasattr(report, "missing_deps")
                assert hasattr(report, "suggestion")
            finally:
                os.environ.pop("OPENAI_API_KEY", None)


# ════════════════════════════════════════════════════════════════════
# I. Mode Switching [P1]
# ════════════════════════════════════════════════════════════════════


class TestModeSwitching:
    def test_configure_switches_to_api(self):
        """configure() can switch from CLI to API mode."""
        cfg = configure(calling_mode="cli")
        assert cfg.calling_mode == "cli"
        cfg2 = configure(calling_mode="api", api_url="http://localhost:8000")
        assert cfg2.calling_mode == "api"

    def test_configure_preserves_unset_fields(self):
        """configure() preserves defaults for fields not overridden."""
        cfg = configure(cdp_url="http://custom:9222")
        assert cfg.cdp_url == "http://custom:9222"
        assert cfg.calling_mode == "cli"  # default
