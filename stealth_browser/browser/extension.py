"""ExtensionBackend -- operates on user's real browser via Chrome Extension.

Architecture:
  CLI/LLM -> Daemon (HTTP) -> WebSocket -> Chrome Extension -> chrome.debugger -> User's real Chrome

Advantages:
- Natural fingerprint (user's real Chrome, not CloakBrowser-synthesized)
- Inherits login state (cookies, sessions)
- Zero configuration (just install the Extension)

Fallback: when no Extension is available, automatically falls back to LocalCDPBackend (CloakBrowser)
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .daemon import ExtensionBridge
from typing import Any

from . import BrowserBackend, BrowserPageHandle

logger = logging.getLogger(__name__)


class ExtensionPageHandle(BrowserPageHandle):
    """Page handle via ExtensionBridge + chrome.debugger.

    Each method is translated into an Extension command sent over WebSocket
    to the Chrome Extension.
    """

    def __init__(self, bridge: ExtensionBridge, session_id: str):
        self._bridge = bridge
        self._session_id = session_id
        self._listeners: dict[str, list[Callable]] = {}

    async def _send(self, method: str, params: dict[str, Any] | None = None, timeout: float = 30.0) -> Any:
        """Send command to Extension and return result."""
        return await self._bridge.send_command(method, params, timeout)

    async def goto(self, url: str, wait_until: str = "domcontentloaded", timeout: int = 15000) -> None:
        await self._send("navigate", {"url": url, "timeout": timeout})

    async def go_back(self, wait_until: str = "domcontentloaded", timeout: int = 10000) -> None:
        # Implemented via JS history.back()
        await self._send("evaluate", {"expression": "history.back()"})

    async def evaluate(self, expression: str) -> Any:
        return await self._send("evaluate", {"expression": expression})

    async def wait_for_selector(self, selector: str, timeout: int = 10000) -> None:
        # Poll for selector appearance via JS
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
        # Note: chrome.debugger Input.dispatchMouseEvent is available but complex.
        # Simplified implementation: trigger mousemove event via JS (does not move real cursor).
        js = f"document.dispatchEvent(new MouseEvent('mousemove', {{clientX: {x}, clientY: {y}}}))"
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
        # Extension mode does not support real-time event streaming like Playwright.
        # Store handlers for compatibility; network interception not supported in this mode.
        if event not in self._listeners:
            self._listeners[event] = []
        self._listeners[event].append(handler)
        logger.debug(f"ExtensionPageHandle.on({event}) -- event streaming not supported in Extension mode")

    def remove_listener(self, event: str, handler: Callable) -> None:
        if event in self._listeners:
            self._listeners[event] = [h for h in self._listeners[event] if h != handler]

    async def close(self) -> None:
        # Extension manages its own tab lifecycle; no explicit close needed.
        self._listeners.clear()


class ExtensionBackend(BrowserBackend):
    """Backend that operates on a real browser via Chrome Extension.

    Usage flow:
    1. User installs Stealth Browser Bridge Chrome Extension
    2. Extension auto-connects to Daemon WebSocket (ws://127.0.0.1:19825/ext)
    3. All browser operations go through Extension -> chrome.debugger -> user's real Chrome
    """

    def __init__(self, config):
        from stealth_browser.browser.daemon import BrowserDaemon

        self._config = config
        self._daemon: BrowserDaemon | None = None
        self._bridge: ExtensionBridge | None = None
        self._sessions: dict[str, ExtensionPageHandle] = {}

    async def connect(self) -> None:
        """Connect to Daemon and ensure Extension Bridge is ready."""
        from stealth_browser.browser.daemon import BrowserDaemon

        self._daemon = BrowserDaemon.get(self._config)
        await self._daemon.ensure_connected()

        self._bridge = self._daemon.extension_bridge
        if not self._bridge or not self._bridge.is_connected:
            raise ConnectionError(
                "Chrome Extension not connected. "
                "Please install the Stealth Browser Bridge extension and ensure Chrome is running."
            )

        logger.info("ExtensionBackend connected via Chrome Extension")

    async def disconnect(self) -> None:
        """Disconnect (do not shut down Daemon; it manages its own lifecycle)."""
        for sid in list(self._sessions.keys()):
            await self.delete_session(sid)
        self._bridge = None
        logger.info("ExtensionBackend disconnected")

    async def is_connected(self) -> bool:
        return self._bridge is not None and self._bridge.is_connected

    async def create_session(self, session_id: str) -> ExtensionPageHandle:
        """Create a session (Extension will auto-create an automation tab)."""
        if not self._bridge:
            await self.connect()

        handle = ExtensionPageHandle(self._bridge, session_id)
        self._sessions[session_id] = handle
        logger.info(f"Extension session created: {session_id}")
        return handle

    async def delete_session(self, session_id: str) -> None:
        """Delete a session."""
        handle = self._sessions.pop(session_id, None)
        if handle:
            await handle.close()
        logger.info(f"Extension session deleted: {session_id}")

    async def get_page(self, session_id: str) -> ExtensionPageHandle:
        if session_id not in self._sessions:
            raise ValueError(f"Session {session_id} not found")
        return self._sessions[session_id]

    async def snapshot(self, session_id: str, interactive_only: bool = False) -> dict:
        """Get page snapshot via Extension (chrome.debugger DOM extraction).

        Delegates to the Chrome Extension which runs JS via debugger to extract
        interactive elements with @eN ref assignment.

        Returns the same format as LocalCDPBackend.snapshot():
        {url, title, elements: [{ref, text, role}]}
        """
        if not self._bridge:
            await self.connect()

        handle = self._sessions.get(session_id)
        if handle:
            result = await handle._send("snapshot", {"interactive_only": interactive_only}, timeout=15.0)
        else:
            # No handle yet; send via bridge directly
            result = await self._bridge.send_command("snapshot", {"interactive_only": interactive_only}, timeout=15.0)

        if isinstance(result, dict) and "url" in result:
            return result

        # Fallback: construct minimal snapshot from individual calls
        url = await self.url() or ""
        title = await self.title() or ""
        logger.warning("Extension snapshot returned unexpected format, using fallback")
        return {"url": url, "title": title, "elements": result if isinstance(result, list) else []}

    async def run_task(
        self,
        session_id: str,
        task: str,
        intelligence: str = "agent",
        llm_config: dict | None = None,
        max_steps: int = 6,
        total_timeout: float = 300.0,
        **kwargs,
    ) -> dict:
        """Extension mode does not support browser-use Agent (requires direct Playwright connection).

        Returns LLM-mode tool descriptions so the caller can use atomic operations.
        """
        if intelligence != "agent":
            return {
                "status": "ready",
                "mode": "llm",
                "session_id": session_id,
                "tools": ["snapshot", "click", "fill", "scroll", "go_back", "hover", "select_option", "press_key"],
                "backend": "extension",
            }

        # In Extension mode, Agent tasks are implemented via atomic operation composition
        # (browser-use requires direct Playwright connection; Extension mode uses chrome.debugger)
        return {
            "status": "limited",
            "error": "Agent mode requires Playwright direct connection. Use LLM mode with atomic operations in Extension backend.",
            "backend": "extension",
            "tools": ["goto", "evaluate", "wait_for_selector", "snapshot"],
        }
