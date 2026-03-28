"""浏览器控制器"""
import asyncio
from typing import Dict, Optional
from playwright.async_api import async_playwright, Browser, Page


class BrowserController:
    def __init__(self):
        self.sessions: Dict[str, Dict] = {}
        self.playwright = None
        self.browser: Optional[Browser] = None

    async def create_session(self, cdp_url: Optional[str] = None) -> str:
        """创建会话"""
        import uuid
        session_id = str(uuid.uuid4())

        if not self.playwright:
            self.playwright = await async_playwright().start()

        if cdp_url:
            self.browser = await self.playwright.chromium.connect_over_cdp(cdp_url)
        else:
            self.browser = await self.playwright.chromium.launch(headless=False)

        context = await self.browser.new_context()
        page = await context.new_page()

        self.sessions[session_id] = {"page": page, "context": context}
        return session_id

    async def open_page(self, session_id: str, url: str):
        """打开页面"""
        page = self.sessions[session_id]["page"]
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)

    async def snapshot(self, session_id: str, interactive_only: bool = False) -> Dict:
        """获取快照"""
        page = self.sessions[session_id]["page"]
        elements = []
        element_handles = []

        # 简化实现：获取所有可交互元素
        selectors = ["button", "a", "input", "textarea"]
        for sel in selectors:
            els = await page.query_selector_all(sel)
            for el in els:
                text = await el.text_content() or ""
                elements.append({"ref": f"@e{len(elements)}", "text": text.strip(), "role": sel})
                element_handles.append(el)

        # 存储元素句柄供后续使用
        self.sessions[session_id]["elements"] = element_handles

        return {"url": page.url, "elements": elements}

    async def click(self, session_id: str, ref: str):
        """点击元素"""
        page = self.sessions[session_id]["page"]
        idx = int(ref.replace("@e", ""))

        # 使用存储的元素句柄
        if "elements" in self.sessions[session_id]:
            elements = self.sessions[session_id]["elements"]
            if idx < len(elements):
                try:
                    await elements[idx].click()
                    # 等待导航或网络空闲
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except Exception as e:
                    # 如果等待超时，继续执行
                    pass
                return

        raise ValueError(f"Element {ref} not found. Call snapshot() first.")

    async def fill(self, session_id: str, ref: str, text: str):
        """填充输入"""
        page = self.sessions[session_id]["page"]
        idx = int(ref.replace("@e", ""))

        # 使用存储的元素句柄
        if "elements" in self.sessions[session_id]:
            elements = self.sessions[session_id]["elements"]
            if idx < len(elements):
                try:
                    await elements[idx].fill(text)
                except Exception as e:
                    # 如果不是输入元素，忽略错误
                    pass
                return

        raise ValueError(f"Element {ref} not found. Call snapshot() first.")


_controller = BrowserController()


async def create_session(cdp_url: Optional[str] = None) -> str:
    return await _controller.create_session(cdp_url)


async def open_page(session_id: str, url: str):
    await _controller.open_page(session_id, url)


async def snapshot(session_id: str, interactive_only: bool = False) -> Dict:
    return await _controller.snapshot(session_id, interactive_only)


async def click(session_id: str, ref: str):
    await _controller.click(session_id, ref)


async def fill(session_id: str, ref: str, text: str):
    await _controller.fill(session_id, ref, text)
