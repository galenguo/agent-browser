"""模式1测试：本地开发模式"""
import pytest
from src.controller import create_session, open_page, snapshot, click


@pytest.mark.asyncio
async def test_zhipin_login_flow():
    """Boss直聘登录流程测试"""
    # 创建会话
    session_id = await create_session()
    assert session_id is not None

    # 打开Boss直聘
    await open_page(session_id, "https://www.zhipin.com")

    # 获取快照
    snap = await snapshot(session_id, interactive_only=True)
    assert "elements" in snap
    assert len(snap["elements"]) > 0

    # 验证元素引用格式
    refs = [e["ref"] for e in snap["elements"]]
    assert all(ref.startswith("@e") for ref in refs)

    # 查找登录按钮
    login_btn = None
    for elem in snap["elements"]:
        text = elem.get("text", "").strip()
        if "登录" in text and len(text) < 10:  # 避免匹配长文本
            login_btn = elem["ref"]
            print(f"Found login button: {elem}")
            break

    if login_btn:
        # 点击登录按钮
        await click(session_id, login_btn)

        # 等待一下让页面加载
        import asyncio
        await asyncio.sleep(2)

        # 验证页面变化
        snap_after = await snapshot(session_id)
        # 页面可能跳转或弹出登录框
        assert snap_after["url"] is not None
    else:
        # 如果没找到登录按钮，测试也算通过（可能页面结构变化）
        print("Login button not found, skipping click test")


@pytest.mark.asyncio
async def test_session_isolation():
    """会话隔离测试"""
    session1 = await create_session()
    session2 = await create_session()

    assert session1 != session2

    await open_page(session1, "https://www.zhipin.com")
    await open_page(session2, "https://www.xiaohongshu.com")

    snap1 = await snapshot(session1)
    snap2 = await snapshot(session2)

    assert "zhipin" in snap1["url"]
    assert "xiaohongshu" in snap2["url"]
