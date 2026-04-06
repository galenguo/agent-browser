"""Agent Browser CLI -- main entry point.

Based on CLISessionManager, supports atomic commands.
External LLM controls the browser step by step via CLI.

CLI cross-process session persistence:
  - CLISessionManager: file-based persistence (~/.agent-browser/sessions.json)
  - UnifiedSessionManager: browser instance management (in-memory)
  - session create: create browser instance + write to file
  - other commands: read cdp_url from file, reuse existing CDP connection
"""

import asyncio
import json
import logging
import os
from pathlib import Path

import click
from browser_use.browser import BrowserProfile, BrowserSession

from agent_browser.cli.session_manager import CLISessionManager
from agent_browser.models import BrowserInstance
from agent_browser.session.session_manager import SessionContext, UnifiedSessionManager
from agent_browser.stealth.browser_controller import ActionResult, BrowserController

logger = logging.getLogger(__name__)

# Global session manager (CLI mode)
session_mgr = UnifiedSessionManager(mode="cli", max_concurrent=5)
# CLI file-based persistence (cross-process sharing)
cli_store = CLISessionManager()


async def _get_or_reconnect_session(session_id: str) -> SessionContext:
    """
    Get session context (cross-process reuse).

    Prefer in-memory retrieval from UnifiedSessionManager;
    if not found (cross-process scenario), read cdp_url from CLISessionManager and reconnect.
    """
    # Try in-memory first (same process)
    try:
        ctx = await session_mgr.get_session(session_id)
        cli_store.update_last_used(session_id)  # Update file record
        return ctx
    except Exception:
        pass

    # Read from file (cross-process)
    cli_session = cli_store.get(session_id)
    if not cli_session:
        raise Exception(f"Session not found: {session_id}")

    # Reconnect to existing CDP endpoint (don't restart browser)
    browser_session = BrowserSession(browser_profile=BrowserProfile(cdp_url=cli_session.cdp_url, is_local=True))
    await browser_session.start()

    # Build lightweight SessionContext
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

    # Register in memory (subsequent same-process calls can reuse)
    session_mgr.sessions[session_id] = ctx
    cli_store.update_last_used(session_id)

    return ctx


def output_json(result: ActionResult):
    """Output result in JSON format."""
    click.echo(json.dumps(result.to_dict(), ensure_ascii=False))


@click.group()
def cli():
    """Agent-Browser CLI -- atomic command mode"""


# ──────────────────────────────────────────
# Session commands
# ──────────────────────────────────────────


@cli.group()
def session():
    """Session management"""


@session.command("create")
@click.option("--name", required=True, help="Session name")
@click.option("--browser", type=click.Choice(["local", "remote"]), default="local")
@click.option("--use-gateway", is_flag=True, help="Use Gateway to allocate remote browser")
@click.option("--cdp-url", help="Specify CDP URL directly (remote mode)")
def session_create(name, browser, use_gateway, cdp_url):
    """Create a session"""
    asyncio.run(_session_create(name, browser, use_gateway, cdp_url))


async def _session_create(name, browser, use_gateway, cdp_url):
    try:
        if use_gateway:
            browser = "remote"
            if not os.environ.get("BROWSER_GATEWAY_URL"):
                click.echo(json.dumps({"status": "error", "error": "BROWSER_GATEWAY_URL not set"}))
                return

        # Create browser instance (UnifiedSessionManager)
        ctx = await session_mgr.create_session(session_id=name, browser_mode=browser, cdp_url=cdp_url)

        # Persist to file (CLISessionManager) -- cross-process sharing
        cli_store.create(
            session_id=ctx.session_id,
            cdp_url=ctx.browser_instance.cdp_url,
            mode=browser,
            profile_path=os.getenv("PROFILE_STORAGE", "/data/profiles") + f"/{name}",
        )

        output_json(
            ActionResult(status="success", data={"session_id": ctx.session_id, "cdp_url": ctx.browser_instance.cdp_url})
        )
    except Exception as e:
        output_json(ActionResult(status="error", error=str(e)))


@session.command("list")
def session_list():
    """List all sessions"""
    # Read from file (cross-process visible)
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
    """View session information"""
    asyncio.run(_session_info(session))


async def _session_info(session_id):
    try:
        # Read from file (cross-process visible)
        cli_session = cli_store.get(session_id)
        if not cli_session:
            output_json(ActionResult(status="error", error=f"Session not found: {session_id}"))
            return

        output_json(
            ActionResult(
                status="success",
                data={
                    "session_id": cli_session.session_id,
                    "browser_mode": cli_session.mode,
                    "cdp_url": cli_session.cdp_url,
                    "created_at": cli_session.created_at,
                    "last_used": cli_session.last_used,
                    "task_count": cli_session.task_count,
                },
            )
        )
    except Exception as e:
        output_json(ActionResult(status="error", error=str(e)))


@session.command("destroy")
@click.option("--session", required=True)
def session_destroy(session):
    """Destroy a session"""
    asyncio.run(_session_destroy(session))


async def _session_destroy(session_id):
    import contextlib

    try:
        # Destroy from UnifiedSessionManager (if exists)
        with contextlib.suppress(Exception):
            await session_mgr.destroy_session(session_id)  # May already be gone from memory

        # Delete from file
        cli_store.delete(session_id)

        output_json(ActionResult(status="destroyed", data={"session_id": session_id}))
    except Exception as e:
        output_json(ActionResult(status="error", error=str(e)))


# ──────────────────────────────────────────
# Navigate commands
# ──────────────────────────────────────────


@cli.group()
def navigate():
    """Navigation operations"""


@navigate.command("goto")
@click.option("--session", required=True)
@click.option("--url", required=True)
def navigate_goto(session, url):
    """Navigate to URL"""
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
# Interact commands
# ──────────────────────────────────────────


@cli.group()
def interact():
    """Interaction operations"""


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
# Extract commands
# ──────────────────────────────────────────


@cli.group()
def extract():
    """Content extraction"""


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
# Page commands
# ──────────────────────────────────────────


@cli.group()
def page():
    """Tab management"""


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
# Run command (Agent mode)
# ──────────────────────────────────────────


@cli.command()
@click.option("--task", required=True, help="Task description")
@click.option("--session", help="Reuse existing session")
@click.option("--url", help="Starting URL")
@click.option("--max-steps", type=int, default=10, help="Maximum steps")
@click.option("--headed/--headless", default=True)
@click.option("--llm-provider", type=click.Choice(["openai", "anthropic"]), default="openai")
@click.option("--llm-model", help="LLM model")
@click.option("--llm-base-url", help="Custom LLM API URL")
def run(task, session, url, max_steps, headed, llm_provider, llm_model, llm_base_url):
    """Execute a browser task (Agent autonomous mode)"""
    asyncio.run(_run_task(task, session, url, max_steps, headed, llm_provider, llm_model, llm_base_url))


async def _run_task(task, session_name, url, max_steps, headed, llm_provider, llm_model, llm_base_url):
    try:
        from agent_browser.llm.factory import LLMFactory

        llm = LLMFactory.create(
            provider=llm_provider,
            model=llm_model,
            base_url=llm_base_url,
            temperature=0.1,
        )

        from browser_use import Agent, BrowserProfile
        from browser_use import BrowserSession as BUSession
        from browser_use.tools.service import Tools

        from agent_browser.stealth.actions import register_stealth_actions

        def _make_stealth_tools(ctx):
            """Build Tools instance with StealthEnhancer injected (CLI=API anti-detection 100% aligned)."""
            tools = Tools()
            register_stealth_actions(tools, ctx.controller.stealth)
            return tools

        if session_name:
            # Reuse existing session
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
            click.echo(
                json.dumps(
                    {
                        "status": "success",
                        "data": {"result": str(result)},
                    },
                    ensure_ascii=False,
                )
            )
        else:
            # Create temporary session
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

            click.echo(
                json.dumps(
                    {
                        "status": "success",
                        "data": {"result": str(result)},
                    },
                    ensure_ascii=False,
                )
            )

    except Exception as e:
        click.echo(json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False))


# ──────────────────────────────────────────
# Skill commands
# ──────────────────────────────────────────


@cli.command()
@click.option("--path", help="Custom install path (default: ~/.claude/skills/agent-browser/)")
@click.option("--force", is_flag=True, help="Overwrite existing skill")
def install_skill(path, force):
    """Install Claude Code skill to ~/.claude/skills/ for discovery."""
    _install_skill(path, force)


def _install_skill(custom_path=None, force=False):
    """Copy SKILL.md and references to Claude Code skills directory."""
    import shutil

    # Locate skill files within the installed package
    import agent_browser.skill as skill_mod
    skill_dir = Path(skill_mod.__file__).parent
    src_skill_md = skill_dir / "SKILL.md"
    src_references = skill_dir / "references"
    src_scripts = skill_dir / "scripts"

    if not src_skill_md.exists():
        click.echo(
            json.dumps({"status": "error", "error": f"SKILL.md not found at {src_skill_md}"})
        )
        return

    # Determine target directory
    if custom_path:
        target_dir = Path(custom_path)
    else:
        target_dir = Path.home() / ".claude" / "skills" / "agent-browser"

    target_dir.mkdir(parents=True, exist_ok=True)

    # Check existing
    target_skill = target_dir / "SKILL.md"
    if target_skill.exists() and not force:
        click.echo(
            json.dumps({
                "status": "exists",
                "message": f"Skill already exists at {target_dir}. Use --force to overwrite.",
                "path": str(target_dir),
            })
        )
        return

    # Copy SKILL.md
    try:
        shutil.copy2(src_skill_md, target_skill)
    except (OSError, shutil.Error) as e:
        click.echo(json.dumps({"status": "error", "error": f"Failed to copy SKILL.md: {e}"}))
        return

    # Copy references/
    target_refs = target_dir / "references"
    if src_references.exists():
        try:
            if target_refs.exists():
                shutil.rmtree(target_refs)
            shutil.copytree(src_references, target_refs)
        except (OSError, shutil.Error) as e:
            click.echo(json.dumps({"status": "error", "error": f"Failed to copy references: {e}"}))
            return

    # Copy scripts/
    target_scripts = target_dir / "scripts"
    if src_scripts.exists():
        try:
            if target_scripts.exists():
                shutil.rmtree(target_scripts)
            shutil.copytree(src_scripts, target_scripts)
        except (OSError, shutil.Error) as e:
            click.echo(json.dumps({"status": "error", "error": f"Failed to copy scripts: {e}"}))
            return

    click.echo(
        json.dumps({
            "status": "installed",
            "message": "Agent Browser skill installed successfully.",
            "path": str(target_dir),
            "next_steps": "Restart Claude Code or open a new conversation to use the skill.",
        }, ensure_ascii=False)
    )


if __name__ == "__main__":
    cli()
