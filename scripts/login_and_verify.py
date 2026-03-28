"""
登录态方案验证脚本。

流程：
  Step 1: 有头模式启动 CloakBrowser，打开 zhipin.com
  Step 2: 等待你手动登录（扫码/账号密码）
  Step 3: 登录成功后按 Enter，自动保存 Cookie
  Step 4: browser-use Agent 使用保存的 Cookie 验证登录态（获取薪资等数据）

用法：
    cd /Users/galen/OpenSource/browser-controller/agent-browser
    PYTHONPATH=. python scripts/login_and_verify.py
"""
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

os.environ.setdefault("REBROWSER_PATCHES_RUNTIME_FIX_MODE", "addBinding")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

COOKIE_FILE = Path("/tmp/zhipin_cookies.json")
CDP_PORT = 19223  # 避免与其他实例冲突


async def step1_login_and_save_cookies():
    """Step 1: 有头模式启动，手动登录，保存 Cookie"""
    import cloakbrowser
    from patchright.async_api import async_playwright

    binary = cloakbrowser.ensure_binary()
    stealth_args = cloakbrowser.get_default_stealth_args()

    logger.info("=" * 60)
    logger.info("Step 1: 启动 CloakBrowser（有头模式）")
    logger.info("=" * 60)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            executable_path=binary,
            headless=False,  # 有头模式，你能看到窗口
            args=stealth_args + [
                f"--remote-debugging-port={CDP_PORT}",
                "--remote-debugging-address=127.0.0.1",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--window-size=1280,900",
                "--window-position=100,100",
            ],
            ignore_default_args=["--enable-automation"],
        )

        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )
        page = await context.new_page()

        # 打开 Boss 直聘
        logger.info("正在打开 zhipin.com ...")
        await page.goto("https://www.zhipin.com", wait_until="domcontentloaded")

        logger.info("")
        logger.info(">>> 浏览器窗口已打开 <<<")
        logger.info("请在浏览器中完成登录（扫码或账号密码）")
        logger.info("将等待 120 秒，请在此期间完成登录...")
        logger.info("")

        # 倒计时等待用户手动登录
        for remaining in range(120, 0, -10):
            logger.info(f"  还剩 {remaining} 秒...")
            await asyncio.sleep(10)

        # 检查登录状态
        cookies = await context.cookies()
        login_cookies = [c for c in cookies if "zhipin" in c.get("domain", "")]
        logger.info(f"获取到 {len(login_cookies)} 个 zhipin.com Cookie")

        # 验证是否真的登录了
        is_logged = await page.evaluate("""
            () => {
                // zhipin.com 登录后会有用户信息
                const userInfo = document.querySelector('.nav-user-info, .user-info, [class*="user-name"]');
                return !!userInfo;
            }
        """)

        # 也检查 URL 是否还在登录页
        current_url = page.url
        logger.info(f"当前页面: {current_url}")

        if not is_logged:
            logger.warning("⚠️  未检测到登录态 DOM，但继续保存 Cookie（可能是 SPA 渲染问题）")

        # 保存 Cookie
        COOKIE_FILE.write_text(
            json.dumps(login_cookies, ensure_ascii=False, indent=2)
        )
        logger.info(f"✅ Cookie 已保存到: {COOKIE_FILE}")

        # 截图留存
        screenshot_path = "/tmp/zhipin_logged_in.png"
        await page.screenshot(path=screenshot_path)
        logger.info(f"✅ 登录截图已保存: {screenshot_path}")

        await browser.close()

    return login_cookies


async def step2_verify_with_agent(cookies: list):
    """Step 2: browser-use Agent 使用 Cookie 验证登录态并抓取薪资"""
    from patchright.async_api import async_playwright
    from browser_use import Agent, Tools
    from browser_use.browser import BrowserProfile, BrowserSession
    from browser_use.llm import ChatAnthropic
    import cloakbrowser

    logger.info("")
    logger.info("=" * 60)
    logger.info("Step 2: browser-use Agent 验证登录态（有头模式）")
    logger.info("=" * 60)

    binary = cloakbrowser.ensure_binary()
    stealth_args = cloakbrowser.get_default_stealth_args()

    pw = await async_playwright().start()

    browser = await pw.chromium.launch(
        executable_path=binary,
        headless=False,  # 继续有头，你能看到 Agent 操作过程
        args=stealth_args + [
            f"--remote-debugging-port={CDP_PORT}",
            "--remote-debugging-address=127.0.0.1",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--window-size=1280,900",
            "--window-position=100,100",
        ],
        ignore_default_args=["--enable-automation"],
    )

    # 创建 context 并注入 Cookie
    context = await browser.new_context(
        viewport={"width": 1280, "height": 900},
        locale="zh-CN",
        timezone_id="Asia/Shanghai",
    )

    # 注入保存的 Cookie（恢复登录态）
    if cookies:
        await context.add_cookies(cookies)
        logger.info(f"✅ 已注入 {len(cookies)} 个 Cookie（恢复登录态）")

    page = await context.new_page()

    # 先验证 Cookie 是否有效
    logger.info("验证 Cookie 有效性...")
    await page.goto("https://www.zhipin.com", wait_until="networkidle")
    await asyncio.sleep(2)

    title = await page.title()
    logger.info(f"页面标题: {title}")

    # 截图看登录态
    await page.screenshot(path="/tmp/zhipin_agent_start.png")
    logger.info("截图已保存: /tmp/zhipin_agent_start.png")

    logger.info("")
    logger.info(">>> Agent 开始工作，你可以在浏览器窗口看到操作过程 <<<")
    logger.info("")

    # browser-use 连接到已有浏览器
    cdp_url = f"http://127.0.0.1:{CDP_PORT}"
    session = BrowserSession(
        browser_profile=BrowserProfile(
            cdp_url=cdp_url,
            is_local=True,
            headless=False,
            highlight_elements=True,
            minimum_wait_page_load_time=0.5,
            wait_for_network_idle_page_load_time=1.5,
        )
    )

    llm = ChatAnthropic(model="claude-haiku-4-5")
    tools = Tools()

    task = (
        "我已经登录了 Boss 直聘（zhipin.com）。"
        "请访问 https://www.zhipin.com/web/geek/jobs?query=Python&city=101010100 "
        "（北京 Python 职位搜索结果页），"
        "收集前 5 个职位的：职位名称、公司名称、薪资范围。"
        "以 JSON 数组格式返回结果，格式为：[{\"title\":\"...\",\"company\":\"...\",\"salary\":\"...\"}]"
    )

    agent = Agent(
        task=task,
        llm=llm,
        tools=tools,
        browser_session=session,
        max_actions_per_step=5,
    )

    try:
        result = await agent.run(max_steps=25)

        logger.info("")
        logger.info("=" * 60)
        logger.info("Agent 执行结果：")
        logger.info("=" * 60)

        # 提取最后的 done action 内容
        final_content = None
        if hasattr(result, "all_results"):
            for r in reversed(result.all_results):
                if r.extracted_content and r.is_done:
                    final_content = r.extracted_content
                    break

        if final_content:
            print(f"\n{final_content}\n")
        else:
            print(f"\n{result}\n")

        # 最终截图
        await page.screenshot(path="/tmp/zhipin_agent_done.png")
        logger.info("最终截图已保存: /tmp/zhipin_agent_done.png")

    except Exception as e:
        logger.error(f"Agent 执行失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            await session.kill()
        except Exception:
            pass

    logger.info("")
    logger.info("30 秒后自动关闭浏览器...")
    await asyncio.sleep(30)

    await browser.close()
    await pw.stop()


async def main():
    # ── Step 1: 手动登录并保存 Cookie ──
    if COOKIE_FILE.exists():
        logger.info(f"发现已保存的 Cookie: {COOKIE_FILE}")
        logger.info("跳过登录步骤，直接用保存的 Cookie 验证？[y/n]: ", )
        ans = await asyncio.get_event_loop().run_in_executor(None, input)
        if ans.strip().lower() == "y":
            cookies = json.loads(COOKIE_FILE.read_text())
            logger.info(f"加载 {len(cookies)} 个已保存的 Cookie")
        else:
            cookies = await step1_login_and_save_cookies()
    else:
        cookies = await step1_login_and_save_cookies()

    # ── Step 2: Agent 验证 ──
    await step2_verify_with_agent(cookies)


if __name__ == "__main__":
    asyncio.run(main())
