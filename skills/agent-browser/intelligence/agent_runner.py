"""Agent 模式执行器 — browser-use Agent + stealth_actions

从 src/agent/runner.py 和 src/core/stealth_actions.py 适配。
支持分块执行（max_steps=6, stuck detection）。
"""
import asyncio
import logging
from typing import Any, Dict, Optional

from ..config import SkillConfig

logger = logging.getLogger(__name__)


def _get_llm(llm_config: Optional[Dict] = None):
    """创建 LLM 实例（langchain）"""
    if not llm_config:
        # 从环境变量读取默认配置
        import os
        provider = os.getenv("AGENT_BROWSER_LLM_PROVIDER", "openai")
        llm_config = {"provider": provider}

    provider = llm_config.get("provider", "openai")

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=llm_config.get("model", "claude-3-5-sonnet-20241022"),
            api_key=llm_config.get("api_key"),
            base_url=llm_config.get("base_url"),
            temperature=llm_config.get("temperature", 0.1),
            max_tokens=llm_config.get("max_tokens", 4096),
        )
    else:
        # 默认 OpenAI 兼容
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=llm_config.get("model", "gpt-4o"),
            api_key=llm_config.get("api_key"),
            base_url=llm_config.get("base_url"),
            temperature=llm_config.get("temperature", 0.1),
            max_tokens=llm_config.get("max_tokens", 4096),
        )


def _register_stealth_actions(tools, stealth) -> None:
    """
    覆盖 browser-use 默认的 navigate/click/input 操作，
    注入 StealthEnhancer 的人类行为模拟。

    参考 src/core/stealth_actions.py 的 register_stealth_actions()。
    """
    try:
        # 排除默认操作
        tools.registry.exclude_action("navigate")
        tools.registry.exclude_action("input")
        tools.registry.exclude_action("click")

        from browser_use.browser.browser import BrowserSession

        # 注册隐匿版 navigate
        @tools.registry.action("Navigate to URL", param_model=type(tools.registry.actions.get("navigate").param_model) if "navigate" in tools.registry.actions else None)
        async def stealth_navigate(params, browser_session: BrowserSession):
            await stealth.pre_action("navigate")
            page = await browser_session.get_current_page()
            await page.goto(url=str(params.url) if hasattr(params, 'url') else str(params))
            await stealth.post_action("navigate")
            return {"status": "navigated"}

        # 注册隐匿版 click
        @tools.registry.action("Click element", param_model=type(tools.registry.actions.get("click").param_model) if "click" in tools.registry.actions else None)
        async def stealth_click(params, browser_session: BrowserSession):
            await stealth.pre_action("click")
            page = await browser_session.get_current_page()
            await stealth.random_mouse_move(page)
            # 使用 browser-use 的元素定位
            if hasattr(params, 'index') and params.index is not None:
                element = await browser_session.get_element_by_index(params.index)
                if element:
                    from playwright.async_api import Locator
                    xpath = await element.get_xpath()
                    locator = page.locator(f"xpath={xpath}")
                    await locator.click()
            await stealth.post_action("click")
            return {"status": "clicked"}

        # 注册隐匿版 input
        @tools.registry.action("Input text", param_model=type(tools.registry.actions.get("input").param_model) if "input" in tools.registry.actions else None)
        async def stealth_input(params, browser_session: BrowserSession):
            await stealth.pre_action("input")
            page = await browser_session.get_current_page()
            if hasattr(params, 'index') and params.index is not None:
                element = await browser_session.get_element_by_index(params.index)
                if element:
                    xpath = await element.get_xpath()
                    await stealth.human_type(page, f"xpath={xpath}", str(params.text))
            await stealth.post_action("input")
            return {"status": "input"}

    except Exception as e:
        logger.warning(f"Failed to register stealth actions: {e}. Using default actions.")


async def run_agent_task(
    session_id: str,
    task: str,
    llm_config: Optional[Dict] = None,
    max_steps: int = 6,
    chunk_continue: bool = True,
    **kwargs,
) -> Dict:
    """
    Agent 模式任务执行。

    1. 获取 session 的浏览器页面
    2. 创建 browser-use BrowserSession（从已有 CDP 连接）
    3. 创建 LLM + Tools + stealth_actions
    4. 分块执行（每块 max_steps 步）
    5. 检测 stuck（空结果/相同结果）
    6. 返回结构化结果
    """
    try:
        from browser_use import Agent, BrowserSession as BUSession
        from browser_use.browser.browser import BrowserProfile
        from browser_use.tools import Tools
    except ImportError:
        return {
            "status": "failed",
            "error": "browser-use not installed. Run: pip install browser-use==0.12.2",
        }

    try:
        from ..backends.local import LocalCDPBackend
        from ..main import _backend, _config
    except ImportError:
        return {"status": "failed", "error": "Local backend not available"}

    if not _backend or not isinstance(_backend, LocalCDPBackend):
        return {"status": "failed", "error": f"No local backend for session {session_id}"}

    # 获取现有页面
    page = _backend.get_page(session_id)
    if not page:
        return {"status": "failed", "error": f"Session {session_id} not found"}

    raw_page = page.raw_page if hasattr(page, 'raw_page') else page

    try:
        # 创建 LLM
        llm = _get_llm(llm_config)

        # 创建 browser-use BrowserSession（从已有 CDP 连接）
        cdp_url = _config.cdp_url if _config else "http://127.0.0.1:19222"
        browser_profile = BrowserProfile(
            cdp_url=cdp_url,
            is_local=True,
            headless=False,
            highlight_elements=True,
            minimum_wait_page_load_time=0.5,
            wait_for_network_idle_page_load_time=1.0,
        )
        browser_session = BUSession(browser_profile=browser_profile)

        # 创建 Tools + 注册隐匿增强
        tools = Tools()
        if _backend._stealth:
            _register_stealth_actions(tools, _backend._stealth)

        # 分块执行循环
        all_results = []
        stuck_count = 0
        last_result_text = ""
        chunk_num = 0
        total_steps = 0

        while True:
            chunk_num += 1
            logger.info(f"Agent chunk {chunk_num}, max_steps={max_steps}")

            # 构建任务 prompt
            if chunk_num == 1:
                current_task = f"{task}\n完成后输出 TASK_COMPLETE: <结果摘要>"
            else:
                current_task = (
                    f"任务：{task}\n"
                    f"已完成：{last_result_text}\n"
                    f"请继续。完成后输出 TASK_COMPLETE: <结果摘要>"
                )

            # 创建并运行 Agent
            agent = Agent(
                task=current_task,
                llm=llm,
                tools=tools,
                browser_session=browser_session,
                max_actions_per_step=5,
                use_vision=False,
            )

            try:
                result = await agent.run(max_steps=max_steps)
                total_steps += max_steps
            except Exception as e:
                logger.error(f"Agent chunk {chunk_num} failed: {e}")
                return {
                    "status": "failed",
                    "error": str(e),
                    "steps": total_steps,
                    "chunks": chunk_num,
                }

            # 解析结果
            result_text = str(result) if result else ""
            all_results.append(result_text)

            # 检查完成
            if "TASK_COMPLETE" in result_text:
                # 提取最终结果
                final = result_text.split("TASK_COMPLETE:")[-1].strip()
                return {
                    "status": "completed",
                    "result": final,
                    "steps": total_steps,
                    "chunks": chunk_num,
                }

            # Stuck 检测
            if not result_text or result_text == last_result_text:
                stuck_count += 1
                logger.warning(f"Stuck detection: count={stuck_count}")
            else:
                stuck_count = 0

            if stuck_count >= 2:
                return {
                    "status": "stuck",
                    "result": result_text or last_result_text,
                    "steps": total_steps,
                    "chunks": chunk_num,
                    "message": "Agent stuck (empty/repeated results). Manual intervention may be needed.",
                }

            last_result_text = result_text

            if not chunk_continue:
                break

        # 不继续分块时返回最后结果
        return {
            "status": "completed" if all_results else "failed",
            "result": last_result_text,
            "steps": total_steps,
            "chunks": chunk_num,
        }

    except Exception as e:
        logger.error(f"Agent task failed: {e}")
        return {"status": "failed", "error": str(e)}
