"""后端抽象 — 参考 opencli IBrowserFactory + IPage 模式"""
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Callable


class BrowserPageHandle(ABC):
    """
    统一页面操作接口。
    参考 opencli IPage/BasePage — 传输无关的页面操作抽象。

    两种实现：
    - PlaywrightPageHandle: 委托 Playwright Page（本地 CDP）
    - RemotePageHandle: 翻译为 HTTP REST 调用（远程 API）
    """

    # ── 导航 ──

    @abstractmethod
    async def goto(self, url: str, wait_until: str = "domcontentloaded", timeout: int = 8000) -> None:
        """导航到 URL"""

    @abstractmethod
    async def go_back(self, wait_until: str = "domcontentloaded", timeout: int = 10000) -> None:
        """后退"""

    # ── JavaScript 执行 ──

    @abstractmethod
    async def evaluate(self, expression: str) -> Any:
        """执行 JavaScript 并返回结果"""

    # ── 元素操作 ──

    @abstractmethod
    async def wait_for_selector(self, selector: str, timeout: int = 10000) -> None:
        """等待选择器出现"""

    # ── 鼠标 / 键盘 ──

    @abstractmethod
    async def mouse_wheel(self, delta_x: int, delta_y: int) -> None:
        """鼠标滚轮"""

    @abstractmethod
    async def mouse_move(self, x: float, y: float) -> None:
        """移动鼠标"""

    @abstractmethod
    async def keyboard_press(self, key: str) -> None:
        """按键"""

    # ── 页面信息 ──

    @abstractmethod
    async def title(self) -> str:
        """获取页面标题"""

    @abstractmethod
    async def url(self) -> str:
        """获取当前 URL"""

    # ── 事件监听 ──

    @abstractmethod
    async def on(self, event: str, handler: Callable) -> None:
        """注册事件监听器（explore 网络拦截需要）"""

    @abstractmethod
    def remove_listener(self, event: str, handler: Callable) -> None:
        """移除事件监听器"""

    # ── 生命周期 ──

    @abstractmethod
    async def close(self) -> None:
        """关闭页面"""


class BrowserBackend(ABC):
    """
    浏览器后端抽象。
    参考 opencli IBrowserFactory — 创建和管理浏览器会话。

    两种实现：
    - LocalCDPBackend: Playwright CDP 直连（本地浏览器）
    - RemoteAPIBackend: HTTP REST 到 FastAPI（远程/本地服务）
    """

    @abstractmethod
    async def connect(self) -> None:
        """建立浏览器连接"""

    @abstractmethod
    async def disconnect(self) -> None:
        """断开浏览器连接"""

    @abstractmethod
    async def is_connected(self) -> bool:
        """检查连接是否存活"""

    @abstractmethod
    async def create_session(self, session_id: str) -> BrowserPageHandle:
        """创建浏览器会话（context + page），返回页面句柄"""

    @abstractmethod
    async def delete_session(self, session_id: str) -> None:
        """删除浏览器会话"""

    @abstractmethod
    async def get_page(self, session_id: str) -> BrowserPageHandle:
        """获取会话的页面句柄"""
