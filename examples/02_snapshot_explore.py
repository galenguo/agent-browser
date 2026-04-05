"""Agent Browser 探索模式：快照 + 分析

运行前确保：
  1. CloakBrowser 已启动（CDP 端口 19222）
"""
import asyncio
from skills.agent_browser.main import create_session, open_page, snapshot
from skills.agent_browser.explore.explorer import explore


async def main():
    session_id = await create_session()

    # 导航到目标页面
    await open_page(session_id, "https://www.zhihu.com/hot")

    # 获取页面快照
    snap = await snapshot(session_id)
    print(f"URL: {snap['url']}")
    print(f"Title: {snap['title']}")
    print(f"Elements: {len(snap['elements'])}")

    # 探索可用端点
    result = await explore(
        session_id=session_id,
        url="https://www.zhihu.com/hot",
        goal="获取热门内容",
    )
    print(f"\n发现 {len(result.get('endpoints', []))} 个端点:")
    for ep in result.get("endpoints", [])[:5]:
        print(f"  - {ep.get('url', '?')} [{ep.get('status')}]")


if __name__ == "__main__":
    asyncio.run(main())
