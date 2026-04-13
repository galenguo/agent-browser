"""
Boss 直聘端到端测试：推荐牛人简历筛选与收藏

流程：
  1. 启动 CloakBrowser (persistent context, Cookie 自动持久化)
  2. browser-use Agent 接管全部操作（登录检测 + 推荐牛人 + 简历筛选 + 收藏）

用法：
    cd <project-root>
    PYTHONPATH=src python scripts/test_recruit_e2e.py
"""
import asyncio
import json
import logging
import os
import time
from pathlib import Path

os.environ.setdefault("REBROWSER_PATCHES_RUNTIME_FIX_MODE", "addBinding")

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env", override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── 配置 ──
CDP_PORT = 19226
COOKIE_FILE = Path("/tmp/zhipin_cookies.json")
SCREENSHOT_DIR = Path("/tmp/zhipin_screenshots")
PROFILE_DIR = Path("/tmp/zhipin_profile")
TARGET_COLLECT_MIN = 5
TARGET_COLLECT_MAX = 10


# ═══════════════════════════════════════════════════════
# 浏览器启动
# ═══════════════════════════════════════════════════════

async def start_browser():
    """启动 CloakBrowser (persistent context — Cookie 自动持久化到磁盘)"""
    import cloakbrowser
    from patchright.async_api import async_playwright

    logger.info("=" * 60)
    logger.info("启动 CloakBrowser (persistent context)")
    logger.info("=" * 60)

    binary = cloakbrowser.ensure_binary()
    stealth_args = cloakbrowser.get_default_stealth_args()
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    pw = await async_playwright().start()
    context = await pw.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        executable_path=binary,
        headless=False,
        args=stealth_args + [
            f"--remote-debugging-port={CDP_PORT}",
            "--remote-debugging-address=127.0.0.1",
            "--remote-allow-origins=*",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--window-size=1440,900",
            "--window-position=50,50",
            "--webrtc-ip-handling-policy=disable_non_proxied_udp",
            "--enforce-webrtc-ip-permission-check",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--disable-background-timer-throttling",
            "--font-render-hinting=medium",
        ],
        ignore_default_args=["--enable-automation"],
        viewport={"width": 1440, "height": 900},
        locale="zh-CN",
        timezone_id="Asia/Shanghai",
    )

    logger.info(f"✅ CloakBrowser 启动成功, CDP={CDP_PORT}, Profile={PROFILE_DIR}")
    return pw, context


# ═══════════════════════════════════════════════════════
# Agent Task Prompt
# ═══════════════════════════════════════════════════════

AGENT_TASK = f"""你是一个 Boss 直聘招聘助手，帮助 HR 筛选和收藏推荐牛人简历。

【目标】
在 Boss 直聘 HR 端的"推荐牛人"页面，筛选并收藏 {TARGET_COLLECT_MIN}~{TARGET_COLLECT_MAX} 份符合条件的简历。

【操作流程】

Phase 0：访问推荐牛人页面
1. 导航到 https://www.zhipin.com/web/boss/recommend
2. 等待 3 秒页面加载
3. 如果被重定向到登录页面（URL 包含 "login" 或 "user"）：
   - 这说明需要登录，请截图当前页面
   - 然后等待 120 秒让用户在浏览器中手动扫码登录
   - 每隔 15 秒检查一次 URL 是否已离开登录页
   - 登录成功后重新导航到 https://www.zhipin.com/web/boss/recommend
4. 如果有弹窗（引导、广告、升级提示），关闭所有弹窗

Phase 1：应用筛选（可选）
1. 如果页面有"筛选"按钮，点击打开筛选面板
2. 在"工作经验"中选择"1-3年"
3. 点击"确定"应用筛选
4. 等待列表刷新

Phase 2：逐个查看简历并筛选收藏

对推荐列表中的每个牛人候选人，重复以下步骤：

Step A - 点击打开简历详情：
  - 找到牛人卡片上的姓名文字（通常是蓝色链接）
  - 直接点击姓名链接打开简历详情页
  - 如果是在当前页打开了详情面板/侧边栏，也可以在里面操作
  - 等待 2~3 秒让简历内容加载

Step B - 阅读简历并判断：
  使用 extract_content 或直接阅读页面上的简历信息，获取：
  - 姓名、工作年限、学历、项目经历（重点）、技能标签

  按以下条件逐一判断：
  ✅ 条件 1: 工作 1~3 年
  ✅ 条件 2: 本科或以上学历（本科、硕士、博士）
  ✅ 条件 3: 有 AI/AI Agent 开发项目经验
     关键词：AI、LLM、大模型、Agent、RAG、向量数据库、机器学习、
     深度学习、NLP、AIGC、GPT、Claude、Transformer、Fine-tuning、
     Prompt Engineering、langchain、embedding、知识图谱、
     模型训练、模型推理、模型部署
  ✅ 条件 4: 项目有具体数据说明（性能提升百分比、准确率、QPS、用户量等）
  ✅ 条件 5: 有技术深度（架构设计、性能优化、系统设计经验）

  满足前 3 个必要条件 + 至少 1 个加分条件（4或5）→ 收藏

Step C - 收藏操作：
  如果符合条件：
  1. 在简历详情页右侧找到星星形状的收藏按钮（⭐）
  2. 使用 click(coordinate_x=X, coordinate_y=Y) 点击收藏按钮
  3. 等待 1~2 秒确认收藏成功
  4. 如果提示"合作客户专享"等付费提示，记录但继续下一个

Step D - 返回列表：
  - 点击浏览器后退按钮或关闭详情面板
  - 等待 2 秒让列表恢复
  - 继续下一个牛人

Phase 3：加载更多
  如果收藏数量不足，向下滚动加载更多候选人，继续 Phase 2。

Phase 4：完成
  收藏达到 {TARGET_COLLECT_MIN}~{TARGET_COLLECT_MAX} 份后，调用 done() 输出结果。

【输出格式】
已收藏 N 位候选人：
1. 姓名：XXX | 年限：X年 | 学历：XX | 关键技能：XXX | 收藏原因：一句话说明
2. ...

未收藏但查看过的候选人：
1. 姓名：XXX | 跳过原因：一句话说明

【重要规则】
1. 禁止使用 evaluate() 动作（browser-use 0.12.2 的 bug）
2. 优先使用 click(coordinate_x=X, coordinate_y=Y) 坐标方式点击
3. 每次页面切换后等待 2~3 秒
4. 遇到弹窗或验证码时，先处理再继续
5. 单个候选人操作超过 8 步仍未完成，跳过
6. 连续 3 个不符合条件，向下滚动查看更多
"""


# ═══════════════════════════════════════════════════════
# Agent 执行
# ═══════════════════════════════════════════════════════

async def run_agent(context):
    """browser-use Agent 执行全部任务（登录 + 筛选 + 收藏）"""
    from browser_use import Agent, Tools
    from browser_use.browser import BrowserProfile, BrowserSession
    from browser_use.llm import ChatOpenAI

    logger.info("=" * 60)
    logger.info("Agent 执行简历筛选与收藏")
    logger.info("=" * 60)

    cdp_url = f"http://127.0.0.1:{CDP_PORT}"
    session = BrowserSession(
        browser_profile=BrowserProfile(
            cdp_url=cdp_url,
            is_local=True,
            headless=False,
            highlight_elements=True,
            minimum_wait_page_load_time=1.0,
            wait_for_network_idle_page_load_time=2.5,
        )
    )

    # 使用 ChatOpenAI + add_schema_to_system_prompt 接入智谱 GLM-5
    llm = ChatOpenAI(
        model=os.getenv("LLM_MODEL", "glm-5-turbo"),
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"),
        temperature=0.1,
        add_schema_to_system_prompt=True,  # 将 schema 添加到 system prompt 而不是 response_format
        dont_force_structured_output=True,  # 不强制 structured output
    )
    logger.info(f"LLM: {llm.model} @ {llm.base_url}")

    agent = Agent(
        task=AGENT_TASK,
        llm=llm,
        tools=Tools(),
        browser_session=session,
        max_actions_per_step=5,
        use_vision=False,
    )

    logger.info(f"Agent 开始执行... 目标: 收藏 {TARGET_COLLECT_MIN}~{TARGET_COLLECT_MAX} 份简历")

    result = await agent.run(max_steps=120)

    # 提取结果
    final_content = None
    if hasattr(result, "all_results"):
        for r in reversed(result.all_results):
            if r.extracted_content and r.is_done:
                final_content = r.extracted_content
                break

    if final_content:
        logger.info("=" * 60)
        logger.info("Agent 执行结果")
        logger.info("=" * 60)
        print(f"\n{final_content}\n")
    else:
        logger.info(f"Agent 原始返回: {result}")

    # 截图
    SCREENSHOT_DIR.mkdir(exist_ok=True)
    try:
        active_page = context.pages[-1] if context.pages else None
        if active_page:
            await active_page.screenshot(path=str(SCREENSHOT_DIR / "final_result.png"))
            logger.info(f"最终截图: {SCREENSHOT_DIR / 'final_result.png'}")
    except Exception:
        pass

    # 保存 Cookie
    try:
        cookies = await context.cookies()
        zhipin_cookies = [c for c in cookies if "zhipin" in c.get("domain", "")]
        if zhipin_cookies:
            COOKIE_FILE.write_text(json.dumps(zhipin_cookies, ensure_ascii=False, indent=2))
            logger.info(f"已保存 Cookie: {COOKIE_FILE}")
    except Exception:
        pass

    try:
        await session.kill()
    except Exception:
        pass

    return final_content


# ═══════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════

async def main():
    pw = None
    context = None

    try:
        # 启动浏览器
        pw, context = await start_browser()

        # 直接让 Agent 处理全部流程（不在 patchright context 中做页面操作）
        # browser-use 通过 CDP 连接浏览器，Agent 自行处理登录检测和页面导航
        result = await run_agent(context)

        logger.info("")
        logger.info("=" * 60)
        logger.info("端到端测试完成")
        logger.info("=" * 60)

        logger.info("")
        logger.info("60 秒后自动关闭浏览器（可提前按 Ctrl+C 退出）...")
        await asyncio.sleep(60)

    except KeyboardInterrupt:
        logger.info("用户中断")
    except Exception as e:
        logger.error(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if context:
            try:
                await context.close()
            except Exception:
                pass
        if pw:
            try:
                await pw.stop()
            except Exception:
                pass


if __name__ == "__main__":
    asyncio.run(main())
