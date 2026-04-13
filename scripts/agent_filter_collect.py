"""
browser-use Agent 筛选推荐牛人并收藏。

条件：工作 1～2 年 + 有 AI 相关项目研发经验
目标：收藏 3 位符合条件的候选人

用法：
    cd <project-root>
    PYTHONPATH=. python scripts/agent_filter_collect.py
"""
import asyncio
import json
import logging
import os
from pathlib import Path

os.environ.setdefault("REBROWSER_PATCHES_RUNTIME_FIX_MODE", "addBinding")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

CDP_PORT = 19225
COOKIE_FILE = Path("/tmp/zhipin_cookies.json")


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

    # 注入已有 Cookie
    if COOKIE_FILE.exists():
        cookies = json.loads(COOKIE_FILE.read_text())
        await context.add_cookies(cookies)
        logger.info(f"已注入 {len(cookies)} 个 Cookie（尝试恢复登录态）")
    else:
        logger.info("无已保存 Cookie，将由 Agent 完成登录")

    page = await context.new_page()

    # 直接打开 Boss 端聊天/推荐页预热
    logger.info("预热：打开 zhipin.com ...")
    await page.goto("https://www.zhipin.com/web/chat/index", wait_until="domcontentloaded")
    await asyncio.sleep(3)

    current_url = page.url
    logger.info(f"当前页面: {current_url}")

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
筛选并收藏 Boss 直聘推荐牛人中符合条件的候选人。

【筛选条件】
1. 工作经验 1～2 年（年限显示为"1年"或"2年"，跳过 3 年及以上）
2. 有 AI 相关项目研发经验（含关键词：AI、大模型、LLM、机器学习、深度学习、NLP、CV、AIGC、RAG、向量数据库等）

【严格禁止的操作】
- 禁止使用 evaluate() 动作（会导致 schema 错误）
- 禁止打开候选人详情面板（点击会导致 DOM 重构，元素 ID 失效）
- 禁止使用 find_elements() 或 search_page()

【操作流程】

Step 1：关闭弹窗，进入推荐牛人
- 关闭任何弹窗
- 点击左侧"推荐牛人"菜单，等待加载

Step 2：应用筛选过滤器
- 点击页面右上角"筛选"按钮
- 在"经验要求"中选择"1-3年"
- 点击"确定"应用筛选，等待 3 秒

Step 3：在列表中直接筛选（不点开详情）
逐一查看列表卡片（不点击打开详情面板），仅看卡片上显示的信息：
- 年限标签（"1年"或"2年"→ 符合；"3年"及以上→ 跳过）
- 卡片上的简介文字/技能标签中是否含 AI 关键词

Step 4：收藏符合条件的候选人
找到符合条件的候选人卡片后：
1. 将鼠标移到卡片上，等待操作按钮出现
2. 找到"收藏"按钮（文字"收藏"或星形图标，通常在卡片右侧或底部）
3. 使用 click(coordinate_x=X, coordinate_y=Y) 坐标方式点击收藏按钮
4. 等待 1 秒确认收藏成功（按钮变为"已收藏"）
5. 记录该候选人姓名、年限、AI 关键词

收藏 3 位后调用 done() 结束。

Step 5：不足时滚动加载更多
- 若当前可见候选人不足，向下滚动候选人列表区域
- 等待新候选人加载后继续

【收藏按钮位置参考】
- 鼠标 hover 到卡片后，右侧或底部会出现"收藏"文字按钮
- 按钮坐标大约在卡片的右侧区域，可截图后用坐标点击

【完成格式】
已收藏 3 位候选人：
1. 姓名：XXX | 年限：X年 | AI关键词：XXX
2. 姓名：XXX | 年限：X年 | AI关键词：XXX
3. 姓名：XXX | 年限：X年 | AI关键词：XXX
"""

    agent = Agent(
        task=task,
        llm=llm,
        tools=tools,
        browser_session=session,
        max_actions_per_step=8,
    )

    logger.info("")
    logger.info(">>> Agent 开始筛选并收藏推荐牛人 <<<")
    logger.info("")

    try:
        result = await agent.run(max_steps=80)

        logger.info("")
        logger.info("=" * 60)
        logger.info("Agent 执行完成")
        logger.info("=" * 60)

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

        # 保存最新 Cookie（更新登录态）
        cookies = await context.cookies()
        zhipin_cookies = [c for c in cookies if "zhipin" in c.get("domain", "")]
        if zhipin_cookies:
            COOKIE_FILE.write_text(json.dumps(zhipin_cookies, ensure_ascii=False, indent=2))
            logger.info(f"已更新 Cookie: {COOKIE_FILE}")

        await page.screenshot(path="/tmp/zhipin_collect_done.png")
        logger.info("最终截图: /tmp/zhipin_collect_done.png")

    except Exception as e:
        logger.error(f"Agent 执行失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            await session.kill()
        except Exception:
            pass

    logger.info("60 秒后自动关闭浏览器...")
    await asyncio.sleep(60)

    await browser.close()
    await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
