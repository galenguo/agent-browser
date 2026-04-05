"""测试 BrowserController"""
import pytest
from agent_browser.stealth.browser_controller import BrowserController


@pytest.mark.asyncio
async def test_create_session():
    """测试创建会话"""
    controller = BrowserController()
    session = await controller.create_session("test-1", "ws://127.0.0.1:19222")
    assert session.session_id == "test-1"
    await controller.delete_session("test-1")


@pytest.mark.asyncio
async def test_snapshot():
    """测试快照"""
    controller = BrowserController()
    await controller.create_session("test-2", "ws://127.0.0.1:19222")
    await controller.open("test-2", "https://example.com")
    snapshot = await controller.snapshot("test-2")
    assert "url" in snapshot
    assert "elements" in snapshot
    await controller.delete_session("test-2")
