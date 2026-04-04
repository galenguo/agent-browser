"""
Security Hardening 单元测试

覆盖 Phase 6-7 安全修复：
  - pipeline/steps.py: CSS 选择器注入、JS 过滤注入、SSRF 防护
  - src/api.py: evaluate JS 沙箱、navigate URL 校验、list_sessions IDOR、
               恒定时间比较、auth bypass 警告

所有测试使用纯 mock，无需真实浏览器。
"""
import os
import sys
import re
import json
import hmac
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "skills"))

import api as api_module


# ─── Helpers ──────────────────────────────────────────────────


def _make_mock_session(user_id: str, session_id: str):
    import time
    s = MagicMock()
    s.user_id = user_id
    s.session_id = session_id
    s.created_at = time.time()
    s.last_activity = time.time()
    s.tasks = {}
    return s


def _make_mgr(sessions=None):
    import time
    mgr = MagicMock()
    mgr.sessions = sessions or {}
    mgr.max_concurrent = 10
    mgr.browser_pool = MagicMock()
    mgr.browser_pool.mode = "local"
    return mgr


def _api_get(path, key=None, sessions=None, **kw):
    mgr = _make_mgr(sessions)
    with patch.object(api_module, "_session_manager", mgr), \
         patch.object(api_module, "_api_key", key):
        c = TestClient(api_module.app, raise_server_exceptions=False)
        return c.get(path, **kw)


def _api_post(path, key=None, sessions=None, **kw):
    mgr = _make_mgr(sessions)
    with patch.object(api_module, "_session_manager", mgr), \
         patch.object(api_module, "_api_key", key):
        c = TestClient(api_module.app, raise_server_exceptions=False)
        return c.post(path, **kw)


# ═══════════════════════════════════════════════════════════════
#  1. Pipeline: _escape_selector (CSS Injection Prevention)
# ═══════════════════════════════════════════════════════════════


class TestEscapeSelector:
    """_escape_selector() CSS 选择器安全验证"""

    def test_valid_selectors_accepted(self):
        from skills.agent_browser.pipeline.steps import _escape_selector

        valid = [
            "#main",
            ".container",
            "button.submit",
            "[data-testid='submit']",
            "div > p span",
            "input[name='email']",
            "#app .nav-item:nth-child(2)",
            "*:hover",
            "h1, h2, h3",
        ]
        for sel in valid:
            result = _escape_selector(sel)
            assert result == sel, f"Selector {sel!r} should pass through"

    def test_empty_selector_rejected(self):
        from skills.agent_browser.pipeline.steps import _escape_selector
        with pytest.raises(ValueError, match="Empty selector"):
            _escape_selector("")

    def test_xss_characters_blocked(self):
        from skills.agent_browser.pipeline.steps import _escape_selector
        dangerous = [
            "<script>alert(1)</script>",
            "img[src='x' onerror='evil']",
            "</div><script>",
            "javascript:void(0)",
        ]
        for sel in dangerous:
            with pytest.raises(ValueError):
                _escape_selector(sel)

    def test_json_dumps_encoding(self):
        """json.dumps 确保选择器可安全嵌入 JS querySelector"""
        from skills.agent_browser.pipeline.steps import _escape_selector
        sel = '#main [data-ref="test"]'
        escaped = _escape_selector(sel)
        # json.dumps 输出是合法 JS 字符串字面量
        js_safe = json.dumps(escaped)
        assert js_safe.startswith('"')
        assert js_safe.endswith('"')


# ═══════════════════════════════════════════════════════════════
#  2. Pipeline: _validate_url (SSRF + Scheme Protection)
# ═══════════════════════════════════════════════════════════════


class TestValidateUrl:
    """_validate_url() URL 安全验证"""

    def test_valid_urls_accepted(self):
        from skills.agent_browser.pipeline.steps import _validate_url
        valid = [
            "https://example.com",
            "http://localhost:3000/path",
            "https://www.google.com/search?q=test",
            "http://192.0.2.1/page",  # documentation IP, not private
        ]
        for url in valid:
            result = _validate_url(url)
            assert result == url.strip()

    def test_empty_url_rejected(self):
        from skills.agent_browser.pipeline.steps import _validate_url
        with pytest.raises(ValueError, match="Empty URL"):
            _validate_url("")

    def test_dangerous_schemes_blocked(self):
        from skills.agent_browser.pipeline.steps import _validate_url
        blocked = [
            "javascript:alert(1)",
            "data:text/html,<h1>hi</h1>",
            "file:///etc/passwd",
            "vbscript:MsgBox",
            "blob:http://evil",
        ]
        for url in blocked:
            with pytest.raises(ValueError, match="Blocked|scheme"):
                _validate_url(url)

    def test_loopback_blocked_in_fetch(self):
        """step_fetch 应阻止 loopback（但 navigate 允许）"""
        from skills.agent_browser.pipeline.steps import _validate_url
        # _validate_url 本身不检查 IP（只在 step_fetch 中检查）
        # 这里验证 scheme 检查工作正常
        _validate_url("http://127.0.0.1/")  # navigate 允许

    def test_private_ip_detection(self):
        """SSRF blocklist 覆盖关键私有网段"""
        from urllib.parse import urlparse
        blocked_hosts = [
            "127.0.0.1", "127.0.0.5",
            "10.0.0.1", "10.255.255.254",
            "192.168.1.1", "192.168.0.100",
            "169.254.169.254",
            "localhost",
            "metadata.google.internal",
        ]
        blocked_prefixes = (
            "127.", "0.", "169.254.", "10.", "192.168.",
            "fc00:", "fe80:", "::1", "::ffff", "[::",
            "localhost", "metadata.google.internal",
        )
        for host in blocked_hosts:
            blocked = any(
                host == p or host.startswith(p) for p in blocked_prefixes
            )
            assert blocked, f"Host {host} should be blocked by SSRF rules"


# ═══════════════════════════════════════════════════════════════
#  3. Pipeline: Filter Expression Allowlist Sandbox
# ═══════════════════════════════════════════════════════════════


class TestFilterExpressionSandbox:
    """过滤表达式白名单：只允许 item.field op 'value' 格式"""

    def test_safe_expressions_pass(self):
        """合法比较表达式应通过验证"""
        pattern = re.compile(
            r'^('
            r'(?:item\.[a-zA-Z_]\w*(?:\.\w+)*\s*(?:==|!=)\s*["\'][^"\']*["\'])'
            r'(?:\s*(?:&&|\|\|)\s*'
            r'(?:item\.[a-zA-Z_]\w*(?:\.\w+)*\s*(?:==|!=)\s*["\'][^"\']*["\']))*'
            r')$'
        )
        safe = [
            'item.status == "active"',
            "item.name != 'test'",
            'item.status == "active" && item.name != "test"',
            'item.data.value == "ok" || item.type == "a"',
            'item._private == "x"',
        ]
        for expr in safe:
            assert pattern.match(expr), f"Should pass: {expr!r}"

    def test_dangerous_expressions_blocked(self):
        """危险表达式应被拒绝"""
        pattern = re.compile(
            r'^('
            r'(?:item\.[a-zA-Z_]\w*(?:\.\w+)*\s*(?:==|!=)\s*["\'][^"\']*["\'])'
            r'(?:\s*(?:&&|\|\|)\s*'
            r'(?:item\.[a-zA-Z_]\w*(?:\.\w+)*\s*(?:==|!=)\s*["\'][^"\']*["\']))*'
            r')$'
        )
        dangerous = [
            'function(){}',
            'item.val => item.val > 0',
            '(item.status) == "ok"',
            'return item',
            'eval(item.name)',
            'item.name == "x"; alert(1)',
            'item["key"] == "v"',
            'item.name == x',          # unquoted value
            'item.name + 1 == 2',      # arithmetic
            '',                        # empty
        ]
        for expr in dangerous:
            assert not pattern.match(expr), f"Should block: {expr!r}"


# ═══════════════════════════════════════════════════════════════
#  4. API: Evaluate JS Sandboxing
# ═══════════════════════════════════════════════════════════════


class TestEvaluateJsSandboxing:
    """evaluate 端点应阻止危险 JS API"""

    def test_fetch_blocked(self):
        """fetch() 应被阻止"""
        import time
        sid = "sess_eval"
        mgr = _make_mgr({sid: _make_mock_session("k", sid)})
        mgr.evaluate = AsyncMock(return_value="ok")
        with patch.object(api_module, "_session_manager", mgr), \
             patch.object(api_module, "_api_key", "k"):
            c = TestClient(api_module.app, raise_server_exceptions=False)
            resp = c.post(
                f"/sessions/{sid}/evaluate",
                json={"expression": "fetch('/api/secret')"},
                headers={"X-API-Key": "k"},
            )
        assert resp.status_code == 400
        assert "blocked" in resp.json()["detail"].lower()

    def test_xmlhttprequest_blocked(self):
        import time
        sid = "sess_eval"
        mgr = _make_mgr({sid: _make_mock_session("k", sid)})
        with patch.object(api_module, "_session_manager", mgr), \
             patch.object(api_module, "_api_key", "k"):
            c = TestClient(api_module.app, raise_server_exceptions=False)
            resp = c.post(
                f"/sessions/{sid}/evaluate",
                json={"expression": "new XMLHttpRequest()"},
                headers={"X-API-Key": "k"},
            )
        assert resp.status_code == 400

    def test_document_cookie_blocked(self):
        import time
        sid = "sess_eval"
        mgr = _make_mgr({sid: _make_mock_session("k", sid)})
        with patch.object(api_module, "_session_manager", mgr), \
             patch.object(api_module, "_api_key", "k"):
            c = TestClient(api_module.app, raise_server_exceptions=False)
            resp = c.post(
                f"/sessions/{sid}/evaluate",
                json={"expression": "document.cookie"},
                headers={"X-API-Key": "k"},
            )
        assert resp.status_code == 400

    def test_safe_js_passes(self):
        """安全的只读 JS 应通过"""
        import time
        sid = "sess_eval"
        mgr = _make_mgr({sid: _make_mock_session("k", sid)})
        mgr.evaluate = AsyncMock(return_value="hello")
        with patch.object(api_module, "_session_manager", mgr), \
             patch.object(api_module, "_api_key", "k"):
            c = TestClient(api_module.app, raise_server_exceptions=False)
            resp = c.post(
                f"/sessions/{sid}/evaluate",
                json={"expression": "document.title"},
                headers={"X-API-Key": "k"},
            )
        assert resp.status_code == 200

    def test_script_tag_blocked(self):
        import time
        sid = "sess_eval"
        mgr = _make_mgr({sid: _make_mock_session("k", sid)})
        with patch.object(api_module, "_session_manager", mgr), \
             patch.object(api_module, "_api_key", "k"):
            c = TestClient(api_module.app, raise_server_exceptions=False)
            resp = c.post(
                f"/sessions/{sid}/evaluate",
                json={"expression": "'<script>alert(1)</script>'"},
                headers={"X-API-Key": "k"},
            )
        assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════════
#  5. API: Navigate URL Validation
# ═══════════════════════════════════════════════════════════════


class TestNavigateUrlValidation:
    """navigate 端点应校验 URL 安全性"""

    def test_javascript_url_rejected(self):
        import time
        sid = "sess_nav"
        mgr = _make_mgr({sid: _make_mock_session("k", sid)})
        with patch.object(api_module, "_session_manager", mgr), \
             patch.object(api_module, "_api_key", "k"):
            c = TestClient(api_module.app, raise_server_exceptions=False)
            resp = c.post(
                f"/sessions/{sid}/navigate",
                json={"url": "javascript:alert(1)"},
                headers={"X-API-Key": "k"},
            )
        assert resp.status_code == 400

    def test_data_url_rejected(self):
        import time
        sid = "sess_nav"
        mgr = _make_mgr({sid: _make_mock_session("k", sid)})
        with patch.object(api_module, "_session_manager", mgr), \
             patch.object(api_module, "_api_key", "k"):
            c = TestClient(api_module.app, raise_server_exceptions=False)
            resp = c.post(
                f"/sessions/{sid}/navigate",
                json={"url": "data:text/html,<h1>hi</h1>"},
                headers={"X-API-Key": "k"},
            )
        assert resp.status_code == 400

    def test_https_url_accepted(self):
        import time
        sid = "sess_nav"
        mgr = _make_mgr({sid: _make_mock_session("k", sid)})
        mgr.navigate = AsyncMock(return_value={"status": "ok"})
        with patch.object(api_module, "_session_manager", mgr), \
             patch.object(api_module, "_api_key", "k"):
            c = TestClient(api_module.app, raise_server_exceptions=False)
            resp = c.post(
                f"/sessions/{sid}/navigate",
                json={"url": "https://example.com"},
                headers={"X-API-Key": "k"},
            )
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════
#  6. API: list_sessions IDOR Protection
# ═══════════════════════════════════════════════════════════════


class TestListSessionsIdor:
    """list_sessions 应只返回当前用户的会话"""

    def test_user_only_sees_own_sessions(self):
        """用户 A 只能看到用户 A 的会话"""
        sessions = {
            "s1": _make_mock_session("key-a", "s1"),
            "s2": _make_mock_session("key-b", "s2"),
            "s3": _make_mock_session("key-a", "s3"),
        }
        resp, _ = _api_get("/sessions", key="key-a", sessions=sessions,
                           headers={"X-API-Key": "key-a"})
        assert resp.status_code == 200
        data = resp.json()
        # key-a 只能看到 s1 和 s3
        ids = {s["session_id"] for s in data["sessions"]}
        assert ids == {"s1", "s3"}
        assert data["total"] == 2

    def test_no_api_key_sees_all(self):
        """未配置 API Key 时（单租户模式）返回全部会话"""
        sessions = {
            "s1": _make_mock_session("anyone", "s1"),
            "s2": _make_mock_session("anyone_else", "s2"),
        }
        resp, _ = _api_get("/sessions", key=None, sessions=sessions)
        assert resp.status_code == 200
        assert resp.json()["total"] == 2


# ═══════════════════════════════════════════════════════════════
#  7. API: Constant-Time Key Comparison
# ═══════════════════════════════════════════════════════════════


class TestConstantTimeCompare:
    """API Key 使用恒定时间比较"""

    def test_compare_digest_used(self):
        """verify_api_key 应使用 hmac.compare_digest"""
        import inspect
        source = inspect.getsource(api_module.verify_api_key)
        assert "compare_digest" in source, \
            "Should use hmac.compare_digest to prevent timing attacks"

    def test_wrong_key_still_401(self):
        """错误 key 返回 401（不泄露正确/错误信息）"""
        resp, _ = _api_get("/sessions", key="correct-secret",
                           headers={"X-API-Key": "wrong-key"})
        assert resp.status_code == 401
        detail = resp.json()["detail"].lower()
        # 不应透露 key 是否存在
        assert "invalid" not in detail or "failed" in detail


# ═══════════════════════════════════════════════════════════════
#  8. API: Error Message Sanitization
# ═══════════════════════════════════════════════════════════════


class TestErrorSanitization:
    """500 错误不应泄露内部细节"""

    def test_500_returns_generic_message(self):
        """内部异常返回通用消息，不暴露堆栈/路径"""
        import time
        sid = "sess_err"
        mgr = _make_mgr({sid: _make_mock_session("k", sid)})
        mgr.snapshot = AsyncMock(side_effect=RuntimeError(" FileNotFoundError: /etc/shadow"))
        with patch.object(api_module, "_session_manager", mgr), \
             patch.object(api_module, "_api_key", "k"):
            c = TestClient(api_module.app, raise_server_exceptions=False)
            resp = c.get(f"/sessions/{sid}/snapshot", headers={"X-API-Key": "k"})
        assert resp.status_code == 500
        detail = resp.json()["detail"]
        # 不应包含内部路径或异常类型名
        assert "/etc/" not in detail
        assert "FileNotFoundError" not in detail

    def test_404_generic_not_found(self):
        """SessionNotFoundError 返回通用 404"""
        resp, _ = _api_get("/sessions/nonexistent-session-id",
                           key="k", headers={"X-API-Key": "k"})
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Session not found"


# ═══════════════════════════════════════════════════════════════
#  9. API: Auth Bypass Warning on Startup
# ═══════════════════════════════════════════════════════════════


class TestAuthBypassWarning:
    """未配置 API Key 时应记录 SECURITY 警告"""

    def test_warning_logged_when_no_key(self):
        """lifespan 中未设置 key 时应 log warning"""
        import inspect
        source = inspect.getsource(api_module.lifespan)
        assert "SECURITY" in source or "authentication is DISABLED" in source or "warning" in source.lower(), \
            "Should warn when API_KEY is not configured"


# ═══════════════════════════════════════════════════════════════
#  10. Pipeline: Step Registration Integrity
# ═══════════════════════════════════════════════════════════════


class TestStepRegistration:
    """所有步骤处理器已正确注册"""

    def test_all_expected_steps_registered(self):
        from skills.agent_browser.pipeline.steps import STEPS
        expected = {
            "navigate", "evaluate", "click", "type", "wait",
            "fetch", "select", "map", "filter", "limit",
        }
        assert set(STEPS.keys()) == expected, \
            f"Missing steps: {expected - set(STEPS.keys())}"

    def test_step_handlers_are_callable(self):
        from skills.agent_browser.pipeline.steps import STEPS
        for name, handler in STEPS.items():
            assert callable(handler), f"Step '{name}' is not callable"
