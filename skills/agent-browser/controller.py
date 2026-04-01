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
                # 短暂等待导航开始，不阻塞等 networkidle
                await asyncio.sleep(0.3)
            except Exception:
                pass  # 元素不可点击时继续
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
        """获取页面快照（使用 refs_generator 混合检测）"""
        session = self.sessions[session_id]
        page = session.page

        elements, handles = await generate_refs(page, interactive_only)

        # 更新元素句柄
        session.elements = handles

        return {
            "url": page.url,
            "title": await page.title(),
            "elements": elements
        }

    # ── ReAct 辅助方法 ──

    async def observe(self, session_id: str) -> Dict:
        """Observe: 获取页面状态 + 元素分析"""
        snap = await self.snapshot(session_id)
        page = self.sessions[session_id].page

        # 统计元素类型
        role_counts = {}
        for el in snap["elements"]:
            role_counts[el["role"]] = role_counts.get(el["role"], 0) + 1

        return {
            **snap,
            "element_summary": role_counts,
            "interactive_count": sum(v for k, v in role_counts.items()
                                     if k in ("a", "button", "input", "select")),
        }

    async def reason_and_act(self, session_id: str, goal: str, observation: Dict) -> Dict:
        """Reason & Act: 根据目标和观察执行操作"""
        elements = observation.get("elements", [])
        actions_taken = []

        # 简单的关键词匹配执行（真实场景由 LLM 驱动）
        goal_lower = goal.lower()

        for el in elements:
            text = el.get("text", "").lower()
            role = el.get("role", "")

            # 搜索类目标
            if "搜索" in goal_lower and role == "input" and not actions_taken:
                keyword = goal.split("搜索")[-1].strip() if "搜索" in goal else ""
                if keyword:
                    await self.fill(session_id, el["ref"], keyword)
                    actions_taken.append(f"fill({el['ref']}, '{keyword}')")

            # 点击类目标
            if any(w in goal_lower for w in ("点击", "打开", "提交", "搜索")):
                if role == "button" and text and not any("click" in a for a in actions_taken):
                    await self.click(session_id, el["ref"])
                    actions_taken.append(f"click({el['ref']})")

        return {"actions": actions_taken, "observation": observation}

    async def check_result(self, session_id: str, expected: str) -> Dict:
        """Check: 验证当前页面是否符合预期"""
        snap = await self.snapshot(session_id)
        elements = snap.get("elements", [])
        expected_lower = expected.lower()

        found = any(expected_lower in el.get("text", "").lower() for el in elements)
        url_match = expected_lower in snap.get("url", "").lower()
        title_match = expected_lower in snap.get("title", "").lower()

        return {
            "success": found or url_match or title_match,
            "url": snap["url"],
            "title": snap["title"],
            "match_type": "text" if found else ("url" if url_match else ("title" if title_match else "none")),
        }
