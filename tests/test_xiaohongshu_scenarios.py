"""小红书场景测试"""
import pytest

from agent_browser.main import create_session, open_page, snapshot


@pytest.mark.asyncio
async def test_xiaohongshu_homepage():
    """小红书首页浏览"""
    session_id = await create_session()
    await open_page(session_id, "https://www.xiaohongshu.com")

    snap = await snapshot(session_id)
    assert "xiaohongshu" in snap["url"]
    assert len(snap["elements"]) > 0


@pytest.mark.asyncio
async def test_xiaohongshu_anti_detection():
    """小红书反检测验证"""
    session_id = await create_session()
    await open_page(session_id, "https://www.xiaohongshu.com")

    snap = await snapshot(session_id, interactive_only=True)

    # 验证页面正常加载，未被检测
    assert len(snap["elements"]) > 10
    assert snap.get("error") is None


@pytest.mark.asyncio
async def test_xiaohongshu_extract_notes():
    """小红书笔记提取"""
    session_id = await create_session()
    await open_page(session_id, "https://www.xiaohongshu.com")

    snap = await snapshot(session_id)

    # 提取笔记元素
    notes = [e for e in snap["elements"] if "笔记" in e.get("text", "")]
    assert len(notes) > 0
