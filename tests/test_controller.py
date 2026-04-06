"""Tests for BrowserController and ActionResult."""
from unittest.mock import MagicMock

from agent_browser.stealth.browser_controller import ActionResult, BrowserController


class TestActionResult:
    def test_default_ok(self):
        result = ActionResult()
        assert result.status == "ok"
        assert result.error is None
        assert result.data is None

    def test_to_dict_minimal(self):
        result = ActionResult()
        d = result.to_dict()
        assert d == {"status": "ok"}

    def test_to_dict_with_error(self):
        result = ActionResult(error="element not found")
        d = result.to_dict()
        assert d["status"] == "ok"
        assert d["error"] == "element not found"

    def test_to_dict_with_data(self):
        result = ActionResult(data={"url": "https://example.com"})
        d = result.to_dict()
        assert d["data"]["url"] == "https://example.com"

    def test_to_dict_full(self):
        result = ActionResult(
            status="error",
            error="timeout",
            data={"retry_after": 5},
        )
        d = result.to_dict()
        assert d["status"] == "error"
        assert d["error"] == "timeout"
        assert d["data"]["retry_after"] == 5


class TestBrowserController:
    def test_init_requires_args(self):
        """BrowserController requires browser_session and session_id."""
        mock_session = MagicMock()
        ctrl = BrowserController(browser_session=mock_session, session_id="test-1")
        assert ctrl.session_id == "test-1"
        assert ctrl.session is mock_session

    def test_session_property(self):
        mock_session = MagicMock()
        ctrl = BrowserController(browser_session=mock_session, session_id="s1")
        assert ctrl.session is mock_session
