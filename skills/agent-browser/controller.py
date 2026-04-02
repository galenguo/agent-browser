"""浏览器控制器 - 核心类"""
import asyncio
from typing import Dict, Optional, List
from dataclasses import dataclass
from playwright.async_api import async_playwright, Browser, Page, Playwright
from .refs_generator import generate_refs, COMBINED_SELECTOR


@dataclass
class BrowserSession:
    """浏览器会话"""
    browser: Browser
    page: Page
    dom_indices: List[int]  # 存储可见元素在 DOM 中的索引（用于 JS 直接操作）
    _snapshot_cache: Optional[Dict] = None  # open_page 后的快照缓存


class BrowserController:
    """浏览器控制器"""

    def __init__(self):
        self.sessions: Dict[str, BrowserSession] = {}
        self._playwright: Optional[Playwright] = None

    async def connect(self, cdp_url: str, retries: int = 2) -> Browser:
        """连接到 CDP 端点（带重试）"""
        if not self._playwright:
            self._playwright = await async_playwright().start()

        # Playwright connect_over_cdp 需要 HTTP URL，自动转换 ws:// 为 http://
        if cdp_url.startswith("ws://"):
            cdp_url = "http://" + cdp_url[5:]

        last_err = None
        for attempt in range(retries):
            try:
                browser = await self._playwright.chromium.connect_over_cdp(cdp_url)
                return browser
            except Exception as e:
                last_err = e
                if attempt < retries - 1:
                    await asyncio.sleep(0.3 * (attempt + 1))
        raise last_err

    def _resolve_dom_idx(self, session_id: str, ref: str) -> int:
        """将 ref (@eN) 解析为 DOM 索引"""
        session = self.sessions[session_id]
        idx = int(ref.replace("@e", ""))
        if idx >= len(session.dom_indices):
            raise ValueError(f"Element {ref} not found (have {len(session.dom_indices)} elements). Call snapshot() first.")
        return session.dom_indices[idx]

    async def create_session(self, session_id: str, cdp_url: str = "http://127.0.0.1:19222") -> BrowserSession:
        """创建会话"""
        browser = await self.connect(cdp_url)
        context = await browser.new_context()
        page = await context.new_page()

        session = BrowserSession(
            browser=browser,
            page=page,
            dom_indices=[],
        )

        self.sessions[session_id] = session
        return session

    async def delete_session(self, session_id: str):
        """删除会话"""
        if session_id in self.sessions:
            session = self.sessions[session_id]
            try:
                await session.page.close()
            except Exception:
                pass
            try:
                await session.browser.close()
            except Exception:
                pass
            del self.sessions[session_id]

    async def open(self, session_id: str, url: str):
        """打开 URL"""
        session = self.sessions[session_id]
        await session.page.goto(url, wait_until="domcontentloaded", timeout=8000)

        # 预计算快照缓存（open 后立即 snapshot 的场景可复用）
        try:
            elements, dom_indices, page_info = await generate_refs(session.page, False)
            session.dom_indices = dom_indices
            session._snapshot_cache = {
                "url": page_info["href"],
                "title": page_info["title"],
                "elements": elements,
            }
        except Exception:
            session._snapshot_cache = None

    async def click(self, session_id: str, ref: str):
        """点击元素（直接 JS，无 ElementHandle）"""
        dom_idx = self._resolve_dom_idx(session_id, ref)
        session = self.sessions[session_id]
        await session.page.evaluate(f"document.querySelectorAll('{COMBINED_SELECTOR}')[{dom_idx}].click()")

    async def fill(self, session_id: str, ref: str, text: str):
        """填充输入框（直接 JS，无 ElementHandle）"""
        dom_idx = self._resolve_dom_idx(session_id, ref)
        session = self.sessions[session_id]
        escaped = text.replace("\\", "\\\\").replace("'", "\\'")
        await session.page.evaluate(
            f"(el => {{ el.focus(); el.value = '{escaped}'; el.dispatchEvent(new Event('input', {{bubbles: true}})); }})"
            f"(document.querySelectorAll('{COMBINED_SELECTOR}')[{dom_idx}])"
        )

    async def scroll(self, session_id: str, direction: str = "down", amount: int = 500):
        """滚动页面"""
        session = self.sessions[session_id]
        delta = amount if direction == "down" else -amount
        await session.page.mouse.wheel(0, delta)

    async def select_option(self, session_id: str, ref: str, value: str):
        """选择下拉选项（直接 JS，无 ElementHandle）"""
        dom_idx = self._resolve_dom_idx(session_id, ref)
        session = self.sessions[session_id]
        escaped = value.replace("\\", "\\\\").replace("'", "\\'")
        await session.page.evaluate(
            f"(el => {{ el.value = '{escaped}'; el.dispatchEvent(new Event('change', {{bubbles: true}})); }})"
            f"(document.querySelectorAll('{COMBINED_SELECTOR}')[{dom_idx}])"
        )

    async def hover(self, session_id: str, ref: str):
        """悬停元素（通过坐标 + JS 混合）"""
        dom_idx = self._resolve_dom_idx(session_id, ref)
        session = self.sessions[session_id]
        box = await session.page.evaluate(
            f"(el => {{ const r = el.getBoundingClientRect(); return {{x: r.x + r.width/2, y: r.y + r.height/2}}; }})"
            f"(document.querySelectorAll('{COMBINED_SELECTOR}')[{dom_idx}])"
        )
        if box:
            await session.page.mouse.move(box["x"], box["y"])

    async def press_key(self, session_id: str, key: str):
        """按键（Enter, Tab, Escape 等）"""
        session = self.sessions[session_id]
        await session.page.keyboard.press(key)

    async def wait_for_selector(self, session_id: str, selector: str, timeout: int = 10000):
        """等待选择器出现"""
        session = self.sessions[session_id]
        await session.page.wait_for_selector(selector, timeout=timeout)

    async def go_back(self, session_id: str):
        """后退到上一页"""
        session = self.sessions[session_id]
        await session.page.go_back(wait_until="domcontentloaded", timeout=10000)

    async def snapshot(self, session_id: str, interactive_only: bool = False) -> Dict:
        """获取页面快照"""
        session = self.sessions[session_id]

        # 如果有缓存且不是 interactive_only，直接返回缓存
        if session._snapshot_cache and not interactive_only:
            result = session._snapshot_cache
            session._snapshot_cache = None  # 缓存只使用一次
            return result

        page = session.page

        # 单次 JS 评估获取元素列表 + 页面信息（无句柄获取）
        elements, dom_indices, page_info = await generate_refs(page, interactive_only)

        session.dom_indices = dom_indices

        result = {
            "url": page_info["href"],
            "title": page_info["title"],
            "elements": elements,
        }

        return result
