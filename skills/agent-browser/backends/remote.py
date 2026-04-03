"""远程 API 后端 — HTTP 传输适配器（薄包装）

RemoteAPIBackend 不实现任何浏览器逻辑。
它是 LocalCDPBackend 的 HTTP 远程代理：
- 将 BrowserPageHandle 方法翻译为 HTTP REST 调用
- 处理认证（API Key）
- 管理 session_id 映射
- FastAPI 服务端内部运行的是同一个 LocalCDPBackend
"""
import asyncio
import logging
from typing import Any, Callable, Dict, Optional

from . import BrowserBackend, BrowserPageHandle
from ..config import SkillConfig

logger = logging.getLogger(__name__)


class RemotePageHandle(BrowserPageHandle):
    """
    HTTP 传输层 PageHandle。
    每个方法翻译为一个 HTTP REST 调用到 FastAPI。
    """

    def __init__(self, backend: "RemoteAPIBackend", session_id: str, remote_id: str):
        self._backend = backend
        self._session_id = session_id
        self._remote_id = remote_id

    async def goto(self, url: str, wait_until: str = "domcontentloaded", timeout: int = 8000) -> None:
        # TODO: FastAPI 需添加 POST /sessions/{id}/navigate
        await self._backend._request(
            "POST", f"/sessions/{self._remote_id}/navigate",
            {"url": url, "wait_until": wait_until, "timeout": timeout},
        )

    async def go_back(self, wait_until: str = "domcontentloaded", timeout: int = 10000) -> None:
        # TODO: FastAPI 需添加 POST /sessions/{id}/back
        await self._backend._request(
            "POST", f"/sessions/{self._remote_id}/back",
            {"wait_until": wait_until, "timeout": timeout},
        )

    async def evaluate(self, expression: str) -> Any:
        # TODO: FastAPI 需添加 POST /sessions/{id}/evaluate
        result = await self._backend._request(
            "POST", f"/sessions/{self._remote_id}/evaluate",
            {"expression": expression},
        )
        return result.get("result")

    async def wait_for_selector(self, selector: str, timeout: int = 10000) -> None:
        # TODO: FastAPI 需添加 POST /sessions/{id}/wait
        await self._backend._request(
            "POST", f"/sessions/{self._remote_id}/wait",
            {"selector": selector, "timeout": timeout},
        )

    async def mouse_wheel(self, delta_x: int, delta_y: int) -> None:
        # TODO: FastAPI 需添加 POST /sessions/{id}/scroll
        await self._backend._request(
            "POST", f"/sessions/{self._remote_id}/scroll",
            {"delta_x": delta_x, "delta_y": delta_y},
        )

    async def mouse_move(self, x: float, y: float) -> None:
        # TODO: FastAPI 需添加 POST /sessions/{id}/mouse/move
        await self._backend._request(
            "POST", f"/sessions/{self._remote_id}/mouse/move",
            {"x": x, "y": y},
        )

    async def keyboard_press(self, key: str) -> None:
        # TODO: FastAPI 需添加 POST /sessions/{id}/keyboard/press
        await self._backend._request(
            "POST", f"/sessions/{self._remote_id}/keyboard/press",
            {"key": key},
        )

    async def title(self) -> str:
        # TODO: FastAPI 需添加 GET /sessions/{id}/title
        result = await self._backend._request("GET", f"/sessions/{self._remote_id}/title")
        return result.get("title", "")

    async def url(self) -> str:
        # TODO: FastAPI 需添加 GET /sessions/{id}/url
        result = await self._backend._request("GET", f"/sessions/{self._remote_id}/url")
        return result.get("url", "")

    async def on(self, event: str, handler: Callable) -> None:
        raise NotImplementedError(
            "Event listeners not supported in remote mode. Use local mode for explore/cascade."
        )

    def remove_listener(self, event: str, handler: Callable) -> None:
        pass  # No-op for remote

    async def close(self) -> None:
        pass  # Session lifecycle managed by backend


class RemoteAPIBackend(BrowserBackend):
    """
    远程 API 后端 — LocalCDPBackend 的 HTTP 传输层。

    不实现任何浏览器逻辑。只做：
    1. HTTP 序列化/反序列化
    2. 认证（X-API-Key header）
    3. 本地 session_id ↔ 远程 session_id 映射
    """

    def __init__(self, config: SkillConfig):
        self._config = config
        self._api_url = config.api_url.rstrip("/")
        self._api_key = config.api_key
        self._http_session = None  # aiohttp.ClientSession
        self._sessions: Dict[str, RemotePageHandle] = {}
        self._id_map: Dict[str, str] = {}  # local_id -> remote_id
        self._reverse_id_map: Dict[str, str] = {}  # remote_id -> local_id

    async def _ensure_http(self):
        """确保 aiohttp session 已创建"""
        if self._http_session is None:
            import aiohttp
            self._http_session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
            )

    async def _request(self, method: str, path: str, json_data: dict = None) -> dict:
        """发送 HTTP 请求"""
        await self._ensure_http()
        headers = {}
        if self._api_key:
            headers["X-API-Key"] = self._api_key

        url = f"{self._api_url}{path}"
        try:
            async with self._http_session.request(
                method, url, json=json_data, headers=headers,
            ) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    raise Exception(f"API error {resp.status}: {text}")
                if resp.content_length == 0:
                    return {}
                return await resp.json()
        except Exception as e:
            if "ConnectError" in str(type(e).__name__) or "connect" in str(e).lower():
                raise ConnectionError(
                    f"Cannot connect to API at {self._api_url}. "
                    f"Ensure FastAPI server is running: uvicorn src.api:app --port 8000"
                )
            raise

    async def connect(self) -> None:
        """验证 FastAPI 可达"""
        await self._ensure_http()
        try:
            await self._request("GET", "/health")
            logger.info(f"Remote API connected: {self._api_url}")
        except Exception as e:
            raise ConnectionError(f"FastAPI not reachable at {self._api_url}/health: {e}")

    async def disconnect(self) -> None:
        """关闭所有 session + HTTP 连接"""
        for sid in list(self._sessions.keys()):
            try:
                await self.delete_session(sid)
            except Exception:
                pass
        if self._http_session:
            await self._http_session.close()
            self._http_session = None

    async def is_connected(self) -> bool:
        try:
            await self._request("GET", "/health")
            return True
        except Exception:
            return False

    async def create_session(self, session_id: str) -> RemotePageHandle:
        """在远程 FastAPI 创建 session"""
        result = await self._request(
            "POST", "/sessions/create",
            {"user_id": session_id, "browser_mode": self._config.browser_mode},
        )
        remote_id = result.get("session_id", result.get("id", session_id))

        self._id_map[session_id] = remote_id
        self._reverse_id_map[remote_id] = session_id

        handle = RemotePageHandle(self, session_id, remote_id)
        self._sessions[session_id] = handle
        logger.info(f"Remote session created: local={session_id}, remote={remote_id}")
        return handle

    async def delete_session(self, session_id: str) -> None:
        """删除远程 session"""
        remote_id = self._id_map.pop(session_id, None)
        if remote_id:
            try:
                await self._request("DELETE", f"/sessions/{remote_id}")
            except Exception as e:
                logger.debug(f"Failed to delete remote session {remote_id}: {e}")
            self._reverse_id_map.pop(remote_id, None)
        self._sessions.pop(session_id, None)

    async def get_page(self, session_id: str) -> RemotePageHandle:
        """获取远程 page handle"""
        if session_id not in self._sessions:
            raise ValueError(f"Session {session_id} not found")
        return self._sessions[session_id]

    # ── Agent 模式：任务提交 + 轮询 ──

    async def run_task(
        self,
        session_id: str,
        task: str,
        max_steps: int = 6,
        poll_interval: float = 5.0,
        poll_timeout: float = 120.0,
        **kwargs,
    ) -> Dict:
        """提交 Agent 任务到远程 FastAPI 并轮询结果"""
        remote_id = self._id_map.get(session_id)
        if not remote_id:
            raise ValueError(f"Session {session_id} not found")

        # 提交任务
        result = await self._request(
            "POST", f"/sessions/{remote_id}/task",
            {"task": task, "max_steps": max_steps, **kwargs},
        )
        task_id = result.get("task_id")
        if not task_id:
            return {"status": "failed", "error": "No task_id returned"}

        # 轮询结果
        import time
        start = time.time()
        while time.time() - start < poll_timeout:
            await asyncio.sleep(poll_interval)
            status = await self._request(
                "GET", f"/sessions/{remote_id}/tasks/{task_id}",
            )
            state = status.get("status", "running")
            if state in ("completed", "failed"):
                return status

        return {
            "status": "timeout",
            "task_id": task_id,
            "message": f"Task not completed within {poll_timeout}s",
        }

    # ── 快照（需要 FastAPI 端点）──

    async def snapshot(self, session_id: str, interactive_only: bool = False) -> Dict:
        """远程获取快照"""
        remote_id = self._id_map.get(session_id)
        if not remote_id:
            raise ValueError(f"Session {session_id} not found")
        # TODO: FastAPI 需添加 GET /sessions/{id}/snapshot
        return await self._request(
            "POST", f"/sessions/{remote_id}/snapshot",
            {"interactive_only": interactive_only},
        )
