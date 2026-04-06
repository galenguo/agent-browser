"""Agent Browser 示例：知乎热榜提取

运行前确保：
  1. CloakBrowser 已启动（CDP 端口 19222）
  2. 已有知乎登录 Cookie（或使用 public 模式查看部分内容）
"""
import asyncio
import json
from agent_browseradapters.runner import run_adapter
from agent_browsermain import create_session


async def main():
    session_id = await create_session()
    print(f"Session: {session_id}")

    # 使用 zhihu/hot 适配器获取热榜
    result = await run_adapter(
        site="zhihu",
        command="hot",
        args={"limit": 10},
        session_id=session_id,
    )

    if isinstance(result, list):
        print(f"\n=== 知乎热榜 Top {len(result)} ===\n")
        for item in result:
            rank = item.get("rank", "?")
            title = item.get("title", "N/A")
            hot_score = item.get("hot_score", "N/A")
            excerpt = item.get("excerpt", "")[:60]
            url = item.get("url", "")
            print(f"#{rank} {title}")
            print(f"   热度: {hot_score}")
            if excerpt:
                print(f"   摘要: {excerpt}...")
            if url:
                print(f"   链接: {url[:80]}")
            print()
    else:
        print(f"执行结果: {json.dumps(result, ensure_ascii=False, indent=2)}")


if __name__ == "__main__":
    asyncio.run(main())
