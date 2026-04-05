"""
browser-use Stealth Actions 注册

将 browser-use Agent 的 navigate / input / click 动作替换为
StealthEnhancer 增强版，使 API 模式和 CLI 模式的反侦测能力
100% 对齐。

覆盖项目：
  navigate → pre_action("navigate") + page.goto() + post_action("navigate")
  input    → stealth.human_type()（字符级延迟 50-250ms，5% 打错退格）
  click    → pre_action("click") + random_mouse_move() + locator.click() + post_action

用法：
  from core.stealth_actions import register_stealth_actions
  tools = Tools()
  register_stealth_actions(tools, ctx.stealth)
  agent = Agent(..., controller=tools)
"""
from __future__ import annotations

import logging

from browser_use.agent.views import ActionResult
from browser_use.tools.service import Tools
from browser_use.tools.views import (
    ClickElementAction,
    InputTextAction,
    NavigateAction,
)

from src.core.stealth_enhancer import StealthEnhancer

logger = logging.getLogger(__name__)


def register_stealth_actions(tools: Tools, stealth: StealthEnhancer) -> None:
    """
    覆盖 browser-use 默认的 navigate / input / click 动作，
    注入 StealthEnhancer 延迟和人类行为模拟。

    Args:
        tools:   browser-use Tools 实例（含 Registry）
        stealth: StealthEnhancer 实例（来自 SessionContext）
    """
    # ── 1. 移除 browser-use 默认版本 ──────────────────────────
    tools.registry.exclude_action("navigate")
    tools.registry.exclude_action("input")
    tools.registry.exclude_action("click")

    # ── 2. 注册隐匿版 navigate ────────────────────────���────────

    @tools.registry.action(
        "Navigate browser to a URL",
        param_model=NavigateAction,
        terminates_sequence=True,
    )
    async def stealth_navigate(
        params: NavigateAction,
        browser_session,
    ) -> ActionResult:
        """
        隐匿导航：
          pre_action("navigate") → 随机延迟 0.5-1.5s
          page.goto()
          post_action() → 随机延迟 0.05-0.2s
        """
        await stealth.pre_action("navigate")
        try:
            page = await browser_session.get_current_page()
            if params.new_tab:
                ctx = browser_session.browser_context
                page = await ctx.new_page()
            await page.goto(params.url, wait_until="domcontentloaded", timeout=30000)
            await stealth.post_action("navigate")
            title = await page.title()
            logger.info(f"Stealth navigated to {params.url}")
            return ActionResult(extracted_content=f"Navigated to {params.url} - {title}")
        except Exception:
            await stealth.post_action("navigate")
            raise

    # ── 3. 注册隐匿版 input ────────────────────────────────────

    @tools.registry.action(
        "Input text into an interactive element",
        param_model=InputTextAction,
    )
    async def stealth_input(
        params: InputTextAction,
        browser_session,
    ) -> ActionResult:
        """
        隐匿输入：
          通过 index 获取元素 XPath
          human_type()：字符级延迟 50-250ms + 5% 打错退格 + 10% 长停顿
        """
        page = await browser_session.get_current_page()
        try:
            element = await browser_session.get_element_by_index(params.index)
            if element is None:
                raise ValueError(f"Element index {params.index} not found in DOM")
            xpath_selector = f"xpath={element.xpath}"
            await stealth.human_type(
                page, xpath_selector, params.text, clear_first=params.clear
            )
            preview = params.text[:30] + ("..." if len(params.text) > 30 else "")
            logger.info(f"Stealth typed '{preview}' into element {params.index}")
            return ActionResult(
                extracted_content=f"Typed '{preview}' into element at index {params.index}"
            )
        except Exception:
            raise

    # ── 4. 注册隐匿版 click ────────────────────────────────────

    @tools.registry.action(
        "Click element",
        param_model=ClickElementAction,
    )
    async def stealth_click(
        params: ClickElementAction,
        browser_session,
    ) -> ActionResult:
        """
        隐匿点击：
          pre_action("click") → 随机延迟 0.1-0.3s
          random_mouse_move() → 贝塞尔曲线鼠标移动 1-3 次
          locator.click()
          post_action() → 随机延迟 0.05-0.2s
        """
        await stealth.pre_action("click")
        page = await browser_session.get_current_page()
        await stealth.random_mouse_move(page)
        try:
            if params.index is not None:
                element = await browser_session.get_element_by_index(params.index)
                if element is None:
                    raise ValueError(f"Element index {params.index} not found in DOM")
                xpath_selector = f"xpath={element.xpath}"
                await page.locator(xpath_selector).click(timeout=10000)
                await stealth.post_action("click")
                logger.info(f"Stealth clicked element {params.index}")
                return ActionResult(
                    extracted_content=f"Clicked element at index {params.index}"
                )
            elif params.coordinate_x is not None and params.coordinate_y is not None:
                await page.mouse.click(params.coordinate_x, params.coordinate_y)
                await stealth.post_action("click")
                logger.info(
                    f"Stealth clicked at ({params.coordinate_x}, {params.coordinate_y})"
                )
                return ActionResult(
                    extracted_content=(
                        f"Clicked at ({params.coordinate_x}, {params.coordinate_y})"
                    )
                )
            else:
                raise ValueError("Either index or coordinates required for click action")
        except Exception:
            await stealth.post_action("click")
            raise
