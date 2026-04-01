"""浏览器控制器 - 核心类"""
import asyncio
from typing import Dict, Optional, List
from dataclasses import dataclass
from playwright.async_api import async_playwright, Browser, Page, Playwright, ElementHandle


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

    async def connect(self, cdp_url: str) -> Browser:
        """连接到 CDP 端点"""
        if not self._playwright:
            self._playwright = await async_playwright().start()

        # Playwright connect_over_cdp 需要 HTTP URL，自动转换 ws:// 为 http://
        if cdp_url.startswith("ws://"):
            cdp_url = "http://" + cdp_url[5:]
        browser = await self._playwright.chromium.connect_over_cdp(cdp_url)
        return browser

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
            await session.page.close()
            await session.browser.close()
            del self.sessions[session_id]

    async def open(self, session_id: str, url: str):
        """打开 URL"""
        session = self.sessions[session_id]
        await session.page.goto(url, wait_until="domcontentloaded", timeout=30000)

    async def click(self, session_id: str, ref: str):
        """点击元素"""
        session = self.sessions[session_id]
        idx = int(ref.replace("@e", ""))

        if idx < len(session.elements):
            try:
                await session.elements[idx].click()
                # 等待导航或网络空闲
                await session.page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass  # 超时继续
        else:
            raise ValueError(f"Element {ref} not found. Call snapshot() first.")

    async def fill(self, session_id: str, ref: str, text: str):
        """填充输入框"""
        session = self.sessions[session_id]
        idx = int(ref.replace("@e", ""))

        if idx < len(session.elements):
            try:
                await session.elements[idx].fill(text)
            except Exception:
                pass  # 非输入元素忽略
        else:
            raise ValueError(f"Element {ref} not found. Call snapshot() first.")

    async def snapshot(self, session_id: str, interactive_only: bool = False) -> Dict:
        """获取页面快照"""
        session = self.sessions[session_id]
        page = session.page

        # 清空旧的元素句柄
        session.elements.clear()
        elements = []

        # 获取所有可交互元素
        selectors = ["button", "a", "input", "textarea"]
        for sel in selectors:
            els = await page.query_selector_all(sel)
            for el in els:
                text = await el.text_content() or ""
                elements.append({
                    "ref": f"@e{len(session.elements)}",
                    "text": text.strip()[:50],
                    "role": sel
                })
                session.elements.append(el)

        return {
            "url": page.url,
            "title": await page.title(),
            "elements": elements
        }
