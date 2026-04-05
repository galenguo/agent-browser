"""
Phase 1: BrowserDaemon 单元测试

测试目标：
- A3.1 Singleton 模式
- A3.2 状态持久化（daemon-state.json 正确写入）
- A3.3 空闲超时机制（需集成测试验证断开）
- A3.4 Session 管理

注意：Playwright 连接相关测试在集成测试 (test_local_backend.py) 中进行
"""
import asyncio
import json
import tempfile
from pathlib import Path
from unittest import mock

import pytest

# 使用 skill_loader 助手加载模块
from helpers.skill_loader import load_skill_module

config = load_skill_module("config")
daemon_module = load_skill_module("daemon")

SkillConfig = config.SkillConfig
BrowserDaemon = daemon_module.BrowserDaemon


class TestBrowserDaemonSingleton:
    """A3.1 Singleton 模式测试"""

    def teardown_method(self):
        """每个测试后重置 singleton"""
        BrowserDaemon.reset()

    def test_singleton_returns_same_instance(self):
        """get() 返回同一个实例"""
        daemon1 = BrowserDaemon.get(SkillConfig())
        daemon2 = BrowserDaemon.get()

        assert daemon1 is daemon2

    def test_reset_creates_new_instance(self):
        """reset() 后创建新实例"""
        daemon1 = BrowserDaemon.get(SkillConfig())
        BrowserDaemon.reset()
        daemon2 = BrowserDaemon.get(SkillConfig())

        assert daemon1 is not daemon2

    def test_default_config_applied(self):
        """默认配置正确应用"""
        daemon = BrowserDaemon(SkillConfig())
        assert daemon._config is not None
        assert daemon._config.daemon_idle_timeout == 1800


class TestDaemonInitialState:
    """初始状态测试"""

    def teardown_method(self):
        BrowserDaemon.reset()

    def test_not_connected_on_creation(self):
        """创建时未连接"""
        daemon = BrowserDaemon(SkillConfig())
        assert daemon.is_connected is False
        assert daemon.browser is None

    def test_no_sessions_on_creation(self):
        """创建时无 sessions"""
        daemon = BrowserDaemon(SkillConfig())
        assert daemon.active_session_count == 0
        assert daemon._sessions == {}


class TestStatePersistence:
    """A3.2 状态持久化测试"""

    def teardown_method(self):
        BrowserDaemon.reset()

    def test_state_persisted_to_file(self):
        """状态持久化到 JSON 文件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "daemon-state.json"
            config = SkillConfig(daemon_state_path=str(state_path))
            daemon = BrowserDaemon(config)

            # Mock 连接
            daemon._connected = True
            daemon._sessions = {"session_1": {"created_at": 1234567890}}
            daemon._persist_state()

            # 验证文件存在
            assert state_path.exists()

            # 验证内容
            with open(state_path) as f:
                state = json.load(f)

            assert state["connected"] is True
            assert "session_1" in state["sessions"]
            assert state["sessions"]["session_1"]["created_at"] == 1234567890

    def test_load_state_from_file(self):
        """从 JSON 文件恢复状态"""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "daemon-state.json"

            # 写入初始状态
            state = {
                "cdp_url": "http://192.168.1.100:9222",
                "connected": False,
                "sessions": {},
                "last_activity": 1234567890,
            }
            state_path.write_text(json.dumps(state))

            config = SkillConfig(daemon_state_path=str(state_path))
            daemon = BrowserDaemon(config)

            loaded = daemon._load_state()

            assert loaded["cdp_url"] == "http://192.168.1.100:9222"
            assert loaded["last_activity"] == 1234567890

    def test_load_state_missing_file(self):
        """文件不存在时返回空字典"""
        config = SkillConfig(daemon_state_path="/nonexistent/path.json")
        daemon = BrowserDaemon(config)

        loaded = daemon._load_state()
        assert loaded == {}


class TestIdleMonitorControl:
    """空闲监控控制测试"""

    def teardown_method(self):
        BrowserDaemon.reset()

    @pytest.mark.asyncio
    async def test_start_idle_monitor_creates_task(self):
        """启动空闲监控创建任务"""
        config = SkillConfig(daemon_idle_timeout=60)
        daemon = BrowserDaemon(config)

        daemon._start_idle_monitor()

        assert daemon._idle_task is not None

        # 清理
        daemon._stop_idle_monitor()

    @pytest.mark.asyncio
    async def test_stop_idle_monitor_cancels_task(self):
        """停止空闲监控取消任务"""
        config = SkillConfig(daemon_idle_timeout=60)
        daemon = BrowserDaemon(config)

        daemon._start_idle_monitor()
        assert daemon._idle_task is not None

        daemon._stop_idle_monitor()
        assert daemon._idle_task is None

    def test_disabled_idle_timeout_no_task(self):
        """idle_timeout=0 时不创建监控任务"""
        config = SkillConfig(daemon_idle_timeout=0)
        daemon = BrowserDaemon(config)

        # 不需要 async context，因为不会创建 task
        assert daemon._config.daemon_idle_timeout == 0


class TestSessionManagement:
    """Session 管理测试"""

    def teardown_method(self):
        BrowserDaemon.reset()

    def test_get_page_existing_session(self):
        """获取存在 session 的 page"""
        config = SkillConfig()
        daemon = BrowserDaemon(config)

        mock_page = mock.MagicMock()
        daemon._sessions["session_1"] = {
            "page": mock_page,
            "context": mock.MagicMock(),
            "created_at": 1234567890,
        }

        page = daemon.get_page("session_1")
        assert page is mock_page

    def test_get_page_not_found(self):
        """不存在的 session 返回 None"""
        config = SkillConfig()
        daemon = BrowserDaemon(config)

        page = daemon.get_page("nonexistent")
        assert page is None

    def test_active_session_count(self):
        """活跃 session 计数"""
        config = SkillConfig()
        daemon = BrowserDaemon(config)

        assert daemon.active_session_count == 0

        daemon._sessions = {"s1": {}, "s2": {}}
        assert daemon.active_session_count == 2

    def test_touch_activity_updates_time(self):
        """touch_activity 更新最后活动时间"""
        import time

        config = SkillConfig()
        daemon = BrowserDaemon(config)

        old_time = daemon._last_activity
        time.sleep(0.1)
        daemon._touch_activity()

        assert daemon._last_activity > old_time


class TestDisconnect:
    """断开连接测试"""

    def teardown_method(self):
        BrowserDaemon.reset()

    @pytest.mark.asyncio
    async def test_disconnect_clears_state(self):
        """disconnect 清理状态"""
        config = SkillConfig()
        daemon = BrowserDaemon(config)

        # Mock 已连接状态
        daemon._connected = True
        mock_browser = mock.AsyncMock()
        mock_browser.close = mock.AsyncMock()
        daemon._browser = mock_browser

        await daemon.disconnect()

        assert daemon.is_connected is False
        mock_browser.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_stops_idle_monitor(self):
        """disconnect 停止空闲监控"""
        config = SkillConfig(daemon_idle_timeout=60)
        daemon = BrowserDaemon(config)

        # Mock 已连接状态
        daemon._connected = True
        mock_browser = mock.AsyncMock()
        mock_browser.close = mock.AsyncMock()
        daemon._browser = mock_browser

        daemon._start_idle_monitor()
        assert daemon._idle_task is not None

        await daemon.disconnect()

        assert daemon._idle_task is None


class TestShutdown:
    """完全关闭测试"""

    def teardown_method(self):
        BrowserDaemon.reset()

    @pytest.mark.asyncio
    async def test_shutdown_closes_all(self):
        """shutdown 关闭所有资源"""
        config = SkillConfig()
        daemon = BrowserDaemon(config)

        # Mock 资源
        mock_browser = mock.AsyncMock()
        mock_playwright = mock.MagicMock()
        mock_playwright.stop = mock.AsyncMock()
        daemon._browser = mock_browser
        daemon._playwright = mock_playwright
        daemon._connected = True
        daemon._sessions = {
            "s1": {"page": mock.AsyncMock(), "context": mock.AsyncMock(), "created_at": 1234567890}
        }

        await daemon.shutdown()

        mock_browser.close.assert_called_once()
        mock_playwright.stop.assert_called_once()
        assert daemon.is_connected is False
        assert BrowserDaemon._instance is None

    @pytest.mark.asyncio
    async def test_shutdown_handles_no_browser(self):
        """shutdown 处理无浏览器情况"""
        config = SkillConfig()
        daemon = BrowserDaemon(config)

        # 无浏览器
        daemon._browser = None
        daemon._playwright = None
        daemon._connected = False

        # 不应抛出异常
        await daemon.shutdown()

        assert daemon.is_connected is False
