"""Agent Browser 示例：B站热门视频排行

运行前确保：
  1. CloakBrowser 已启动（CDP 端口 19222）
"""
import asyncio
import json
from agent_browseradapters.runner import run_adapter
from agent_browsermain import create_session


async def main():
    session_id = await create_session()
    print(f"Session: {session_id}")

    # 使用 bilibili/hot 适配器获取热门视频
    result = await run_adapter(
        site="bilibili",
        command="hot",
        args={"limit": 10},
        session_id=session_id,
    )

    if isinstance(result, list):
        print(f"\n=== B站热门 Top {len(result)} ===\n")
        for item in result:
            rank = item.get("rank", "?")
            title = item.get("title", "N/A")
            play_count = item.get("play_count", "N/A")
            danmaku = item.get("danmaku", "N/A")
            author = item.get("author", "N/A")
            url = item.get("url", "")
            print(f"#{rank} {title}")
            print(f"   UP主: {author} | 播放: {play_count} | 弹幕: {danmaku}")
            if url:
                print(f"   链接: {url[:80]}")
            print()
    else:
        print(f"执行结果: {json.dumps(result, ensure_ascii=False, indent=2)}")


if __name__ == "__main__":
    asyncio.run(main())
