"""
Boss 直聘端到端测试。

用法：
    export ANTHROPIC_API_KEY=...
    export CLOAKBROWSER_PATH=/opt/cloakbrowser/chrome
    cd <project-root>
    python tests/test_zhipin.py
"""

import asyncio
import logging
import os

os.environ.setdefault("REBROWSER_PATCHES_RUNTIME_FIX_MODE", "addBinding")


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


async def main():
    from agent.runner import run_agent_task, shutdown_browser

    try:
        from browser_use.llm import ChatAnthropic

        llm = ChatAnthropic(model="claude-haiku-4-5")
    except ImportError:
        logger.error("browser-use not installed. Run: pip install browser-use")
        return

    task = (
        "访问 https://www.zhipin.com，搜索北京的 Python 开发岗位，"
        "收集前 5 个职位的名称、公司名、薪资范围，以 JSON 格式返回。"
    )

    logger.info("Starting Boss直聘 end-to-end test...")
    logger.info(f"Task: {task}")

    try:
        result = await run_agent_task(
            task=task,
            llm=llm,
            warmup=True,  # 首次任务预热
            max_steps=30,
            model_name="claude-haiku-4-5",
        )
        logger.info(f"\n✅ Task Result:\n{result}")
    except Exception as e:
        logger.error(f"❌ Task failed: {e}")
        raise
    finally:
        await shutdown_browser()


if __name__ == "__main__":
    asyncio.run(main())
