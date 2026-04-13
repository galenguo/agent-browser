"""
browser-use Agent 自动登录 + 查询推荐牛人简历。

流程：
  Step 1: Agent 打开 Boss 直聘 HR 端，截图二维码到 /tmp/zhipin_qrcode.png
          → 你扫码或等 Agent 切换到短信登录让你输入验证码
  Step 2: 登录成功后，Agent 访问"推荐牛人"，收集并总结 3 份简历

用法：
    cd <project-root>
    PYTHONPATH=. python scripts/agent_login_recruit.py
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

CDP_PORT = 19224  # 独立端口，避免冲突
QRCODE_PATH = "/tmp/zhipin_qrcode.png"
SCREENSHOT_PATH = "/tmp/zhipin_recruit.png"


async def main():
    import cloakbrowser
    from patchright.async_api import async_playwright
    from browser_use import Agent, Tools
    from browser_use.browser import BrowserProfile, BrowserSession
    from browser_use.llm import ChatAnthropic

    binary = cloakbrowser.ensure_binary()
    stealth_args = cloakbrowser.get_default_stealth_args()

    logger.info("=" * 60)
    logger.info("启动 CloakBrowser（有头模式）")
    logger.info("=" * 60)

    pw = await async_playwright().start()

    browser = await pw.chromium.launch(
        executable_path=binary,
        headless=False,
        args=stealth_args + [
            f"--remote-debugging-port={CDP_PORT}",
            "--remote-debugging-address=127.0.0.1",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--window-size=1440,900",
            "--window-position=50,50",
        ],
        ignore_default_args=["--enable-automation"],
    )

    context = await browser.new_context(
        viewport={"width": 1440, "height": 900},
        locale="zh-CN",
        timezone_id="Asia/Shanghai",
    )
    page = await context.new_page()

    # 先打开首页预热
    logger.info("预热：打开 zhipin.com 首页...")
    await page.goto("https://www.zhipin.com", wait_until="domcontentloaded")
    await asyncio.sleep(2)

    logger.info("")
    logger.info(">>> 浏览器窗口已打开，Agent 即将开始登录流程 <<<")
    logger.info(f">>> 二维码截图将保存到: {QRCODE_PATH} <<<")
    logger.info(">>> 请查看浏览器窗口或截图文件，完成扫码/验证码登录 <<<")
    logger.info("")

    # ── browser-use Agent ──
    cdp_url = f"http://127.0.0.1:{CDP_PORT}"
    session = BrowserSession(
        browser_profile=BrowserProfile(
            cdp_url=cdp_url,
            is_local=True,
            headless=False,
            highlight_elements=True,
            minimum_wait_page_load_time=0.8,
            wait_for_network_idle_page_load_time=2.0,
        )
    )

    llm = ChatAnthropic(model="claude-sonnet-4-6")
    tools = Tools()

    task = """
你是一个浏览器自动化助手，帮助用户完成 Boss 直聘招聘端的登录和简历查询。

【当前情况】
浏览器已打开 zhipin.com 首页。你需要完成以下步骤：

【Step 1 - 登录】
1. 点击右上角"登录"按钮，进入登录页面
2. 优先尝试"二维码登录"：
   - 找到二维码后，立即截图保存到 /tmp/zhipin_qrcode.png（使用 save_file 或截图工具）
   - 在浏览器中显示二维码，等待 90 秒让用户扫码
   - 如果二维码超时，点击"刷新"重新截图
3. 如果二维码登录不可用，切换到"验证码登录"（短信登录）：
   - 点击"短信验证码登录"选项
   - 截图当前页面到 /tmp/zhipin_qrcode.png（让用户看到手机号输入界面）
   - 等待 120 秒（用户需要手动在浏览器中输入手机号和验证码）
4. 登录成功的标志：页面右上角出现头像/用户名，URL 不再包含 login

【Step 2 - 查询推荐牛人简历】
登录成功后：
1. 确保切换到"招聘者"模式（Boss 端，HR 视角）
   - 如果当前是求职者视角，找到切换入口（右上角"我要招人"或"Boss 端"）
2. 访问 https://www.zhipin.com/web/boss/recommend 或从导航栏找到"推荐牛人"
3. 收集页面上显示的推荐候选人信息：
   - 姓名（或化名）
   - 当前职位/头衔
   - 工作经验年限
   - 学历
   - 期望薪资
   - 核心技能/技术栈
   - 简历摘要（从简介中提取）
4. 收集至少 3 位候选人的完整信息

【Step 3 - 输出结果】
以 JSON 格式输出 3 份简历总结：
[
  {
    "name": "候选人A",
    "title": "Python 高级工程师",
    "experience": "5年",
    "education": "本科",
    "expected_salary": "25-35K",
    "skills": ["Python", "Django", "MySQL"],
    "summary": "5年后端开发经验，专注于..."
  },
  ...
]

【重要提示】
- 遇到验证码或人机验证时，等待用户在浏览器中手动处理
- 每次需要等待用户操作时，截图当前页面并等待至少 60 秒
- 如果页面跳转到聊天页或其他意外页面，重新导航到正确 URL
"""

    agent = Agent(
        task=task,
        llm=llm,
        tools=tools,
        browser_session=session,
        max_actions_per_step=8,
    )

    logger.info("Agent 开始执行...")
    logger.info("")

    try:
        result = await agent.run(max_steps=60)

        logger.info("")
        logger.info("=" * 60)
        logger.info("Agent 执行完成")
        logger.info("=" * 60)

        # 提取最终结果
        final_content = None
        if hasattr(result, "all_results"):
            for r in reversed(result.all_results):
                if r.extracted_content and r.is_done:
                    final_content = r.extracted_content
                    break

        if final_content:
            logger.info("最终结果：")
            print(f"\n{final_content}\n")
        else:
            print(f"\n{result}\n")

        # 最终截图
        try:
            await page.screenshot(path=SCREENSHOT_PATH)
            logger.info(f"最终截图已保存: {SCREENSHOT_PATH}")
        except Exception:
            pass

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
    logger.info("60 秒后自动关闭浏览器...")
    await asyncio.sleep(60)

    await browser.close()
    await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
