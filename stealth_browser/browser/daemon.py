"""Micro Daemon -- in-process persistent browser connection singleton.

Design inspired by the daemon + IdleManager dual-condition pattern:
- Uses an in-process singleton (because the skill runs inside a long-lived Claude REPL)
- Shared concepts: IdleManager dual-condition exit, state persistence, auto-reconnect
- Added: WebSocket server for Chrome Extension connections
"""

import asyncio
import contextlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from stealth_browser.config import SkillConfig

logger = logging.getLogger(__name__)


# -- Extension Bridge Types --


class ExtensionCommand:
    """Command sent to Chrome Extension."""

    def __init__(self, method: str, params: dict[str, Any] | None = None):
        self.id = f"cmd_{time.time_ns()}"
        self.method = method
        self.params = params or {}
        self._future: asyncio.Future = asyncio.get_event_loop().create_future()

    @property
    def future(self) -> asyncio.Future:
        return self._future


class ExtensionBridge:
    """WebSocket server for Chrome Extension connections.

    Security model:
    - Only accepts localhost connections
    - Heartbeat detection (15s ping/pong)
    - Command queue + Future matching for request/response
    """

    def __init__(self, port: int = 19825):
        self._port = port
        self._server: Any | None = None  # websockets.serve
        self._ws: Any | None = None  # WebSocket connection
        self._commands: dict[str, ExtensionCommand] = {}  # id -> Command
        self._connected = False
        self._heartbeat_task: asyncio.Task | None = None
        self._missed_pongs = 0

    @property
    def is_connected(self) -> bool:
        return self._connected and self._ws is not None

    async def start(self) -> None:
        """Start WebSocket server and wait for Extension to connect."""
        if self._server:
            return

        try:
            import websockets
        except ImportError:
            logger.warning("websockets not installed. Extension bridge disabled. Run: pip install websockets")
            return

        async def _handler(ws, path: str):
            # Only accept connections on /ext path
            if path != "/ext":
                await ws.close(4004, "Invalid path")
                return

            logger.info(f"Extension connected from {ws.remote_address}")
            self._ws = ws
            self._connected = True
            self._missed_pongs = 0

            try:
                # Start heartbeat
                self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(ws))

                # Message loop
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        msg_type = msg.get("type")

                        if msg_type == "pong":
                            self._missed_pongs = 0
                        elif "id" in msg and "data" in msg:
                            # Response message: match pending command
                            cmd_id = msg["id"]
                            cmd = self._commands.pop(cmd_id, None)
                            if cmd and not cmd.future.done():
                                if msg.get("error"):
                                    cmd.future.set_exception(RuntimeError(msg["error"]))
                                else:
                                    cmd.future.set_result(msg["data"])
                        elif msg.get("id") == "ready":
                            logger.info(f"Extension ready: {msg.get('data', {})}")
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON from extension: {raw[:200]}")
                    except Exception as e:
                        logger.error(f"Extension message error: {e}")
            finally:
                self._connected = False
                self._ws = None
                if self._heartbeat_task:
                    self._heartbeat_task.cancel()
                    self._heartbeat_task = None
                # Cancel all pending commands
                for cmd in self._commands.values():
                    if not cmd.future.done():
                        cmd.future.set_exception(ConnectionError("Extension disconnected"))
                self._commands.clear()
                logger.info("Extension disconnected")

        self._server = await websockets.serve(_handler, "127.0.0.1", self._port)
        logger.info(f"Extension bridge listening on ws://127.0.0.1:{self._port}/ext")

    async def stop(self) -> None:
        """Stop WebSocket server."""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None
        if self._ws:
            with contextlib.suppress(Exception):
                await self._ws.close()
            self._ws = None
        self._connected = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def send_command(self, method: str, params: dict[str, Any] | None = None, timeout: float = 30.0) -> Any:
        """Send command to Extension and wait for response."""
        if not self._connected or not self._ws:
            raise ConnectionError("Extension not connected")

        cmd = ExtensionCommand(method, params)
        self._commands[cmd.id] = cmd

        try:
            payload = {"id": cmd.id, "method": cmd.method, "params": cmd.params}
            await self._ws.send(json.dumps(payload))
            return await asyncio.wait_for(cmd.future, timeout=timeout)
        except TimeoutError:
            self._commands.pop(cmd.id, None)
            raise TimeoutError(f"Extension command '{method}' timed out after {timeout}s") from None
        except Exception:
            self._commands.pop(cmd.id, None)
            raise

    async def _heartbeat_loop(self, ws) -> None:
        """Heartbeat loop: send ping every 15 seconds."""
        try:
            while True:
                await asyncio.sleep(15)
                if not self._connected:
                    break
                try:
                    await ws.send(json.dumps({"type": "ping"}))
                    self._missed_pongs += 1
                    if self._missed_pongs >= 2:
                        logger.warning("Extension missed heartbeats, closing connection")
                        await ws.close(1011, "Missed heartbeats")
                        break
                except Exception:
                    break
        except asyncio.CancelledError:
            pass


class BrowserDaemon:
    """In-process persistent browser connection singleton.

    Lifecycle:
    1. Lazy connect on first browser command (ensure_connected)
    2. Keep Playwright + CDP connection alive across session create/delete
    3. Dual-condition idle disconnect: no active sessions AND past idle_timeout
    4. Auto-reconnect on next command
    5. State persisted to ~/.stealth-browser/daemon-state.json
    """

    _instance: Optional["BrowserDaemon"] = None

    def __init__(self, config: SkillConfig):
        self._config = config
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._connected = False
        self._sessions: dict[str, dict[str, Any]] = {}  # session_id -> {context, page, created_at}
        self._last_activity = time.time()
        self._idle_task: asyncio.Task | None = None
        self._state_path = Path(config.daemon_state_path).expanduser()
        # Extension Bridge (WebSocket server for Chrome Extension)
        self._extension_bridge: ExtensionBridge | None = None

    @classmethod
    def get(cls, config: SkillConfig = None) -> "BrowserDaemon":
        """Singleton accessor."""
        if cls._instance is None:
            cls._instance = cls(config or SkillConfig())
        return cls._instance

    @classmethod
    def reset(cls):
        """Reset singleton (for testing only)."""
        cls._instance = None

    # -- Connection management --

    async def ensure_connected(self) -> None:
        """Ensure browser is connected (lazy connect + auto-reconnect)."""
        # Start Extension Bridge if not yet started
        if not self._extension_bridge:
            self._extension_bridge = ExtensionBridge(port=19825)
            await self._extension_bridge.start()

        if self._connected and self._browser:
            try:
                _ = self._browser.contexts  # Liveness check
                self._touch_activity()
                return
            except Exception:
                logger.info("Browser disconnected, reconnecting...")
                self._connected = False

        # Try to restore state
        state = self._load_state()
        cdp_url = state.get("cdp_url", self._config.cdp_url)

        if not self._playwright:
            self._playwright = await async_playwright().start()

        # Connect via CDP (with retry)
        if cdp_url.startswith("ws://"):
            cdp_url = "http://" + cdp_url[5:]

        retries = 3
        for attempt in range(retries):
            try:
                self._browser = await self._playwright.chromium.connect_over_cdp(cdp_url)
                self._connected = True
                self._touch_activity()
                self._start_idle_monitor()
                logger.info(f"Daemon connected to CDP: {cdp_url}")
                return
            except Exception as e:
                if attempt < retries - 1:
                    await asyncio.sleep(0.3 * (attempt + 1))
                else:
                    raise ConnectionError(f"Failed to connect to CDP at {cdp_url}: {e}") from e

    async def disconnect(self) -> None:
        """Disconnect browser."""
        self._stop_idle_monitor()

        # Stop Extension Bridge
        if self._extension_bridge:
            await self._extension_bridge.stop()
            self._extension_bridge = None

        # Close all sessions
        for sid in list(self._sessions.keys()):
            await self.destroy_context(sid)

        if self._browser:
            with contextlib.suppress(Exception):
                await self._browser.close()
            self._browser = None

        self._connected = False
        self._persist_state()
        logger.info("Daemon disconnected")

    async def shutdown(self) -> None:
        """Full shutdown including Playwright."""
        await self.disconnect()
        if self._playwright:
            with contextlib.suppress(Exception):
                await self._playwright.stop()
            self._playwright = None
        BrowserDaemon._instance = None
        logger.info("Daemon shutdown complete")

    # -- Session management --

    async def create_context(self, session_id: str) -> tuple[BrowserContext, Page]:
        """Create a new context + page on the persistent browser connection."""
        await self.ensure_connected()
        context = await self._browser.new_context()
        page = await context.new_page()

        self._sessions[session_id] = {
            "context": context,
            "page": page,
            "created_at": time.time(),
        }
        self._touch_activity()
        self._persist_state()
        return context, page

    async def destroy_context(self, session_id: str) -> None:
        """Close context + page but keep browser connection alive."""
        session = self._sessions.pop(session_id, None)
        if session:
            with contextlib.suppress(Exception):
                await session["page"].close()
            with contextlib.suppress(Exception):
                await session["context"].close()
        self._touch_activity()
        self._persist_state()

    def get_page(self, session_id: str) -> Page | None:
        """Get the Playwright Page for a session."""
        session = self._sessions.get(session_id)
        return session["page"] if session else None

    @property
    def browser(self) -> Browser | None:
        return self._browser

    @property
    def playwright(self) -> Playwright | None:
        return self._playwright

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def active_session_count(self) -> int:
        return len(self._sessions)

    @property
    def extension_bridge(self) -> ExtensionBridge | None:
        """Extension Bridge (WebSocket server for Chrome Extension)."""
        return self._extension_bridge

    # -- IdleManager (dual-condition auto-disconnect) --

    def _touch_activity(self) -> None:
        """Update last activity timestamp."""
        self._last_activity = time.time()

    def _start_idle_monitor(self) -> None:
        """Start / restart idle monitoring."""
        self._stop_idle_monitor()
        timeout = self._config.daemon_idle_timeout
        if timeout <= 0:
            return  # Disable idle timeout
        self._idle_task = asyncio.create_task(self._idle_monitor_loop(timeout))

    def _stop_idle_monitor(self) -> None:
        if self._idle_task:
            self._idle_task.cancel()
            self._idle_task = None

    async def _idle_monitor_loop(self, timeout: int) -> None:
        """Periodically check whether we should disconnect."""
        try:
            while True:
                await asyncio.sleep(60)  # Check every minute
                elapsed = time.time() - self._last_activity
                # Dual condition: no active sessions AND timeout exceeded
                if not self._sessions and elapsed >= timeout:
                    logger.info(f"Daemon idle timeout ({timeout}s), disconnecting")
                    await self.disconnect()
                    return
        except asyncio.CancelledError:
            pass

    # -- State persistence --

    def _persist_state(self) -> None:
        """Save state to JSON file."""
        state = {
            "cdp_url": self._config.cdp_url,
            "connected": self._connected,
            "sessions": {sid: {"created_at": info.get("created_at", 0)} for sid, info in self._sessions.items()},
            "last_activity": self._last_activity,
        }
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(json.dumps(state, indent=2))
        except Exception as e:
            logger.debug(f"Failed to persist daemon state: {e}")

    def _load_state(self) -> dict:
        """Restore state from JSON file."""
        try:
            if self._state_path.exists():
                return json.loads(self._state_path.read_text())
        except Exception:
            pass
        return {}
