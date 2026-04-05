"""ExtensionBackend — 通过 Chrome Extension 操作用户真实浏览器

架构：
  CLI/LLM → Daemon (HTTP) → WebSocket → Chrome Extension → chrome.debugger → 用户真实 Chrome

优势：
- 自然指纹（用户真实 Chrome，非 CloakBrowser 合成）
- 继承登录状态（cookies、session）
- 零配置（安装 Extension 即可）

Fallback: 无 Extension 时自动回退到 LocalCDPBackend (CloakBrowser)
"""
import sys
from pathlib import Path
import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional

_project_root = str(Path(__file__).resolve().parent.parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from . import BrowserBackend, BrowserPageHandle

logger = logging.getLogger(__name__)


class ExtensionPageHandle(BrowserPageHandle):
    """
    通过 ExtensionBridge + chrome.debugger 的页面句柄。

    每个方法都翻译为 Extension 命令，通过 WebSocket 发送到 Chrome Extension。
    """

    def __init__(self, bridge: "ExtensionBridge", session_id: str):
        self._bridge = bridge
        self._session_id = session_id
        self._listeners: Dict[str, List[Callable]] = {}

    async def _send(self, method: str, params: Dict[str, Any] | None = None, timeout: float = 30.0) -> Any:
        """发送命令到 Extension 并返回结果"""
        return await self._bridge.send_command(method, params, timeout)

    async def goto(self, url: str, wait_until: str = "domcontentloaded", timeout: int = 15000) -> None:
        await self._send("navigate", {"url": url, "timeout": timeout})

    async def go_back(self, wait_until: str = "domcontentloaded", timeout: int = 10000) -> None:
        # 通过 JS history.back() 实现
        await self._send("evaluate", {"expression": "history.back()"})

    async def evaluate(self, expression: str) -> Any:
        return await self._send("evaluate", {"expression": expression})

    async def wait_for_selector(self, selector: str, timeout: int = 10000) -> None:
        # 通过轮询等待选择器出现
        js = f"""
        (() => {{
            const start = Date.now();
            return new Promise((resolve) => {{
                const check = () => {{
                    if (document.querySelector('{selector}')) resolve(true);
                    else if (Date.now() - start > {timeout}) resolve(false);
                    else setTimeout(check, 100);
                }};
                check();
            }});
        }})()
        """
        result = await self._send("evaluate", {"expression": js, "timeout": timeout + 2000})
        if not result:
            raise TimeoutError(f"Selector '{selector}' not found within {timeout}ms")

    async def mouse_wheel(self, delta_x: int, delta_y: int) -> None:
        js = f"window.scrollBy({delta_x}, {delta_y})"
        await self._send("evaluate", {"expression": js})

    async def mouse_move(self, x: float, y: float) -> None:
        # Note: chrome.debugger Input.dispatchMouseEvent 可用但复杂
        # 简化实现：通过 JS 触发 mousemove 事件（不移动真实光标）
        js = f"document.dispatchEvent(new MouseEvent('mousemove', {{clientX: {x}, clientY: {y}}}))"  # noqa: E501
        await self._send("evaluate", {"expression": js})

    async def keyboard_press(self, key: str) -> None:
        # Map common key names to KeyboardEvent keys
        key_map = {
            "Enter": "Enter",
            "Tab": "Tab",
            "Escape": "Escape",
            "Backspace": "Backspace",
            "ArrowDown": "ArrowDown",
            "ArrowUp": "ArrowUp",
        }
        k = key_map.get(key, key)
        js = f"document.dispatchEvent(new KeyboardEvent('keydown', {{key: '{k}', code: '{k}'}}))"
        await self._send("evaluate", {"expression": js})

    async def title(self) -> str:
        result = await self._send("getTitle")
        return result or ""

    async def url(self) -> str:
        result = await self._send("getUrl")
        return result or ""

    async def on(self, event: str, handler: Callable) -> None:
        # Extension mode doesn't support real-time event streaming like Playwright
        # Store handlers for compatibility; network interception not supported in this mode
        if event not in self._listeners:
            self._listeners[event] = []
        self._listeners[event].append(handler)
        logger.debug(f"ExtensionPageHandle.on({event}) — event streaming not supported in Extension mode")

    def remove_listener(self, event: str, handler: Callable) -> None:
        if event in self._listeners:
            self._listeners[event] = [h for h in self._listeners[event] if h != handler]

    async def close(self) -> None:
        # Extension manages its own tab lifecycle; no explicit close needed
        self._listeners.clear()


class ExtensionBackend(BrowserBackend):
    """
    通过 Chrome Extension 操作真实浏览器的后端。

    使用流程：
    1. 用户安装 Agent Browser Bridge Chrome Extension
    2. Extension 自动连接到 Daemon 的 WebSocket (ws://127.0.0.1:19825/ext)
    3. 所有浏览器操作通过 Extension → chrome.debugger → 用户真实 Chrome
    """

    def __init__(self, config):
        from ..daemon import BrowserDaemon, ExtensionBridge
        self._config = config
        self._daemon: Optional[BrowserDaemon] = None
        self._bridge: Optional[ExtensionBridge] = None
        self._sessions: Dict[str, ExtensionPageHandle] = {}

    async def connect(self) -> None:
        """连接到 Daemon 并确保 Extension Bridge 就绪"""
        from ..daemon import BrowserDaemon

        self._daemon = BrowserDaemon.get(self._config)
        await self._daemon.ensure_connected()

        self._bridge = self._daemon.extension_bridge
        if not self._bridge or not self._bridge.is_connected:
            raise ConnectionError(
                "Chrome Extension not connected. "
                "Please install the Agent Browser Bridge extension and ensure Chrome is running."
            )

        logger.info("ExtensionBackend connected via Chrome Extension")

    async def disconnect(self) -> None:
        """断开连接（不关闭 Daemon，由 Daemon 自行管理生命周期）"""
        for sid in list(self._sessions.keys()):
            await self.delete_session(sid)
        self._bridge = None
        logger.info("ExtensionBackend disconnected")

    async def is_connected(self) -> bool:
        return self._bridge is not None and self._bridge.is_connected

    async def create_session(self, session_id: str) -> ExtensionPageHandle:
        """创建会话（Extension 会自动创建自动化标签页）"""
        if not self._bridge:
            await self.connect()

        handle = ExtensionPageHandle(self._bridge, session_id)
        self._sessions[session_id] = handle
        logger.info(f"Extension session created: {session_id}")
        return handle

    async def delete_session(self, session_id: str) -> None:
        """删除会话"""
        handle = self._sessions.pop(session_id, None)
        if handle:
            await handle.close()
        logger.info(f"Extension session deleted: {session_id}")

    async def get_page(self, session_id: str) -> ExtensionPageHandle:
        if session_id not in self._sessions:
            raise ValueError(f"Session {session_id} not found")
        return self._sessions[session_id]

    async def run_task(
        self,
        session_id: str,
        task: str,
        intelligence: str = "agent",
        llm_config: Optional[Dict] = None,
        max_steps: int = 6,
        total_timeout: float = 300.0,
        **kwargs,
    ) -> Dict:
        """
        Extension 模式暂不支持 browser-use Agent（需要 Playwright 直连）。
        返回 LLM 模式工具描述，让调用方使用原子操作。
        """
        if intelligence != "agent":
            return {
                "status": "ready",
                "mode": "llm",
                "session_id": session_id,
                "tools": ["snapshot", "click", "fill", "scroll", "go_back", "hover", "press_key"],
                "backend": "extension",
            }

        # Extension 模式下 Agent 任务通过原子操作组合实现
        # （browser-use 需要 Playwright 直连，Extension 模式使用 chrome.debugger）
        return {
            "status": "limited",
            "error": "Agent mode requires Playwright direct connection. Use LLM mode with atomic operations in Extension backend.",
            "backend": "extension",
            "tools": ["goto", "evaluate", "wait_for_selector", "snapshot"],
        }
