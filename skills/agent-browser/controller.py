"""浏览器控制器 - 核心类"""
import asyncio
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
                # 智能等待：如果触发导航则等待 domcontentloaded，否则快速返回
                try:
                    await session.page.wait_for_load_state("domcontentloaded", timeout=500)
                except Exception:
                    pass
            except Exception:
                pass  # 元素不可点击时继续
        else:
            raise ValueError(f"Element {ref} not found. Call snapshot() first.")

    async def fill(self, session_id: str, ref: str, text: str):
        """填充输入框"""
        session = self.sessions[session_id]
        idx = int(ref.replace("@e", ""))

        if idx >= len(session.elements):
            raise ValueError(f"Element {ref} not found. Call snapshot() first.")

        try:
            await session.elements[idx].fill(text)
        except Exception as e:
            # 尝试 click + type 作为回退（某些元素不支持 fill）
            try:
                await session.elements[idx].click()
                await session.page.keyboard.type(text, delay=50)
            except Exception:
                pass

    # JS 提取页面可见文本摘要（body 前 500 字符，跳过 script/style）
    _PAGE_TEXT_JS = """
    () => {
        const body = document.body;
        if (!body) return '';
        const clone = body.cloneNode(true);
        clone.querySelectorAll('script,style,noscript,svg').forEach(e => e.remove());
        return (clone.textContent || '').replace(/\\s+/g, ' ').trim().substring(0, 500);
    }
    """

    async def snapshot(self, session_id: str, interactive_only: bool = False) -> Dict:
        """获取页面快照"""
        session = self.sessions[session_id]
        page = session.page

        # 并行获取元素列表、页面信息、页面文本摘要
        (elements_info, url, title, page_text) = await asyncio.gather(
            generate_refs(page, interactive_only),
            page.evaluate("() => location.href"),
            page.title(),
            page.evaluate(self._PAGE_TEXT_JS),
        )
        elements, handles = elements_info

        session.elements = handles

        return {"url": url, "title": title, "page_text": page_text, "elements": elements}
