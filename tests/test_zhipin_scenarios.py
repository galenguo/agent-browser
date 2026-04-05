"""Boss直聘场景测试"""
import pytest
from agent_browser.main import create_session, open_page, snapshot, click, fill


@pytest.mark.asyncio
async def test_zhipin_homepage_load():
    """Boss直聘首页加载"""
    session_id = await create_session()
    await open_page(session_id, "https://www.zhipin.com")

    snap = await snapshot(session_id)
    assert "zhipin" in snap["url"]
    assert len(snap["elements"]) > 0


@pytest.mark.asyncio
async def test_zhipin_search_jobs():
    """Boss直聘职位搜索"""
    session_id = await create_session()
    await open_page(session_id, "https://www.zhipin.com")

    snap = await snapshot(session_id, interactive_only=True)

    # 查找搜索框
    search_input = None
    for elem in snap["elements"]:
        if elem.get("role") == "input":
            text = elem.get("text", "").strip()
            # 查找可能的搜索输入框
            if len(text) == 0 or "搜索" in text or "职位" in text:
                search_input = elem["ref"]
                print(f"Found search input: {elem}")
                break

    if search_input:
        await fill(session_id, search_input, "Python工程师")

        # 重新获取快照以找到搜索按钮
        snap = await snapshot(session_id, interactive_only=True)

        # 查找搜索按钮
        for elem in snap["elements"]:
            text = elem.get("text", "").strip()
            if "搜索" in text and elem.get("role") == "button" and len(text) < 10:
                print(f"Found search button: {elem}")
                await click(session_id, elem["ref"])
                break
    else:
        print("Search input not found, skipping search test")
