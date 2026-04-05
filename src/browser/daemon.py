"""微 Daemon — 进程内持久化浏览器连接 singleton

参考 opencli 的 daemon + IdleManager 双条件模式：
- opencli 用独立 HTTP 进程（因为 CLI 每次是新的 subprocess）
- 我们用进程内 singleton（因为 skill 运行在 Claude REPL 长生命周期中）
- 共享：IdleManager 双条件退出、状态持久化、自动重连
- 新增: WebSocket 服务器用于 Chrome Extension 连接
"""
import sys
from pathlib import Path

import asyncio
import json
import time
import logging

_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
from typing import Any, Dict, Optional, Tuple

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from .config import SkillConfig

logger = logging.getLogger(__name__)

# ── Extension Bridge Types ──

class ExtensionCommand:
    """发送给 Chrome Extension 的命令"""
    def __init__(self, method: str, params: Dict[str, Any] | None = None):
        self.id = f"cmd_{time.time_ns()}"
        self.method = method
        self.params = params or {}
        self._future: asyncio.Future = asyncio.get_event_loop().create_future()

    @property
    def future(self) -> asyncio.Future:
        return self._future


class ExtensionBridge:
    """
    WebSocket 服务器，供 Chrome Extension 连接。

    安全模型（来自 OpenCLI）：
    - 仅接受 localhost 连接
    - 心跳检测 (15s ping/pong)
    - 命令队列 + Future 匹配请求/响应
    """

    def __init__(self, port: int = 19825):
        self._port = port
        self._server: Optional[Any] = None  # websockets.serve
        self._ws: Optional[Any] = None  # WebSocket connection
        self._commands: Dict[str, ExtensionCommand] = {}  # id → Command
        self._connected = False
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._missed_pongs = 0

    @property
    def is_connected(self) -> bool:
        return self._connected and self._ws is not None

    async def start(self) -> None:
        """启动 WebSocket 服务器，等待 Extension 连接"""
        if self._server:
            return

        try:
            import websockets
        except ImportError:
            logger.warning("websockets not installed. Extension bridge disabled. Run: pip install websockets")
            return

        async def _handler(ws, path: str):
            # 仅接受 /ext 路径的连接
            if path != "/ext":
                await ws.close(4004, "Invalid path")
                return

            logger.info(f"Extension connected from {ws.remote_address}")
            self._ws = ws
            self._connected = True
            self._missed_pongs = 0

            try:
                # 启动心跳
                self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(ws))

                # 消息循环
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        msg_type = msg.get("type")

                        if msg_type == "pong":
                            self._missed_pongs = 0
                        elif "id" in msg and "data" in msg:
                            # 响应消息：匹配 pending command
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
                # 取消所有 pending 命令
                for cmd in self._commands.values():
                    if not cmd.future.done():
                        cmd.future.set_exception(ConnectionError("Extension disconnected"))
                self._commands.clear()
                logger.info("Extension disconnected")

        self._server = await websockets.serve(_handler, "127.0.0.1", self._port)
        logger.info(f"Extension bridge listening on ws://127.0.0.1:{self._port}/ext")

    async def stop(self) -> None:
        """停止 WebSocket 服务器"""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        self._connected = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def send_command(self, method: str, params: Dict[str, Any] | None = None, timeout: float = 30.0) -> Any:
        """发送命令到 Extension 并等待响应"""
        if not self._connected or not self._ws:
            raise ConnectionError("Extension not connected")

        cmd = ExtensionCommand(method, params)
        self._commands[cmd.id] = cmd

        try:
            payload = {"id": cmd.id, "method": cmd.method, "params": cmd.params}
            await self._ws.send(json.dumps(payload))
            return await asyncio.wait_for(cmd.future, timeout=timeout)
        except asyncio.TimeoutError:
            self._commands.pop(cmd.id, None)
            raise TimeoutError(f"Extension command '{method}' timed out after {timeout}s")
        except Exception:
            self._commands.pop(cmd.id, None)
            raise

    async def _heartbeat_loop(self, ws) -> None:
        """心跳循环：每 15s 发送 ping"""
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
    """
    进程内持久化浏览器连接 singleton。

    生命周期：
    1. 首次浏览器命令时懒连接（ensure_connected）
    2. 保持 Playwright + CDP 连接跨 session create/delete
    3. 双条件空闲断开：无活跃 session 且超过 idle_timeout
    4. 下次命令自动重连
    5. 状态持久化到 ~/.agent-browser/daemon-state.json
    """

    _instance: Optional["BrowserDaemon"] = None

    def __init__(self, config: SkillConfig):
        self._config = config
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._connected = False
        self._sessions: Dict[str, Dict[str, Any]] = {}  # session_id -> {context, page, created_at}
        self._last_activity = time.time()
        self._idle_task: Optional[asyncio.Task] = None
        self._state_path = Path(config.daemon_state_path).expanduser()
        # Extension Bridge (WebSocket server for Chrome Extension)
        self._extension_bridge: Optional[ExtensionBridge] = None

    @classmethod
    def get(cls, config: SkillConfig = None) -> "BrowserDaemon":
        """Singleton accessor"""
        if cls._instance is None:
            cls._instance = cls(config or SkillConfig())
        return cls._instance

    @classmethod
    def reset(cls):
        """重置 singleton（仅用于测试）"""
        cls._instance = None

    # ── 连接管理 ──

    async def ensure_connected(self) -> None:
        """确保浏览器已连接（懒连接 + 自动重连）"""
        # 启动 Extension Bridge（如果尚未启动）
        if not self._extension_bridge:
            self._extension_bridge = ExtensionBridge(port=19825)
            await self._extension_bridge.start()

        if self._connected and self._browser:
            try:
                _ = self._browser.contexts  # 存活性检查
                self._touch_activity()
                return
            except Exception:
                logger.info("Browser disconnected, reconnecting...")
                self._connected = False

        # 尝试恢复状态
        state = self._load_state()
        cdp_url = state.get("cdp_url", self._config.cdp_url)

        if not self._playwright:
            self._playwright = await async_playwright().start()

        # 连接 CDP（带重试）
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
                    raise ConnectionError(f"Failed to connect to CDP at {cdp_url}: {e}")

    async def disconnect(self) -> None:
        """断开浏览器连接"""
        self._stop_idle_monitor()

        # 停止 Extension Bridge
        if self._extension_bridge:
            await self._extension_bridge.stop()
            self._extension_bridge = None

        # 关闭所有 session
        for sid in list(self._sessions.keys()):
            await self.destroy_context(sid)

        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None

        self._connected = False
        self._persist_state()
        logger.info("Daemon disconnected")

    async def shutdown(self) -> None:
        """完全关闭（包括 Playwright）"""
        await self.disconnect()
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
        BrowserDaemon._instance = None
        logger.info("Daemon shutdown complete")

    # ── Session 管理 ──

    async def create_context(self, session_id: str) -> Tuple[BrowserContext, Page]:
        """在持久浏览器连接上创建新的 context + page"""
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
        """关闭 context + page，但保持浏览器连接"""
        session = self._sessions.pop(session_id, None)
        if session:
            try:
                await session["page"].close()
            except Exception:
                pass
            try:
                await session["context"].close()
            except Exception:
                pass
        self._touch_activity()
        self._persist_state()

    def get_page(self, session_id: str) -> Optional[Page]:
        """获取 session 的 Playwright Page"""
        session = self._sessions.get(session_id)
        return session["page"] if session else None

    @property
    def browser(self) -> Optional[Browser]:
        return self._browser

    @property
    def playwright(self) -> Optional[Playwright]:
        return self._playwright

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def active_session_count(self) -> int:
        return len(self._sessions)

    @property
    def extension_bridge(self) -> Optional[ExtensionBridge]:
        """Extension Bridge (WebSocket server for Chrome Extension)"""
        return self._extension_bridge

    # ── IdleManager（双条件自动断开）──

    def _touch_activity(self) -> None:
        """更新最后活动时间"""
        self._last_activity = time.time()

    def _start_idle_monitor(self) -> None:
        """启动/重启 idle 监控"""
        self._stop_idle_monitor()
        timeout = self._config.daemon_idle_timeout
        if timeout <= 0:
            return  # 禁用 idle 超时
        self._idle_task = asyncio.create_task(self._idle_monitor_loop(timeout))

    def _stop_idle_monitor(self) -> None:
        if self._idle_task:
            self._idle_task.cancel()
            self._idle_task = None

    async def _idle_monitor_loop(self, timeout: int) -> None:
        """定期检查是否应该断开"""
        try:
            while True:
                await asyncio.sleep(60)  # 每分钟检查一次
                elapsed = time.time() - self._last_activity
                # 双条件：无活跃 session 且超过超时
                if not self._sessions and elapsed >= timeout:
                    logger.info(f"Daemon idle timeout ({timeout}s), disconnecting")
                    await self.disconnect()
                    return
        except asyncio.CancelledError:
            pass

    # ── 状态持久化 ──

    def _persist_state(self) -> None:
        """保存状态到 JSON 文件"""
        state = {
            "cdp_url": self._config.cdp_url,
            "connected": self._connected,
            "sessions": {
                sid: {"created_at": info.get("created_at", 0)}
                for sid, info in self._sessions.items()
            },
            "last_activity": self._last_activity,
        }
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(json.dumps(state, indent=2))
        except Exception as e:
            logger.debug(f"Failed to persist daemon state: {e}")

    def _load_state(self) -> Dict:
        """从 JSON 文件恢复状态"""
        try:
            if self._state_path.exists():
                return json.loads(self._state_path.read_text())
        except Exception:
            pass
        return {}
