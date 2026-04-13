"""Remote API backend -- HTTP transport adapter (thin wrapper).

RemoteAPIBackend implements no browser logic whatsoever.
It is an HTTP remote proxy for LocalCDPBackend:
- Translates BrowserPageHandle methods into HTTP REST calls
- Handles authentication (API Key)
- Manages session_id mapping
- The FastAPI server internally runs the same LocalCDPBackend
"""

import asyncio
import atexit
import contextlib
import logging
from collections.abc import Callable
from typing import Any

from agent_browser.config import SkillConfig

from . import BrowserBackend, BrowserPageHandle

logger = logging.getLogger(__name__)


class RemotePageHandle(BrowserPageHandle):
    """HTTP transport layer PageHandle.

    Each method is translated into one HTTP REST call to FastAPI.
    """

    def __init__(self, backend: "RemoteAPIBackend", session_id: str, remote_id: str):
        self._backend = backend
        self._session_id = session_id
        self._remote_id = remote_id

    async def goto(self, url: str, wait_until: str = "domcontentloaded", timeout: int = 8000) -> None:
        await self._backend._request(
            "POST",
            f"/sessions/{self._remote_id}/navigate",
            {"url": url, "wait_until": wait_until, "timeout": timeout},
        )

    async def go_back(self, wait_until: str = "domcontentloaded", timeout: int = 10000) -> None:
        await self._backend._request(
            "POST",
            f"/sessions/{self._remote_id}/back",
            {"wait_until": wait_until, "timeout": timeout},
        )

    async def evaluate(self, expression: str) -> Any:
        result = await self._backend._request(
            "POST",
            f"/sessions/{self._remote_id}/evaluate",
            {"expression": expression},
        )
        return result.get("result")

    async def wait_for_selector(self, selector: str, timeout: int = 10000) -> None:
        await self._backend._request(
            "POST",
            f"/sessions/{self._remote_id}/wait",
            {"selector": selector, "timeout": timeout},
        )

    async def mouse_wheel(self, delta_x: int, delta_y: int) -> None:
        direction = "down" if delta_y >= 0 else "up"
        amount = abs(delta_y) if delta_y != 0 else abs(delta_x)
        await self._backend._request(
            "POST",
            f"/sessions/{self._remote_id}/scroll",
            {"direction": direction, "amount": amount},
        )

    async def mouse_move(self, x: float, y: float) -> None:
        await self._backend._request(
            "POST",
            f"/sessions/{self._remote_id}/mouse/move",
            {"x": x, "y": y},
        )

    async def click(self, ref: str = None, x: float = None, y: float = None,
                    button: str = "left", click_count: int = 1,
                    delay: int | None = None) -> None:
        """Click element by ref or by viewport coordinates."""
        body: dict = {}
        if ref:
            body["ref"] = ref
        if x is not None and y is not None:
            body["x"] = x
            body["y"] = y
        if button != "left":
            body["button"] = button
        if click_count != 1:
            body["click_count"] = click_count
        if delay is not None:
            body["delay"] = delay
        await self._backend._request(
            "POST",
            f"/sessions/{self._remote_id}/click",
            body,
        )

    async def keyboard_press(self, key: str) -> None:
        await self._backend._request(
            "POST",
            f"/sessions/{self._remote_id}/keyboard/press",
            {"key": key},
        )

    async def title(self) -> str:
        result = await self._backend._request("GET", f"/sessions/{self._remote_id}/title")
        return result.get("title", "")

    async def url(self) -> str:
        result = await self._backend._request("GET", f"/sessions/{self._remote_id}/url")
        return result.get("url", "")

    async def on(self, event: str, handler: Callable) -> None:
        raise NotImplementedError("Event listeners not supported in remote mode. Use local mode for explore/cascade.")

    def remove_listener(self, event: str, handler: Callable) -> None:
        pass  # No-op for remote

    async def close(self) -> None:
        pass  # Session lifecycle managed by backend


class RemoteAPIBackend(BrowserBackend):
    """Remote API backend -- HTTP transport layer for LocalCDPBackend.

    Implements no browser logic. Only handles:
    1. HTTP serialization / deserialization
    2. Authentication (X-API-Key header)
    3. Local session_id <-> remote session_id mapping
    """

    def __init__(self, config: SkillConfig):
        self._config = config
        self._api_url = config.api_url.rstrip("/")
        self._api_key = config.api_key
        self._http_session = None  # aiohttp.ClientSession
        self._sessions: dict[str, RemotePageHandle] = {}
        self._id_map: dict[str, str] = {}  # local_id -> remote_id
        self._reverse_id_map: dict[str, str] = {}  # remote_id -> local_id
        atexit.register(self._sync_cleanup)

    def _sync_cleanup(self):
        """atexit handler: best-effort close aiohttp session to prevent resource leaks."""
        if self._http_session and not self._http_session.closed:
            try:
                loop = asyncio.get_event_loop()
                if not loop.is_closed() and loop.is_running():
                    loop.create_task(self._http_session.close())
            except RuntimeError:
                pass

    async def _ensure_http(self):
        """Ensure aiohttp session has been created."""
        if self._http_session is None:
            import aiohttp

            self._http_session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=120),
            )

    async def _request(self, method: str, path: str, json_data: dict | None = None) -> dict:
        """Send an HTTP request."""
        await self._ensure_http()
        headers = {}
        if self._api_key:
            headers["X-API-Key"] = self._api_key

        url = f"{self._api_url}{path}"
        try:
            async with self._http_session.request(
                method,
                url,
                json=json_data,
                headers=headers,
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
                    f"Ensure FastAPI server is running: uvicorn agent_browser.api:app --port 8000"
                ) from e
            raise

    async def connect(self) -> None:
        """Verify FastAPI is reachable."""
        await self._ensure_http()
        try:
            await self._request("GET", "/health")
            logger.info(f"Remote API connected: {self._api_url}")
        except Exception as e:
            raise ConnectionError(f"FastAPI not reachable at {self._api_url}/health: {e}") from e

    async def disconnect(self) -> None:
        """Close all sessions + HTTP connection."""
        for sid in list(self._sessions.keys()):
            with contextlib.suppress(Exception):
                await self.delete_session(sid)
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
        """Create a session on the remote FastAPI server."""
        result = await self._request(
            "POST",
            "/sessions/create",
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
        """Delete a remote session."""
        remote_id = self._id_map.pop(session_id, None)
        if remote_id:
            try:
                await self._request("DELETE", f"/sessions/{remote_id}")
            except Exception as e:
                logger.debug(f"Failed to delete remote session {remote_id}: {e}")
            self._reverse_id_map.pop(remote_id, None)
        self._sessions.pop(session_id, None)

    async def get_page(self, session_id: str) -> RemotePageHandle:
        """Get the remote page handle for a session.

        If the session was created externally (e.g., via curl or another client),
        queries the remote server to verify it exists and auto-registers it locally.
        """
        if session_id in self._sessions:
            return self._sessions[session_id]

        # External session: query remote server to verify existence, then auto-register
        try:
            result = await self._request("GET", f"/sessions/{session_id}")
            remote_id = result.get("session_id", session_id)
            handle = RemotePageHandle(self, session_id, remote_id)
            self._sessions[session_id] = handle
            self._id_map[session_id] = remote_id
            self._reverse_id_map[remote_id] = session_id
            logger.info(f"Auto-registered external session: local={session_id}, remote={remote_id}")
            return handle
        except Exception as e:
            raise ValueError(f"Session {session_id} not found locally or remotely: {e}") from e

    # -- Agent mode: task submission + polling --

    async def run_task(
        self,
        session_id: str,
        task: str,
        intelligence: str = "agent",
        llm_config: dict | None = None,
        max_steps: int = 6,
        poll_interval: float = 5.0,
        poll_timeout: float = 120.0,
        **kwargs,
    ) -> dict:
        """Submit Agent task to remote FastAPI and poll for results."""
        remote_id = self._id_map.get(session_id)
        if not remote_id:
            raise ValueError(f"Session {session_id} not found")

        # Submit task
        result = await self._request(
            "POST",
            f"/sessions/{remote_id}/task",
            {"task": task, "max_steps": max_steps, **kwargs},
        )
        task_id = result.get("task_id")
        if not task_id:
            return {"status": "failed", "error": "No task_id returned"}

        # Poll for result
        import time

        start = time.time()
        while time.time() - start < poll_timeout:
            await asyncio.sleep(poll_interval)
            status = await self._request(
                "GET",
                f"/sessions/{remote_id}/tasks/{task_id}",
            )
            state = status.get("status", "running")
            if state in ("completed", "failed"):
                return status

        return {
            "status": "timeout",
            "task_id": task_id,
            "message": f"Task not completed within {poll_timeout}s",
        }

    # -- Snapshot (requires FastAPI endpoint) --

    async def snapshot(self, session_id: str, interactive_only: bool = False,
                     iframe_selector: str | None = None) -> dict:
        """Get snapshot remotely."""
        remote_id = self._id_map.get(session_id)
        if not remote_id:
            raise ValueError(f"Session {session_id} not found")
        params: dict = {"interactive_only": interactive_only}
        if iframe_selector:
            params["iframe_selector"] = iframe_selector
        return await self._request(
            "POST",
            f"/sessions/{remote_id}/snapshot",
            params,
        )
