"""Agent Browser 基础用法：用适配器搜索 Boss 直聘

运行前确保：
  1. CloakBrowser 已启动（CDP 端口 19222）
  2. 已有 Boss 直聘登录 Cookie
"""
import asyncio
from skills.agent_browser.adapters.runner import run_adapter
from skills.agent_browser.main import create_session


async def main():
    # 1. 创建浏览器会话
    session_id = await create_session()
    print(f"Session: {session_id}")

    # 2. 用适配器搜索（boss/search.yaml 的参数名是 query）
    result = await run_adapter(
        site="boss",
        command="search",
        args={"query": "Python工程师", "limit": 5},
        session_id=session_id,
    )

    # 3. 输出结果
    if isinstance(result, list):
        print(f"\n找到 {len(result)} 条结果:")
        for item in result[:5]:
            title = item.get("title", "N/A")
            salary = item.get("salary", "N/A")
            print(f"  - {title} | {salary}")
    else:
        print(f"执行结果: {result}")


if __name__ == "__main__":
    asyncio.run(main())
