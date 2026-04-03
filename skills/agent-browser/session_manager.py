"""会话管理器 — 基于 BrowserBackend"""
import uuid
from typing import Optional

from .config import SkillConfig, load_config
from .backends import BrowserBackend
from .backends.local import LocalCDPBackend, PlaywrightPageHandle


class SessionManager:
    """
    会话管理器（兼容层）。
    内部使用 BrowserBackend，对外保持与原有 API 一致。
    """

    def __init__(self, config: SkillConfig = None):
        self._config = config or load_config()
        self._backend: Optional[BrowserBackend] = None

    async def _ensure_backend(self) -> BrowserBackend:
        if self._backend is None:
            self._backend = LocalCDPBackend(self._config)
        return self._backend

    async def create_session(self, cdp_url: str = "http://127.0.0.1:19222") -> str:
        """创建会话"""
        if cdp_url != self._config.cdp_url:
            self._config.cdp_url = cdp_url
        backend = await self._ensure_backend()
        session_id = uuid.uuid4().hex
        await backend.create_session(session_id)
        return session_id

    async def delete_session(self, session_id: str):
        """删除会话"""
        backend = await self._ensure_backend()
        await backend.delete_session(session_id)

    def get_session(self, session_id: str):
        """获取会话（返回 LocalSession 或 None）"""
        if isinstance(self._backend, LocalCDPBackend):
            return self._backend._sessions.get(session_id)
        return None

    @property
    def controller(self):
        """向后兼容：返回 backend（BrowserController 语义）"""
        return self._backend
