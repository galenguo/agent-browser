"""Stealth Browser CLI commands -- config init, task execution, session management.

Lightweight CLI layer that uses ConfigManager for configuration and
CLISessionManager for cross-process session persistence.
"""

import asyncio
from pathlib import Path

import click

from stealth_browser.cli.session_manager import CLISessionManager
from stealth_browser.config import ConfigManager
from stealth_browser.llm.factory import LLMFactory

config_mgr = ConfigManager()


@click.group()
def cli():
    """Stealth Browser CLI"""


@cli.command()
def init():
    """Initialize configuration file"""
    config_path = Path.home() / ".stealth-browser" / "config.yaml"

    if config_path.exists() and not click.confirm(f"Configuration file already exists: {config_path}\nOverwrite?"):
        return

    config_mgr.save_config()
    click.echo(f"Configuration file created: {config_path}")
    click.echo("Please edit the configuration file and set API keys")


@cli.command()
@click.option("--task", required=True, help="Task description")
@click.option("--session", help="Reuse existing session")
@click.option("--url", help="Starting URL")
@click.option("--max-steps", type=int, help="Maximum steps")
@click.option("--headless/--headed", default=None)
@click.option("--llm-provider", type=click.Choice(["openai", "anthropic"]))
@click.option("--llm-model", help="LLM model")
@click.option("--llm-base-url", help="Custom LLM API URL")
@click.option("--remote-host", help="Remote browser host")
@click.option("--remote-port", type=int, help="Remote CDP port")
@click.option("--cdp-url", help="Full CDP URL")
def run(
    task, session, url, max_steps, headless, llm_provider, llm_model, llm_base_url, remote_host, remote_port, cdp_url
):
    """Execute a browser task"""
    asyncio.run(
        _run_task(
            task,
            session,
            url,
            max_steps,
            headless,
            llm_provider,
            llm_model,
            llm_base_url,
            remote_host,
            remote_port,
            cdp_url,
        )
    )


async def _run_task(
    task,
    session_name,
    url,
    max_steps,
    headless,
    llm_provider,
    llm_model,
    llm_base_url,
    remote_host,
    remote_port,
    cdp_url,
):
    from stealth_browser.agent.runner import run_agent_task

    cli_config = config_mgr.get_cli_config()
    browser_config = config_mgr.get_browser_config(headless=headless if headless is not None else None)
    llm_config = config_mgr.get_llm_config(provider=llm_provider, model=llm_model, base_url=llm_base_url)
    browser_mode = config_mgr.get_cli_browser_mode()
    remote_config = config_mgr.get_browser_remote_config()

    max_steps = max_steps or cli_config.default_max_steps

    llm = LLMFactory.create(
        provider=llm_config.provider,
        model=llm_config.model,
        api_key=llm_config.api_key,
        base_url=llm_config.base_url,
        temperature=llm_config.temperature,
    )

    session_mgr = CLISessionManager(storage_path=Path(cli_config.session_storage).expanduser())
    browser = None
    temp_session = False
    target_cdp_url = None

    try:
        if session_name:
            session = session_mgr.get(session_name)
            if not session:
                click.echo(f"Session '{session_name}' does not exist", err=True)
                return
            from playwright.async_api import async_playwright

            pw = await async_playwright().start()
            browser = await pw.chromium.connect_over_cdp(session.cdp_url)
            click.echo(f"Reusing session: {session_name}")
        else:
            # Determine CDP URL (precedence: command line > config file)
            if cdp_url:
                target_cdp_url = cdp_url
            elif remote_host:
                port = remote_port or 19222
                target_cdp_url = f"http://{remote_host}:{port}"
            elif browser_mode == "remote" and remote_config:
                if remote_config.get("cdp_url"):
                    target_cdp_url = remote_config["cdp_url"]
                elif remote_config.get("host"):
                    target_cdp_url = f"http://{remote_config['host']}:{remote_config['port']}"

            if target_cdp_url:
                from playwright.async_api import async_playwright

                pw = await async_playwright().start()
                browser = await pw.chromium.connect_over_cdp(target_cdp_url)
                click.echo(f"Connected to remote browser: {target_cdp_url}")
            else:
                from stealth_browser.browser.stealth_launcher import launch_stealth_browser

                browser = await launch_stealth_browser(headless=browser_config.headless)
                temp_session = True
                click.echo("Started local browser")

        if url:
            page = await browser.new_page()
            await page.goto(url)

        result = await run_agent_task(browser=browser, task=task, llm=llm, max_steps=max_steps)

        click.echo("\nTask completed")
        click.echo(f"Result: {result}")

        if session_name:
            session_mgr.update_last_used(session_name)

    finally:
        if temp_session and browser:
            await browser.close()


@cli.group()
def session():
    """Session management commands"""


@session.command("start")
@click.option("--name", required=True, help="Session name")
@click.option("--headless/--headed", default=False)
def session_start(name, headless):
    """Start a persistent session"""
    asyncio.run(_session_start(name, headless))


async def _session_start(name, headless):
    from stealth_browser.browser.stealth_launcher import launch_stealth_browser

    cli_config = config_mgr.get_cli_config()
    session_mgr = CLISessionManager(storage_path=Path(cli_config.session_storage).expanduser())

    if session_mgr.get(name):
        click.echo(f"Session '{name}' already exists", err=True)
        return

    await launch_stealth_browser(headless=headless)
    cdp_url = "http://localhost:19222"
    profile_path = str(Path.home() / ".stealth-browser" / "profiles" / name)

    session_mgr.create(session_id=name, cdp_url=cdp_url, mode="local", profile_path=profile_path)
    click.echo(f"Session '{name}' started")
    click.echo(f"   CDP URL: {cdp_url}")


@session.command("list")
def session_list():
    """List all sessions"""
    cli_config = config_mgr.get_cli_config()
    session_mgr = CLISessionManager(storage_path=Path(cli_config.session_storage).expanduser())
    sessions = session_mgr.list_all()

    if not sessions:
        click.echo("No active sessions")
        return

    click.echo(f"{'NAME':<15} {'BROWSER':<20} {'TASKS':<8} {'LAST USED'}")
    for name, sess in sessions.items():
        click.echo(f"{name:<15} {sess.browser_instance_id:<20} {sess.task_count:<8} {sess.last_used}")


@session.command("stop")
@click.option("--name", required=True, help="Session name")
def session_stop(name):
    """Stop a session"""
    cli_config = config_mgr.get_cli_config()
    session_mgr = CLISessionManager(storage_path=Path(cli_config.session_storage).expanduser())
    session = session_mgr.get(name)

    if not session:
        click.echo(f"Session '{name}' does not exist", err=True)
        return

    session_mgr.delete(name)
    click.echo(f"Session '{name}' stopped")


if __name__ == "__main__":
    cli()
