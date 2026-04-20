"""
browser-use Stealth Actions registration.

Replaces browser-use Agent's navigate / input / click actions with
StealthEnhancer-enhanced versions, so that API mode and CLI mode
anti-detection capabilities are 100% aligned.

Overrides:
  navigate -> pre_action("navigate") + page.goto() + post_action("navigate")
  input    -> stealth.human_type() (character-level delay 50-250ms, 5% typo-backspace)
  click    -> pre_action("click") + random_mouse_move() + locator.click() + post_action

Usage::

    from stealth_browser.stealth.actions import register_stealth_actions
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

from stealth_browser.stealth.enhancer import StealthEnhancer

logger = logging.getLogger(__name__)


def register_stealth_actions(tools: Tools, stealth: StealthEnhancer) -> None:
    """
    Override browser-use default navigate / input / click actions,
    injecting StealthEnhancer delays and human behavior simulation.

    Args:
        tools:   browser-use Tools instance (contains Registry)
        stealth: StealthEnhancer instance (from SessionContext)
    """
    # ── 1. Remove browser-use default versions ───────────────────
    tools.registry.exclude_action("navigate")
    tools.registry.exclude_action("input")
    tools.registry.exclude_action("click")

    # ── 2. Register stealth version of navigate ───────────────────

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
        Stealth navigation:
          pre_action("navigate") -> random delay 0.5-1.5s
          page.goto()
          post_action() -> random delay 0.05-0.2s
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

    # ── 3. Register stealth version of input ──────────────────────

    @tools.registry.action(
        "Input text into an interactive element",
        param_model=InputTextAction,
    )
    async def stealth_input(
        params: InputTextAction,
        browser_session,
    ) -> ActionResult:
        """
        Stealth input:
          Get element XPath by index
          human_type(): character-level delay 50-250ms + 5% typo-backspace + 10% long pause
        """
        page = await browser_session.get_current_page()
        try:
            element = await browser_session.get_element_by_index(params.index)
            if element is None:
                raise ValueError(f"Element index {params.index} not found in DOM")
            xpath_selector = f"xpath={element.xpath}"
            await stealth.human_type(page, xpath_selector, params.text, clear_first=params.clear)
            preview = params.text[:30] + ("..." if len(params.text) > 30 else "")
            logger.info(f"Stealth typed '{preview}' into element {params.index}")
            return ActionResult(extracted_content=f"Typed '{preview}' into element at index {params.index}")
        except Exception:
            raise

    # ── 4. Register stealth version of click ───────────────────────

    @tools.registry.action(
        "Click element",
        param_model=ClickElementAction,
    )
    async def stealth_click(
        params: ClickElementAction,
        browser_session,
    ) -> ActionResult:
        """
        Stealth click:
          pre_action("click") -> random delay 0.1-0.3s
          random_mouse_move() -> Bezier curve mouse movement 1-3 times
          locator.click()
          post_action() -> random delay 0.05-0.2s
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
                return ActionResult(extracted_content=f"Clicked element at index {params.index}")
            if params.coordinate_x is not None and params.coordinate_y is not None:
                await page.mouse.click(params.coordinate_x, params.coordinate_y)
                await stealth.post_action("click")
                logger.info(f"Stealth clicked at ({params.coordinate_x}, {params.coordinate_y})")
                return ActionResult(extracted_content=(f"Clicked at ({params.coordinate_x}, {params.coordinate_y})"))
            raise ValueError("Either index or coordinates required for click action")
        except Exception:
            await stealth.post_action("click")
            raise
