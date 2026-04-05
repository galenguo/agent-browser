"""
Agent-Browser CLI - 重构版

基于 UnifiedSessionManager，支持原子命令。
外部 LLM 通过 CLI 逐步控制浏览器。

CLI 跨进程会话持久化：
  - CLISessionManager：文件持久化（~/.agent-browser/sessions.json）
  - UnifiedSessionManager：浏览器实例管理（内存态）
  - session create：创建浏览器实例 + 写入文件
  - 其他命令：从文件读取 cdp_url，复用已有 CDP 连接
"""
import asyncio
import json
import logging
import os
from pathlib import Path

import click

from src.core.session_manager import UnifiedSessionManager, SessionContext
from src.core.browser_controller import ActionResult, BrowserController
from src.cli.session_manager import CLISessionManager
from browser_use.browser import BrowserSession, BrowserProfile
from src.models import BrowserInstance

logger = logging.getLogger(__name__)

# 全局 session manager（CLI 模式）
session_mgr = UnifiedSessionManager(mode="cli", max_concurrent=5)
# CLI 文件持久化（跨进程共享）
cli_store = CLISessionManager()


async def _get_or_reconnect_session(session_id: str) -> SessionContext:
    """
    获取会话上下文（跨进程复用）。

    优先从 UnifiedSessionManager 内存获取；
    如果不存在（跨进程场景），从 CLISessionManager 读取 cdp_url 并重新连接。
    """
    # 尝试从内存获取（同进程）
    try:
        ctx = await session_mgr.get_session(session_id)
        cli_store.update_last_used(session_id)  # 更新文件记录
        return ctx
    except Exception:
        pass

    # 从文件读取（跨进程）
    cli_session = cli_store.get(session_id)
    if not cli_session:
        raise Exception(f"Session not found: {session_id}")

    # 重新连接到已有 CDP endpoint（不重新启动浏览器）
    browser_session = BrowserSession(
        browser_profile=BrowserProfile(cdp_url=cli_session.cdp_url, is_local=True)
    )
    await browser_session.start()

    # 构造轻量级 SessionContext
    instance = BrowserInstance(
        instance_id=cli_session.browser_instance_id,
        cdp_url=cli_session.cdp_url,
        cdp_port=0,
        session_id=session_id,
    )
    controller = BrowserController(browser_session, session_id)

    ctx = SessionContext(
        session_id=session_id,
        browser_instance=instance,
        browser_session=browser_session,
        controller=controller,
        mode="cli",
        browser_mode=cli_session.mode,
    )

    # 注册到内存（后续同进程调用可复用）
    session_mgr.sessions[session_id] = ctx
    cli_store.update_last_used(session_id)

    return ctx


def output_json(result: ActionResult):
    """输出 JSON 格式结果"""
    click.echo(json.dumps(result.to_dict(), ensure_ascii=False))


@click.group()
def cli():
    """Agent-Browser CLI - 原子命令模式"""
    pass


# ──────────────────────────────────────────
# Session 命令组
# ──────────────────────────────────────────

@cli.group()
def session():
    """会话管理"""
    pass


@session.command("create")
@click.option("--name", required=True, help="Session 名称")
@click.option("--browser", type=click.Choice(["local", "remote"]), default="local")
@click.option("--use-gateway", is_flag=True, help="使用 Gateway 分配远程浏览器")
@click.option("--cdp-url", help="直接指定 CDP URL（远程模式）")
def session_create(name, browser, use_gateway, cdp_url):
    """创建会话"""
    asyncio.run(_session_create(name, browser, use_gateway, cdp_url))


async def _session_create(name, browser, use_gateway, cdp_url):
    try:
        if use_gateway:
            browser = "remote"
            if not os.environ.get("BROWSER_GATEWAY_URL"):
                click.echo(json.dumps({"status": "error", "error": "BROWSER_GATEWAY_URL not set"}))
                return

        # 创建浏览器实例（UnifiedSessionManager）
        ctx = await session_mgr.create_session(session_id=name, browser_mode=browser, cdp_url=cdp_url)

        # 持久化到文件（CLISessionManager）— 跨进程共享
        cli_store.create(
            session_id=ctx.session_id,
            cdp_url=ctx.browser_instance.cdp_url,
            mode=browser,
            profile_path=os.getenv('PROFILE_STORAGE', '/data/profiles') + f"/{name}",
        )

        output_json(ActionResult(
            status="success",
            data={"session_id": ctx.session_id, "cdp_url": ctx.browser_instance.cdp_url}
        ))
    except Exception as e:
        output_json(ActionResult(status="error", error=str(e)))


@session.command("list")
def session_list():
    """列出所有会话"""
    # 从文件读取（跨进程可见）
    sessions = [
        {
            "session_id": s.session_id,
            "cdp_url": s.cdp_url,
            "mode": s.mode,
            "created_at": s.created_at,
            "last_used": s.last_used,
            "task_count": s.task_count,
        }
        for s in cli_store.list_all().values()
    ]
    click.echo(json.dumps({"status": "success", "data": {"sessions": sessions}}, ensure_ascii=False))


@session.command("info")
@click.option("--session", required=True)
def session_info(session):
    """查看会话信息"""
    asyncio.run(_session_info(session))


async def _session_info(session_id):
    try:
        # 从文件读取（跨进程可见）
        cli_session = cli_store.get(session_id)
        if not cli_session:
            output_json(ActionResult(status="error", error=f"Session not found: {session_id}"))
            return

        output_json(ActionResult(
            status="success",
            data={
                "session_id": cli_session.session_id,
                "browser_mode": cli_session.mode,
                "cdp_url": cli_session.cdp_url,
                "created_at": cli_session.created_at,
                "last_used": cli_session.last_used,
                "task_count": cli_session.task_count,
            }
        ))
    except Exception as e:
        output_json(ActionResult(status="error", error=str(e)))


@session.command("destroy")
@click.option("--session", required=True)
def session_destroy(session):
    """销毁会话"""
    asyncio.run(_session_destroy(session))


async def _session_destroy(session_id):
    try:
        # 从 UnifiedSessionManager 销毁（如果存在）
        try:
            await session_mgr.destroy_session(session_id)
        except Exception:
            pass  # 可能已经不在内存中

        # 从文件删除
        cli_store.delete(session_id)

        output_json(ActionResult(status="destroyed", data={"session_id": session_id}))
    except Exception as e:
        output_json(ActionResult(status="error", error=str(e)))


# ──────────────────────────────────────────
# Navigate 命令组
# ──────────────────────────────────────────

@cli.group()
def navigate():
    """导航操作"""
    pass


@navigate.command("goto")
@click.option("--session", required=True)
@click.option("--url", required=True)
def navigate_goto(session, url):
    """跳转到 URL"""
    asyncio.run(_navigate_goto(session, url))


async def _navigate_goto(session_id, url):
    try:
        ctx = await _get_or_reconnect_session(session_id)
        result = await ctx.controller.goto(url)
        output_json(result)
    except Exception as e:
        output_json(ActionResult(status="error", error=str(e)))


@navigate.command("back")
@click.option("--session", required=True)
def navigate_back(session):
    asyncio.run(_navigate_back(session))


async def _navigate_back(session_id):
    try:
        ctx = await _get_or_reconnect_session(session_id)
        result = await ctx.controller.back()
        output_json(result)
    except Exception as e:
        output_json(ActionResult(status="error", error=str(e)))


@navigate.command("forward")
@click.option("--session", required=True)
def navigate_forward(session):
    asyncio.run(_navigate_forward(session))


async def _navigate_forward(session_id):
    try:
        ctx = await _get_or_reconnect_session(session_id)
        result = await ctx.controller.forward()
        output_json(result)
    except Exception as e:
        output_json(ActionResult(status="error", error=str(e)))


@navigate.command("refresh")
@click.option("--session", required=True)
def navigate_refresh(session):
    asyncio.run(_navigate_refresh(session))


async def _navigate_refresh(session_id):
    try:
        ctx = await _get_or_reconnect_session(session_id)
        result = await ctx.controller.refresh()
        output_json(result)
    except Exception as e:
        output_json(ActionResult(status="error", error=str(e)))


# ──────────────────────────────────────────
# Interact 命令组
# ──────────────────────────────────────────

@cli.group()
def interact():
    """交互操作"""
    pass


@interact.command("click")
@click.option("--session", required=True)
@click.option("--selector", required=True)
def interact_click(session, selector):
    asyncio.run(_interact_click(session, selector))


async def _interact_click(session_id, selector):
    try:
        ctx = await _get_or_reconnect_session(session_id)
        result = await ctx.controller.click(selector)
        output_json(result)
    except Exception as e:
        output_json(ActionResult(status="error", error=str(e)))


@interact.command("input")
@click.option("--session", required=True)
@click.option("--selector", required=True)
@click.option("--text", required=True)
@click.option("--clear/--no-clear", default=True)
def interact_input(session, selector, text, clear):
    asyncio.run(_interact_input(session, selector, text, clear))


async def _interact_input(session_id, selector, text, clear):
    try:
        ctx = await _get_or_reconnect_session(session_id)
        result = await ctx.controller.input_text(selector, text, clear)
        output_json(result)
    except Exception as e:
        output_json(ActionResult(status="error", error=str(e)))


@interact.command("scroll")
@click.option("--session", required=True)
@click.option("--direction", type=click.Choice(["up", "down", "left", "right"]), default="down")
@click.option("--amount", type=int, default=500)
def interact_scroll(session, direction, amount):
    asyncio.run(_interact_scroll(session, direction, amount))


async def _interact_scroll(session_id, direction, amount):
    try:
        ctx = await _get_or_reconnect_session(session_id)
        result = await ctx.controller.scroll(direction, amount)
        output_json(result)
    except Exception as e:
        output_json(ActionResult(status="error", error=str(e)))


# ──────────────────────────────────────────
# Extract 命令组
# ──────────────────────────────────────────

@cli.group()
def extract():
    """内容提取"""
    pass


@extract.command("text")
@click.option("--session", required=True)
@click.option("--selector", default="body")
def extract_text(session, selector):
    asyncio.run(_extract_text(session, selector))


async def _extract_text(session_id, selector):
    try:
        ctx = await _get_or_reconnect_session(session_id)
        result = await ctx.controller.extract_text(selector)
        output_json(result)
    except Exception as e:
        output_json(ActionResult(status="error", error=str(e)))


@extract.command("html")
@click.option("--session", required=True)
@click.option("--selector", default="body")
def extract_html(session, selector):
    asyncio.run(_extract_html(session, selector))


async def _extract_html(session_id, selector):
    try:
        ctx = await _get_or_reconnect_session(session_id)
        result = await ctx.controller.extract_html(selector)
        output_json(result)
    except Exception as e:
        output_json(ActionResult(status="error", error=str(e)))


@extract.command("elements")
@click.option("--session", required=True)
@click.option("--selector", required=True)
def extract_elements(session, selector):
    asyncio.run(_extract_elements(session, selector))


async def _extract_elements(session_id, selector):
    try:
        ctx = await _get_or_reconnect_session(session_id)
        result = await ctx.controller.extract_elements(selector)
        output_json(result)
    except Exception as e:
        output_json(ActionResult(status="error", error=str(e)))


@extract.command("dom")
@click.option("--session", required=True)
@click.option("--simplified/--full", default=True)
def extract_dom(session, simplified):
    asyncio.run(_extract_dom(session, simplified))


async def _extract_dom(session_id, simplified):
    try:
        ctx = await _get_or_reconnect_session(session_id)
        result = await ctx.controller.get_dom(simplified)
        output_json(result)
    except Exception as e:
        output_json(ActionResult(status="error", error=str(e)))


@extract.command("screenshot")
@click.option("--session", required=True)
@click.option("--full-page", is_flag=True)
def extract_screenshot(session, full_page):
    asyncio.run(_extract_screenshot(session, full_page))


async def _extract_screenshot(session_id, full_page):
    try:
        ctx = await _get_or_reconnect_session(session_id)
        result = await ctx.controller.screenshot(full_page)
        output_json(result)
    except Exception as e:
        output_json(ActionResult(status="error", error=str(e)))


# ──────────────────────────────────────────
# Page 命令组
# ──────────────────────────────────────────

@cli.group()
def page():
    """标签页管理"""
    pass


@page.command("new")
@click.option("--session", required=True)
@click.option("--url", default="about:blank")
def page_new(session, url):
    asyncio.run(_page_new(session, url))


async def _page_new(session_id, url):
    try:
        ctx = await _get_or_reconnect_session(session_id)
        result = await ctx.controller.new_tab(url)
        output_json(result)
    except Exception as e:
        output_json(ActionResult(status="error", error=str(e)))


@page.command("list")
@click.option("--session", required=True)
def page_list(session):
    asyncio.run(_page_list(session))


async def _page_list(session_id):
    try:
        ctx = await _get_or_reconnect_session(session_id)
        result = await ctx.controller.list_tabs()
        output_json(result)
    except Exception as e:
        output_json(ActionResult(status="error", error=str(e)))


@page.command("switch")
@click.option("--session", required=True)
@click.option("--index", type=int, required=True)
def page_switch(session, index):
    asyncio.run(_page_switch(session, index))


async def _page_switch(session_id, index):
    try:
        ctx = await _get_or_reconnect_session(session_id)
        result = await ctx.controller.switch_tab(index)
        output_json(result)
    except Exception as e:
        output_json(ActionResult(status="error", error=str(e)))


@page.command("close")
@click.option("--session", required=True)
@click.option("--index", type=int, default=None)
def page_close(session, index):
    asyncio.run(_page_close(session, index))


async def _page_close(session_id, index):
    try:
        ctx = await _get_or_reconnect_session(session_id)
        result = await ctx.controller.close_tab(index)
        output_json(result)
    except Exception as e:
        output_json(ActionResult(status="error", error=str(e)))


# ──────────────────────────────────────────
# Run 命令（Agent 模式）
# ──────────────────────────────────────────

@cli.command()
@click.option("--task", required=True, help="任务描述")
@click.option("--session", help="复用已有 session")
@click.option("--url", help="起始 URL")
@click.option("--max-steps", type=int, default=10, help="最大步骤数")
@click.option("--headed/--headless", default=True)
@click.option("--llm-provider", type=click.Choice(["openai", "anthropic"]), default="openai")
@click.option("--llm-model", help="LLM 模型")
@click.option("--llm-base-url", help="自定义 LLM API 地址")
def run(task, session, url, max_steps, headed, llm_provider, llm_model, llm_base_url):
    """执行浏览器任务（Agent 自主模式）"""
    asyncio.run(_run_task(task, session, url, max_steps, headed, llm_provider, llm_model, llm_base_url))


async def _run_task(task, session_name, url, max_steps, headed, llm_provider, llm_model, llm_base_url):
    try:
        from llm.factory import LLMFactory

        llm = LLMFactory.create(
            provider=llm_provider,
            model=llm_model,
            base_url=llm_base_url,
            temperature=0.1,
        )

        from browser_use import Agent, BrowserSession as BUSession, BrowserProfile
        from browser_use.tools.service import Tools
        from core.stealth_actions import register_stealth_actions

        def _make_stealth_tools(ctx):
            """构造注入了 StealthEnhancer 的 Tools 实例（CLI=API 反侦测 100% 对齐）"""
            tools = Tools()
            register_stealth_actions(tools, ctx.controller.stealth)
            return tools

        if session_name:
            # 复用已有 session
            ctx = await _get_or_reconnect_session(session_name)

            browser_session = BUSession(
                browser_profile=BrowserProfile(
                    cdp_url=ctx.browser_instance.cdp_url,
                    is_local=True,
                ),
            )
            await browser_session.start()

            if url:
                page = await browser_session.get_current_page()
                await page.goto(url)

            agent = Agent(
                task=task,
                llm=llm,
                browser_session=browser_session,
                controller=_make_stealth_tools(ctx),
                max_actions_per_step=5,
            )
            result = await agent.run(max_steps=max_steps)

            await browser_session.close()
            click.echo(json.dumps({
                "status": "success",
                "data": {"result": str(result)},
            }, ensure_ascii=False))
        else:
            # 创建临时 session
            ctx = await session_mgr.create_session(browser_mode="local")

            browser_session = BUSession(
                browser_profile=BrowserProfile(
                    cdp_url=ctx.browser_instance.cdp_url,
                    is_local=True,
                ),
            )
            await browser_session.start()

            if url:
                page = await browser_session.get_current_page()
                await page.goto(url)

            agent = Agent(
                task=task,
                llm=llm,
                browser_session=browser_session,
                controller=_make_stealth_tools(ctx),
                max_actions_per_step=5,
            )
            result = await agent.run(max_steps=max_steps)

            await browser_session.close()
            await session_mgr.destroy_session(ctx.session_id)

            click.echo(json.dumps({
                "status": "success",
                "data": {"result": str(result)},
            }, ensure_ascii=False))

    except Exception as e:
        click.echo(json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False))


if __name__ == "__main__":
    cli()
