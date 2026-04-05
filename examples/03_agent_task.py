"""Agent Browser Agent 模式：AI 自主操作

运行前确保：
  1. CloakBrowser 已启动（CDP 端口 19222）
  2. LLM API Key 已配置（OPENAI_API_KEY 或 ANTHROPIC_API_KEY）
"""
import asyncio
from skills.agent_browser.main import create_session, run_task


async def main():
    session_id = await create_session()
    print(f"Session: {session_id}")

    # 让 AI agent 自主搜索并提取信息
    result = await run_task(
        session_id=session_id,
        task=(
            "打开 https://www.zhihu.com/hot，"
            "获取前 5 条热门内容的标题和链接，"
            "完成后输出 TASK_COMPLETE: <JSON 结果>"
        ),
        intelligence="agent",
        max_steps=10,
    )
    print(f"\nAgent 结果:\n{result}")


if __name__ == "__main__":
    asyncio.run(main())
