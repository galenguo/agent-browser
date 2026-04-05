import asyncio
import click
from pathlib import Path
from .session_manager import CLISessionManager
from ..config.manager import ConfigManager
from ..llm.factory import LLMFactory

config_mgr = ConfigManager()

@click.group()
def cli():
    """Agent Browser CLI"""
    pass

@cli.command()
def init():
    """初始化配置文件"""
    config_path = Path.home() / ".agent-browser" / "config.yaml"

    if config_path.exists():
        if not click.confirm(f"配置文件已存在：{config_path}\n是否覆盖？"):
            return

    config_mgr.save_config()
    click.echo(f"✅ 配置文件已创建：{config_path}")
    click.echo("请编辑配置文件并设置 API keys")

@cli.command()
@click.option('--task', required=True, help='任务描述')
@click.option('--session', help='复用已有 session')
@click.option('--url', help='起始 URL')
@click.option('--max-steps', type=int, help='最大步骤数')
@click.option('--headless/--headed', default=None)
@click.option('--llm-provider', type=click.Choice(['openai', 'anthropic']))
@click.option('--llm-model', help='LLM 模型')
@click.option('--llm-base-url', help='自定义 LLM API 地址')
@click.option('--remote-host', help='远程浏览器主机')
@click.option('--remote-port', type=int, help='远程 CDP 端口')
@click.option('--cdp-url', help='完整 CDP URL')
def run(task, session, url, max_steps, headless, llm_provider, llm_model, llm_base_url, remote_host, remote_port, cdp_url):
    """执行浏览器任务"""
    asyncio.run(_run_task(task, session, url, max_steps, headless, llm_provider, llm_model, llm_base_url, remote_host, remote_port, cdp_url))

async def _run_task(task, session_name, url, max_steps, headless, llm_provider, llm_model, llm_base_url, remote_host, remote_port, cdp_url):
    from ..browser.stealth_launcher import launch_stealth_launcher
    from ..agent.runner import run_agent_task

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
        temperature=llm_config.temperature
    )

    session_mgr = CLISessionManager(storage_path=Path(cli_config.session_storage).expanduser())
    browser = None
    temp_session = False
    target_cdp_url = None

    try:
        if session_name:
            session = session_mgr.get(session_name)
            if not session:
                click.echo(f"❌ Session '{session_name}' 不存在", err=True)
                return
            from playwright.async_api import async_playwright
            pw = await async_playwright().start()
            browser = await pw.chromium.connect_over_cdp(session.cdp_url)
            click.echo(f"✅ 复用 session: {session_name}")
        else:
            # 确定 CDP URL（优先级：命令行 > 配置文件）
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
                click.echo(f"✅ 连接远程浏览器: {target_cdp_url}")
            else:
                from ..browser.stealth_launcher import launch_stealth_browser
                browser = await launch_stealth_browser(headless=browser_config.headless)
                temp_session = True
                click.echo("✅ 启动本地浏览器")

        if url:
            page = await browser.new_page()
            await page.goto(url)

        result = await run_agent_task(browser=browser, task=task, llm=llm, max_steps=max_steps)

        click.echo(f"\n✅ 任务完成")
        click.echo(f"结果：{result}")

        if session_name:
            session_mgr.update_last_used(session_name)

    finally:
        if temp_session and browser:
            await browser.close()

@cli.group()
def session():
    """Session 管理命令"""
    pass

@session.command('start')
@click.option('--name', required=True, help='Session 名称')
@click.option('--headless/--headed', default=False)
def session_start(name, headless):
    """启动持久 session"""
    asyncio.run(_session_start(name, headless))

async def _session_start(name, headless):
    from ..browser.stealth_launcher import launch_stealth_browser

    cli_config = config_mgr.get_cli_config()
    session_mgr = CLISessionManager(storage_path=Path(cli_config.session_storage).expanduser())

    if session_mgr.get(name):
        click.echo(f"❌ Session '{name}' 已存在", err=True)
        return

    browser = await launch_stealth_browser(headless=headless)
    cdp_url = f"http://localhost:19222"
    profile_path = str(Path.home() / ".agent-browser" / "profiles" / name)

    session_mgr.create(session_id=name, cdp_url=cdp_url, mode='local', profile_path=profile_path)
    click.echo(f"✅ Session '{name}' 已启动")
    click.echo(f"   CDP URL: {cdp_url}")

@session.command('list')
def session_list():
    """列出所有 sessions"""
    cli_config = config_mgr.get_cli_config()
    session_mgr = CLISessionManager(storage_path=Path(cli_config.session_storage).expanduser())
    sessions = session_mgr.list_all()

    if not sessions:
        click.echo("无活动 session")
        return

    click.echo(f"{'NAME':<15} {'BROWSER':<20} {'TASKS':<8} {'LAST USED'}")
    for name, sess in sessions.items():
        click.echo(f"{name:<15} {sess.browser_instance_id:<20} {sess.task_count:<8} {sess.last_used}")

@session.command('stop')
@click.option('--name', required=True, help='Session 名称')
def session_stop(name):
    """停止 session"""
    cli_config = config_mgr.get_cli_config()
    session_mgr = CLISessionManager(storage_path=Path(cli_config.session_storage).expanduser())
    session = session_mgr.get(name)

    if not session:
        click.echo(f"❌ Session '{name}' 不存在", err=True)
        return

    session_mgr.delete(name)
    click.echo(f"✅ Session '{name}' 已停止")

if __name__ == '__main__':
    cli()


