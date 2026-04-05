"""
browser-use Agent 连接到工业级隐匿浏览器。

集成方式 Option B（全隐匿模式）：
  1. 通过 patchright 启动 CloakBrowser（获得驱动级补丁）
  2. browser-use 的 BrowserSession 通过 cdp_url 连接
  3. Agent 通过 browser-use 的 DOM 压缩 + 结构化 action 操作

关键文件参考：
  - browser-use/examples/browser/using_cdp.py — CDP 连接示例
  - browser-use/browser_use/browser/session.py — BrowserSession.connect()
  - browser-use/browser_use/browser/profile.py — cdp_url 字段
"""
import logging
import os
from typing import Any

# 激活 rebrowser Runtime.Enable addBinding 修复（环境变量方式，与 patchright 兼容）
os.environ.setdefault("REBROWSER_PATCHES_RUNTIME_FIX_MODE", "addBinding")

from browser_use import Agent, Tools
from browser_use.browser import BrowserProfile, BrowserSession

from src.browser.stealth_launcher import launch_stealth_browser, close_browser
from src.browser.human_behavior import HumanBehaviorSimulator
from src.session.session_manager import SessionProfileManager

logger = logging.getLogger(__name__)

# 全局单例：持久化会话（避免多次 launch/close）
_pw = None
_browser = None
_browser_session: BrowserSession | None = None
_session_manager = SessionProfileManager()


async def _ensure_browser_running(proxy: str | None = None) -> str:
    """确保 CloakBrowser 已启动，返回 cdp_url。单例模式，避免重复启动。"""
    global _pw, _browser

    if _browser is not None:
        try:
            # 检查浏览器是否还活着（兼容 Browser 和 BrowserContext）
            # 注意: patchright 和 playwright 类型不同，用属性检测而非 isinstance
            if hasattr(_browser, 'pages') and not hasattr(_browser, 'contexts'):
                _ = _browser.pages  # BrowserContext 用 .pages 检查
            else:
                _ = _browser.contexts  # Browser 用 .contexts 检查
            cdp_url = f"http://127.0.0.1:{int(os.getenv('CDP_PORT', '19222'))}"
            return cdp_url
        except Exception:
            logger.warning("Browser died, relaunching...")
            _pw = None
            _browser = None

    _pw, _browser, cdp_url = await launch_stealth_browser(
        headless=os.getenv("HEADLESS", "false").lower() == "true",
        proxy=proxy,
    )
    return cdp_url


async def run_agent_task(
    task: str,
    llm: Any,
    *,
    proxy: str | None = None,
    max_steps: int = 50,
    warmup: bool = True,
    model_name: str = "unknown",
) -> str:
    """
    运行一次 browser-use Agent 任务。

    Args:
        task: 任务描述
        llm: LangChain / browser-use 兼容的 LLM 实例
        proxy: 代理地址，如 "http://user:pass@host:port"
        max_steps: 最大步数
        warmup: 是否在执行任务前进行预热浏览
        model_name: 用于日志记录

    Returns:
        任务执行结果字符串

    Example:
        from browser_use.llm import ChatAnthropic
        llm = ChatAnthropic(model="claude-haiku-4-5-20251001")
        result = await run_agent_task("在 Boss 直聘搜索 Python 开发岗位", llm)
    """
    cdp_url = await _ensure_browser_running(proxy=proxy)

    # 创建 browser-use BrowserSession（连接到已运行的 CloakBrowser）
    # is_local=True 告知 browser-use 这是本地 CDP，不尝试启动新浏览器
    browser_session = BrowserSession(
        browser_profile=BrowserProfile(
            cdp_url=cdp_url,
            is_local=True,
            headless=False,
            highlight_elements=True,
            minimum_wait_page_load_time=0.5,
            wait_for_network_idle_page_load_time=1.0,
        )
    )

    # 预热浏览：建立正常用户基线（仅第一次任务）
    if warmup:
        try:
            sim = HumanBehaviorSimulator()
            # 通过临时 page 预热（不通过 browser-use）
            # 注意: patchright 和 playwright 类型不同，用属性检测
            if _browser:
                if hasattr(_browser, 'pages') and not hasattr(_browser, 'contexts'):
                    # BrowserContext: 直接使用 pages
                    pages = _browser.pages
                    if pages:
                        await sim.warmup_browsing(pages[0])
                elif hasattr(_browser, 'contexts') and _browser.contexts:
                    # Browser: 通过 contexts 获取
                    ctx = _browser.contexts[0]
                    pages = ctx.pages
                    if pages:
                        await sim.warmup_browsing(pages[0])
        except Exception as e:
            logger.warning(f"Warmup failed (non-fatal): {e}")

    tools = Tools()
    # use_vision=False: 禁用截图输入，避免不支持 vision 的模型（如 glm-5-turbo）报 1210 错误
    agent = Agent(
        task=task,
        llm=llm,
        tools=tools,
        browser_session=browser_session,
        max_actions_per_step=5,
        use_vision=False,
    )

    logger.info(f"Starting agent task (model={model_name}, max_steps={max_steps}): {task[:80]}")

    try:
        result = await agent.run(max_steps=max_steps)
        logger.info(f"Task completed: {str(result)[:200]}")
        return str(result)
    except Exception as e:
        logger.error(f"Agent task failed: {e}")
        raise
    finally:
        # 不关闭浏览器（保持持久会话），只关闭 browser-use 的会话对象
        try:
            await browser_session.kill()
        except Exception:
            pass


async def shutdown_browser() -> None:
    """关闭全局浏览器实例（程序退出时调用）"""
    global _pw, _browser
    if _browser is not None:
        await close_browser(_pw, _browser)
        _pw = None
        _browser = None
        logger.info("Global browser instance closed")
