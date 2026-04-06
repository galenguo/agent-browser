"""
StealthMiddleware + StealthPageHandle 单元测试

覆盖：
  - 熔断器状态机（CLOSED → OPEN，per-session 隔离）
  - StealthPageHandle 操作分类（隐匿包装 vs 透传）
  - RemotePageHandle 兼容性（无 raw_page 时降级）
  - total_timeout 超时控制
  - ref 格式验证回归
  - stealth_mode 配置选项
"""
import asyncio
import pytest
from unittest import mock
from unittest.mock import AsyncMock, MagicMock, PropertyMock

# ── Fixtures ───────────────────────────────────────────────


@pytest.fixture
def mock_config():
    """默认 SkillConfig（stealth ON）"""
    cfg = mock.MagicMock()
    cfg.stealth_enabled = True
    cfg.stealth_mode = "full"
    cfg.cdp_url = "http://127.0.0.1:19222"
    cfg.daemon_enabled = False
    return cfg


@pytest.fixture
def mock_backend():
    """Mock BrowserBackend"""
    backend = mock.MagicMock()
    backend.connect = AsyncMock()
    backend.disconnect = AsyncMock()
    backend.is_connected = AsyncMock(return_value=True)

    # Mock page handle
    page_handle = MagicMock()
    page_handle.goto = AsyncMock()
    page_handle.go_back = AsyncMock()
    page_handle.evaluate = AsyncMock(return_value=None)
    page_handle.wait_for_selector = AsyncMock()
    page_handle.mouse_wheel = AsyncMock()
    page_handle.mouse_move = AsyncMock()
    page_handle.keyboard_press = AsyncMock()
    page_handle.title = AsyncMock(return_value="Test Page")
    page_handle.url = AsyncMock(return_value="http://example.com")
    page_handle.on = AsyncMock()
    page_handle.remove_listener = mock.MagicMock()
    page_handle.close = AsyncMock()

    # Expose raw_page (LocalCDPBackend style)
    raw_page = MagicMock()
    raw_page.viewport_size = {"width": 1920, "height": 1080}
    raw_page.add_init_script = AsyncMock()
    raw_page.mouse = MagicMock()
    raw_page.mouse.move = AsyncMock()
    type(page_handle).raw_page = PropertyMock(return_value=raw_page)

    backend.create_session = AsyncMock(return_value=page_handle)
    backend.delete_session = AsyncMock()
    backend.get_page = AsyncMock(return_value=page_handle)

    return backend, page_handle, raw_page


@pytest.fixture
def remote_mock_backend():
    """Mock BrowserBackend — RemoteAPIBackend 风格（无 raw_page）"""
    backend = mock.MagicMock()
    backend.connect = AsyncMock()
    backend.disconnect = AsyncMock()

    page_handle = MagicMock()
    page_handle.goto = AsyncMock()
    page_handle.evaluate = AsyncMock(return_value=None)
    page_handle.close = AsyncMock()
    # RemotePageHandle 没有 raw_page 属性
    del page_handle.raw_page

    backend.create_session = AsyncMock(return_value=page_handle)
    backend.delete_session = AsyncMock()
    backend.get_page = AsyncMock(return_value=page_handle)

    return backend, page_handle


# ── Circuit Breaker Tests ────────────────────────────────────


class TestCircuitBreaker:
    """Per-session circuit breaker state machine"""

    @pytest.mark.asyncio
    async def test_circuit_starts_closed(self):
        from agent_browser.stealth.middleware import _PerSessionCircuit

        circuit = _PerSessionCircuit(threshold=5)
        assert circuit.state.name == "CLOSED"
        assert circuit.is_active is True
        assert circuit.failure_count == 0

    @pytest.mark.asyncio
    async def test_circuit_opens_after_threshold(self):
        from agent_browser.stealth.middleware import _PerSessionCircuit

        circuit = _PerSessionCircuit(threshold=5)
        for i in range(5):
            opened = circuit.record_failure()
            if i < 4:
                assert opened is False
                assert circuit.is_active is True
            else:
                # 第 5 次失败触发熔断
                assert opened is True
                assert circuit.is_active is False
                assert circuit.state.name == "OPEN"

    @pytest.mark.asyncio
    async def test_circuit_per_session_isolation(self):
        """不同 session 的熔断状态互不影响"""
        from agent_browser.stealth.middleware import _PerSessionCircuit

        c1 = _PerSessionCircuit(threshold=3)
        c2 = _PerSessionCircuit(threshold=3)

        # session 1 触发熔断
        for _ in range(3):
            c1.record_failure()
        assert c1.is_active is False

        # session 2 不受影响
        assert c2.is_active is True
        assert c2.failure_count == 0


# ── StealthMiddleware Tests ─────────────────────────────────


class TestStealthMiddleware:
    """StealthMiddleware 核心功能"""

    @pytest.mark.asyncio
    async def test_create_session_wraps_with_stealth(self, mock_config, mock_backend):
        from agent_browser.stealth.middleware import StealthMiddleware

        backend, page_handle, raw_page = mock_backend
        mw = StealthMiddleware(backend, mock_config)

        result = await mw.create_session("test_session")

        # 应返回 StealthPageHandle（不是原始 handle）
        from agent_browser.stealth.middleware import StealthPageHandle
        assert isinstance(result, StealthPageHandle)
        assert result._wrapped is page_handle
        assert result._raw_page is raw_page

        # 定时器噪声应被注入
        raw_page.add_init_script.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_session_fallback_on_stealth_failure(self, mock_config, mock_backend):
        from agent_browser.stealth.middleware import StealthMiddleware

        backend, page_handle, raw_page = mock_backend
        # 注入噪声时抛异常
        raw_page.add_init_script.side_effect = RuntimeError("inject failed")

        mw = StealthMiddleware(backend, mock_config)
        result = await mw.create_session("test_session")

        # 降级：返回原始未包装的 handle
        assert result is page_handle
        # 熔断计数应增加
        assert mw._circuits["test_session"].failure_count >= 1

    @pytest.mark.asyncio
    async def test_stealth_off_returns_raw_handle(self, mock_backend):
        """stealth_enabled=False 时返回原始 handle（零开销）"""
        from agent_browser.stealth.middleware import StealthMiddleware

        cfg = mock.MagicMock()
        cfg.stealth_enabled = False
        backend, page_handle, _ = mock_backend

        mw = StealthMiddleware(backend, cfg)
        result = await mw.create_session("test_session")

        assert result is page_handle  # 原始 handle，无包装

    @pytest.mark.asyncio
    async def test_delete_session_cleans_circuit(self, mock_config, mock_backend):
        from agent_browser.stealth.middleware import StealthMiddleware

        backend, _, _ = mock_backend
        mw = StealthMiddleware(backend, mock_config)
        await mw.create_session("test_session")

        assert "test_session" in mw._circuits
        await mw.delete_session("test_session")
        assert "test_session" not in mw._circuits

    @pytest.mark.asyncio
    async def test_connect_disconnect_delegate(self, mock_config, mock_backend):
        from agent_browser.stealth.middleware import StealthMiddleware

        backend, _, _ = mock_backend
        mw = StealthMiddleware(backend, mock_config)

        await mw.connect()
        backend.connect.assert_awaited_once()

        await mw.disconnect()
        backend.disconnect.assert_awaited_once()


# ── StealthPageHandle Tests ─────────────────────────────────


class TestStealthPageHandle:
    """StealthPageHandle 操作分类测试"""

    @pytest.mark.asyncio
    async def test_goto_has_stealth_delays(self, mock_config):
        """goto 操作应有 pre_action(navigate) + post_action(navigate)"""
        from agent_browser.stealth.middleware import StealthPageHandle, _PerSessionCircuit

        wrapped = MagicMock()
        wrapped.goto = AsyncMock()
        raw_page = MagicMock()
        type(wrapped).raw_page = PropertyMock(return_value=raw_page)

        stealth = mock.MagicMock()
        stealth.pre_action = AsyncMock()
        stealth.post_action = AsyncMock()
        circuit = _PerSessionCircuit()

        handle = StealthPageHandle(wrapped, stealth, circuit)
        await handle.goto("http://example.com")

        stealth.pre_action.assert_called_once_with("navigate")
        wrapped.goto.assert_called_once_with(
            "http://example.com", wait_until="domcontentloaded", timeout=8000
        )
        stealth.post_action.assert_called_once_with("navigate")

    @pytest.mark.asyncio
    async def test_evaluate_is_passthrough(self, mock_config):
        """evaluate 是透传操作（无隐匿延迟）"""
        from agent_browser.stealth.middleware import StealthPageHandle, _PerSessionCircuit

        wrapped = MagicMock()
        wrapped.evaluate = AsyncMock(return_value=42)
        stealth = mock.MagicMock()
        stealth.pre_action = AsyncMock()
        circuit = _PerSessionCircuit()

        handle = StealthPageHandle(wrapped, stealth, circuit)
        result = await handle.evaluate("1+1")

        assert result == 42
        stealth.pre_action.assert_not_called()  # 透传，无 pre_action

    @pytest.mark.asyncio
    async def test_keyboard_press_has_stealth(self, mock_config):
        """keyboard_press 有 pre_action(input) + post_action(input)"""
        from agent_browser.stealth.middleware import StealthPageHandle, _PerSessionCircuit

        wrapped = MagicMock()
        wrapped.keyboard_press = AsyncMock()
        stealth = mock.MagicMock()
        stealth.pre_action = AsyncMock()
        stealth.post_action = AsyncMock()
        circuit = _PerSessionCircuit()

        handle = StealthPageHandle(wrapped, stealth, circuit)
        await handle.keyboard_press("Enter")

        stealth.pre_action.assert_called_once_with("input")
        wrapped.keyboard_press.assert_called_once_with("Enter")
        stealth.post_action.assert_called_once_with("input")

    @pytest.mark.asyncio
    async def test_mouse_move_calls_random_mouse_move(self, mock_config):
        """mouse_move 应调用 stealth.random_mouse_move（贝塞尔曲线）"""
        from agent_browser.stealth.middleware import StealthPageHandle, _PerSessionCircuit

        wrapped = MagicMock()
        wrapped.mouse_move = AsyncMock()
        raw_page = MagicMock()
        type(wrapped).raw_page = PropertyMock(return_value=raw_page)

        stealth = mock.MagicMock()
        stealth.random_mouse_move = AsyncMock()
        circuit = _PerSessionCircuit()

        handle = StealthPageHandle(wrapped, stealth, circuit)
        await handle.mouse_move(100, 200)

        stealth.random_mouse_move.assert_called_once_with(raw_page)
        wrapped.mouse_move.assert_called_once_with(100, 200)

    @pytest.mark.asyncio
    async def test_circuit_open_disables_stealth(self, mock_config):
        """熔断 OPEN 后，操作不再有隐匿延迟"""
        from agent_browser.stealth.middleware import StealthPageHandle, _PerSessionCircuit

        wrapped = MagicMock()
        wrapped.goto = AsyncMock()
        stealth = mock.MagicMock()
        stealth.pre_action = AsyncMock()
        circuit = _PerSessionCircuit(threshold=2)

        handle = StealthPageHandle(wrapped, stealth, circuit)

        # 触发熔断
        circuit.record_failure()
        circuit.record_failure()
        assert circuit.is_active is False

        # 再次调用 goto — 不应有隐匿延迟
        await handle.goto("http://example.com")
        stealth.pre_action.assert_not_called()  # 熔断开启，跳过隐匿
        wrapped.goto.assert_called_once()  # 但操作本身仍执行

    @pytest.mark.asyncio
    async def test_remote_handle_no_raw_page_safe(self, mock_config):
        """RemotePageHandle 无 raw_page 时不应崩溃"""
        from agent_browser.stealth.middleware import StealthPageHandle, _PerSessionCircuit

        wrapped = MagicMock()
        wrapped.goto = AsyncMock()
        # 无 raw_page 属性（模拟 RemotePageHandle）
        if hasattr(wrapped, "raw_page"):
            delattr(wrapped, "raw_page")

        stealth = mock.MagicMock()
        stealth.pre_action = AsyncMock()
        stealth.post_action = AsyncMock()
        circuit = _PerSessionCircuit()

        handle = StealthPageHandle(wrapped, stealth, circuit)

        # 不应抛 AttributeError
        await handle.goto("http://example.com")
        stealth.pre_action.assert_called_once()
        wrapped.goto.assert_called_once()

        # mouse_move 在无 raw_page 时直接透传
        wrapped.mouse_move = AsyncMock()
        await handle.mouse_move(50, 50)
        stealth.random_mouse_move.assert_not_called()  # 无 raw_page，跳过鼠标游走
        wrapped.mouse_move.assert_called_once_with(50, 50)


# ── Regression Tests ─────────────────────────────────────────


class TestRegressionFixes:
    """已修复 bug 的回归测试"""

    @pytest.mark.asyncio
    async def test_ref_validation_rejects_injection(self):
        """ref 格式验证：拒绝 CSS 选择器注入"""
        from agent_browser.main import _validate_ref

        # 合法格式
        _validate_ref("@e0")
        _validate_ref("@e12")
        _validate_ref("@e999")

        # 非法格式 — 应抛 ValueError
        bad_refs = [
            '@e0"]); evil;//',
            '@e0" or "1"="1',
            "not_a_ref",
            "",
            "@e",
            "@e-1",
            "@eabc",
            "<script>alert(1)</script>",
        ]
        for ref in bad_refs:
            with pytest.raises(ValueError, match="Invalid ref"):
                _validate_ref(ref)

    @pytest.mark.asyncio
    async def test_json_dumps_escapes_text_safely(self):
        """json.dumps 正确转义特殊字符（防止 JS 注入）"""
        import json

        dangerous_texts = [
            "'; alert(document.cookie); //",
            "hello\nworld",  # 换行符
            "text'text",  # 单引号
            'text"text',  # 双引号
            "\\backslash",  # 反斜杠
        ]
        for text in dangerous_texts:
            escaped = json.dumps(text)
            # json.dumps 输出是合法 JS 字符串字面量
            assert escaped.startswith('"')
            assert escaped.endswith('"')

    @pytest.mark.asyncio
    async def test_total_timeout_parameter_exists(self):
        """run_task 签名包含 total_timeout 参数"""
        from inspect import signature
        from agent_browser.browser.local import LocalCDPBackend

        sig = signature(LocalCDPBackend.run_task)
        params = list(sig.parameters.keys())
        assert "total_timeout" in params
        assert sig.parameters["total_timeout"].default == 300.0

    @pytest.mark.asyncio
    async def test_stealth_mode_config_option(self):
        """SkillConfig 包含 stealth_mode 字段"""
        from agent_browser.config import SkillConfig

        cfg = SkillConfig()
        assert hasattr(cfg, "stealth_mode")
        assert cfg.stealth_mode in ("full", "vanilla")
        assert cfg.stealth_enabled is True  # 默认启用

    @pytest.mark.asyncio
    async def test_middleware_exports(self):
        """agent_browser.stealth 模块正确导出核心类"""
        from agent_browser.stealth import StealthMiddleware, StealthPageHandle, CircuitState

        assert StealthMiddleware is not None
        assert StealthPageHandle is not None
        assert CircuitState is not None
        assert CircuitState.CLOSED.value == "closed"
        assert CircuitState.OPEN.value == "open"
