"""模式2测试：远程CDP连接"""

import pytest

from stealth_browser.main import create_session, open_page, snapshot


@pytest.mark.asyncio
async def test_remote_cdp_zhipin():
    """远程CDP - Boss直聘登录"""
    # 连接远程Docker浏览器
    session_id = await create_session("ws://localhost:19222")
    assert session_id is not None

    await open_page(session_id, "https://www.zhipin.com")
    snap = await snapshot(session_id, interactive_only=True)

    assert len(snap["elements"]) > 0
    assert "zhipin" in snap["url"]


@pytest.mark.asyncio
async def test_remote_cdp_xiaohongshu():
    """远程CDP - 小红书数据提取"""
    session_id = await create_session("ws://localhost:19222")

    await open_page(session_id, "https://www.xiaohongshu.com")
    snap = await snapshot(session_id)

    # 验证反检测有效
    assert "xiaohongshu" in snap["url"]
    assert len(snap["elements"]) > 0
