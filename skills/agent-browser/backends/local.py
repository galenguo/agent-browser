"""本地 CDP 后端 — 包装现有 BrowserController + BrowserDaemon"""
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from . import BrowserBackend, BrowserPageHandle
from ..config import SkillConfig
from ..refs_generator import generate_refs, COMBINED_SELECTOR

logger = logging.getLogger(__name__)


class PlaywrightPageHandle(BrowserPageHandle):
    """
    Playwright Page 的薄包装，实现 BrowserPageHandle 接口。
    95% 委托给 Playwright Page 对象。
    """

    def __init__(self, page: Page):
        self._page = page
        self._listeners: Dict[str, list] = {}

    @property
    def raw_page(self) -> Page:
        """暴露原始 Playwright Page（用于需要 Playwright 特定功能的场景）"""
        return self._page

    async def goto(self, url: str, wait_until: str = "domcontentloaded", timeout: int = 8000) -> None:
        await self._page.goto(url, wait_until=wait_until, timeout=timeout)

    async def go_back(self, wait_until: str = "domcontentloaded", timeout: int = 10000) -> None:
        await self._page.go_back(wait_until=wait_until, timeout=timeout)

    async def evaluate(self, expression: str) -> Any:
        return await self._page.evaluate(expression)

    async def wait_for_selector(self, selector: str, timeout: int = 10000) -> None:
        await self._page.wait_for_selector(selector, timeout=timeout)

    async def mouse_wheel(self, delta_x: int, delta_y: int) -> None:
        await self._page.mouse.wheel(delta_x, delta_y)

    async def mouse_move(self, x: float, y: float) -> None:
        await self._page.mouse.move(x, y)

    async def keyboard_press(self, key: str) -> None:
        await self._page.keyboard.press(key)

    async def title(self) -> str:
        return await self._page.title()

    async def url(self) -> str:
        return self._page.url

    async def on(self, event: str, handler: Callable) -> None:
        self._page.on(event, handler)
        if event not in self._listeners:
            self._listeners[event] = []
        self._listeners[event].append(handler)

    def remove_listener(self, event: str, handler: Callable) -> None:
        self._page.remove_listener(event, handler)
        if event in self._listeners:
            self._listeners[event] = [h for h in self._listeners[event] if h != handler]

    async def close(self) -> None:
        try:
            await self._page.close()
        except Exception:
            pass


@dataclass
class LocalSession:
    """本地会话数据"""
    page_handle: PlaywrightPageHandle
    browser_context: Any  # BrowserContext
    dom_indices: List[int]
    snapshot_cache: Optional[Dict] = None


class LocalCDPBackend(BrowserBackend):
    """
    本地 CDP 后端 — 唯一的浏览器操作核心实现。

    - 使用 Playwright connect_over_cdp 连接本地 CloakBrowser
    - daemon_enabled 时使用 BrowserDaemon 持久连接
    - 集成 StealthEnhancer（隐匿增强）
    - 支持 LLM 模式（原子操作）和 Agent 模式（browser-use Agent）
    """

    def __init__(self, config: SkillConfig):
        self._config = config
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._sessions: Dict[str, LocalSession] = {}
        self._stealth = None
        self._daemon = None

        # Daemon 持久化（可选）
        if config.daemon_enabled:
            try:
                from ..daemon import BrowserDaemon
                self._daemon = BrowserDaemon.get(config)
                logger.info("BrowserDaemon enabled")
            except Exception as e:
                logger.debug(f"BrowserDaemon not available: {e}")

        # 延迟初始化 StealthEnhancer
        if config.stealth_enabled:
            try:
                from ..stealth import StealthEnhancer
                self._stealth = StealthEnhancer()
            except ImportError:
                logger.debug("StealthEnhancer not available")

    async def connect(self) -> None:
        """连接到 CDP 端点（带重试）"""
        # Daemon 路径：使用 BrowserDaemon 持久连接
        if self._daemon:
            await self._daemon.ensure_connected()
            self._browser = self._daemon.browser
            return

        # 非 Daemon 路径：直接连接
        if self._browser:
            try:
                _ = self._browser.contexts  # 存活性检查
                return
            except Exception:
                self._browser = None

        if not self._playwright:
            self._playwright = await async_playwright().start()

        cdp_url = self._config.cdp_url
        # Playwright connect_over_cdp 需要 HTTP URL
        if cdp_url.startswith("ws://"):
            cdp_url = "http://" + cdp_url[5:]

        retries = 3
        for attempt in range(retries):
            try:
                self._browser = await self._playwright.chromium.connect_over_cdp(cdp_url)
                logger.info(f"Connected to CDP: {cdp_url}")
                return
            except Exception as e:
                if attempt < retries - 1:
                    await asyncio.sleep(0.3 * (attempt + 1))
                else:
                    raise

    async def disconnect(self) -> None:
        """断开浏览器连接"""
        # 先关闭所有 session
        for sid in list(self._sessions.keys()):
            await self.delete_session(sid)

        if self._daemon:
            await self._daemon.disconnect()
            self._browser = None
            return

        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None

        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

    async def is_connected(self) -> bool:
        if self._daemon:
            return self._daemon.is_connected
        if not self._browser:
            return False
        try:
            _ = self._browser.contexts
            return True
        except Exception:
            return False

    async def create_session(self, session_id: str) -> PlaywrightPageHandle:
        """创建浏览器会话"""
        await self.connect()

        # Daemon 路径：使用 daemon 的 context 管理
        if self._daemon:
            context, page = await self._daemon.create_context(session_id)
            if self._stealth:
                from ..stealth import StealthEnhancer
                await StealthEnhancer.inject_timing_noise(page)
            page_handle = PlaywrightPageHandle(page)
            self._sessions[session_id] = LocalSession(
                page_handle=page_handle,
                browser_context=context,
                dom_indices=[],
            )
            logger.info(f"Session created (daemon): {session_id}")
            return page_handle

        # 非 Daemon 路径
        context = await self._browser.new_context()
        page = await context.new_page()

        # 注入隐匿增强
        if self._stealth:
            from ..stealth import StealthEnhancer
            await StealthEnhancer.inject_timing_noise(page)

        page_handle = PlaywrightPageHandle(page)
        self._sessions[session_id] = LocalSession(
            page_handle=page_handle,
            browser_context=context,
            dom_indices=[],
        )

        logger.info(f"Session created: {session_id}")
        return page_handle

    async def delete_session(self, session_id: str) -> None:
        """删除浏览器会话"""
        session = self._sessions.pop(session_id, None)
        if not session:
            return

        # Daemon 路径：通过 daemon 管理 context 生命周期
        if self._daemon:
            await self._daemon.destroy_context(session_id)
            logger.info(f"Session deleted (daemon): {session_id}")
            return

        # 非 Daemon 路径
        try:
            await session.page_handle.close()
        except Exception:
            pass
        try:
            await session.browser_context.close()
        except Exception:
            pass
        logger.info(f"Session deleted: {session_id}")

    async def get_page(self, session_id: str) -> PlaywrightPageHandle:
        """获取会话的页面句柄"""
        if session_id not in self._sessions:
            raise ValueError(f"Session {session_id} not found")
        return self._sessions[session_id].page_handle

    # ── 快照/refs 专用方法（保持与现有 controller.py 兼容）──

    async def snapshot(self, session_id: str, interactive_only: bool = False) -> Dict:
        """获取页面快照（兼容现有接口）"""
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        # 使用缓存
        if session.snapshot_cache and not interactive_only:
            result = session.snapshot_cache
            session.snapshot_cache = None
            return result

        page = session.page_handle.raw_page
        elements, dom_indices, page_info = await generate_refs(page, interactive_only)
        session.dom_indices = dom_indices

        return {
            "url": page_info["href"],
            "title": page_info["title"],
            "elements": elements,
        }

    async def cache_snapshot_after_open(self, session_id: str) -> None:
        """open_page 后预计算快照缓存"""
        session = self._sessions.get(session_id)
        if not session:
            return

        try:
            page = session.page_handle.raw_page
            elements, dom_indices, page_info = await generate_refs(page, False)
            session.dom_indices = dom_indices
            session.snapshot_cache = {
                "url": page_info["href"],
                "title": page_info["title"],
                "elements": elements,
            }
        except Exception:
            session.snapshot_cache = None

    def get_dom_indices(self, session_id: str) -> List[int]:
        """获取会话的 DOM 索引"""
        session = self._sessions.get(session_id)
        return session.dom_indices if session else []

    async def stealth_delay(self, action_type: str = "general") -> None:
        """隐匿延迟"""
        if self._stealth:
            await self._stealth.pre_action(action_type)

    async def stealth_mouse_move(self, session_id: str) -> None:
        """隐匿鼠标移动"""
        if self._stealth:
            session = self._sessions.get(session_id)
            if session:
                await self._stealth.random_mouse_move(session.page_handle.raw_page)
