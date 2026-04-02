"""浏览器控制器 - 核心类"""
import asyncio
import base64
from typing import Dict, Optional, List
from dataclasses import dataclass
from playwright.async_api import async_playwright, Browser, Page, Playwright, ElementHandle
from .refs_generator import generate_refs


@dataclass
class BrowserSession:
    """浏览器会话"""
    session_id: str
    browser: Browser
    page: Page
    elements: List[ElementHandle]  # 存储元素句柄
    created_at: float


class BrowserController:
    """浏览器控制器"""

    def __init__(self):
        self.sessions: Dict[str, BrowserSession] = {}
        self._playwright: Optional[Playwright] = None

    async def connect(self, cdp_url: str, retries: int = 3) -> Browser:
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
                    await asyncio.sleep(1.0 * (attempt + 1))
        raise last_err

    async def create_session(self, session_id: str, cdp_url: str = "http://127.0.0.1:19222") -> BrowserSession:
        """创建会话"""
        browser = await self.connect(cdp_url)
        context = await browser.new_context()
        page = await context.new_page()

        session = BrowserSession(
            session_id=session_id,
            browser=browser,
            page=page,
            elements=[],
            created_at=asyncio.get_event_loop().time()
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
        await session.page.goto(url, wait_until="domcontentloaded", timeout=30000)

    async def click(self, session_id: str, ref: str):
        """点击元素"""
        session = self.sessions[session_id]
        idx = int(ref.replace("@e", ""))

        if idx >= len(session.elements):
            raise ValueError(f"Element {ref} not found (have {len(session.elements)} elements). Call snapshot() first.")

        try:
            await session.elements[idx].click()
            # 智能等待：如果触发导航则等待 domcontentloaded，否则快速返回
            try:
                await session.page.wait_for_load_state("domcontentloaded", timeout=50)
            except Exception:
                pass
        except Exception:
            # Fallback: use JS click() for elements that Playwright can't click
            try:
                await session.elements[idx].evaluate("el => el.click()")
            except Exception:
                pass

    async def fill(self, session_id: str, ref: str, text: str):
        """填充输入框"""
        session = self.sessions[session_id]
        idx = int(ref.replace("@e", ""))

        if idx >= len(session.elements):
            raise ValueError(f"Element {ref} not found. Call snapshot() first.")

        try:
            await session.elements[idx].fill(text)
        except Exception:
            # 回退: click + type（支持 contenteditable 等非标准输入元素）
            try:
                await session.elements[idx].click()
                await session.page.keyboard.type(text, delay=50)
            except Exception:
                # Fallback: JS value set
                try:
                    await session.elements[idx].evaluate(f"el => {{ el.value = '{text}'; el.dispatchEvent(new Event('input', {{bubbles: true}})); }}")
                except Exception:
                    pass

    async def scroll(self, session_id: str, direction: str = "down", amount: int = 500):
        """滚动页面"""
        session = self.sessions[session_id]
        delta = amount if direction == "down" else -amount
        await session.page.mouse.wheel(0, delta)

    async def select_option(self, session_id: str, ref: str, value: str):
        """选择下拉选项"""
        session = self.sessions[session_id]
        idx = int(ref.replace("@e", ""))
        if idx >= len(session.elements):
            raise ValueError(f"Element {ref} not found. Call snapshot() first.")
        await session.elements[idx].select_option(value)

    async def hover(self, session_id: str, ref: str):
        """悬停元素"""
        session = self.sessions[session_id]
        idx = int(ref.replace("@e", ""))
        if idx >= len(session.elements):
            raise ValueError(f"Element {ref} not found. Call snapshot() first.")
        await session.elements[idx].hover()

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
        await session.page.go_back(wait_until="domcontentloaded", timeout=15000)

    # JS 提取页面可见文本摘要 + 滚动状态 + 标题
    _PAGE_INFO_JS = """
    () => {
        const pageText = (document.body?.innerText || '').replace(/\\s+/g, ' ').trim().substring(0, 80);
        const scrollMax = Math.max(document.documentElement.scrollHeight - window.innerHeight, 1);
        return {
            href: location.href,
            title: document.title,
            pageText: pageText,
            scrollPercent: Math.round(scrollY / scrollMax * 100),
        };
    }
    """

    async def snapshot(self, session_id: str, interactive_only: bool = False) -> Dict:
        """获取页面快照"""
        session = self.sessions[session_id]
        page = session.page

        # 并行获取元素列表 + 页面信息（screenshot removed for speed）
        results = await asyncio.gather(
            generate_refs(page, interactive_only),
            page.evaluate(self._PAGE_INFO_JS),
            return_exceptions=True,
        )
        elements_info, page_info = results[0], results[1]
        elements, handles = elements_info

        session.elements = handles

        result = {
            "url": page_info["href"],
            "title": page_info["title"],
            "page_text": page_info["pageText"],
            "scroll_percent": page_info["scrollPercent"],
            "elements": elements,
        }

        return result
