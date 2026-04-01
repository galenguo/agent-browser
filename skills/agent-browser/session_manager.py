"""会话管理器"""
import uuid
from typing import Dict, Optional
from .controller import BrowserController, BrowserSession


class SessionManager:
    """会话管理器"""

    def __init__(self):
        self.controller = BrowserController()

    async def create_session(self, cdp_url: str = "http://127.0.0.1:19222") -> str:
        """创建会话"""
        session_id = str(uuid.uuid4())
        await self.controller.create_session(session_id, cdp_url)
        return session_id

    async def delete_session(self, session_id: str):
        """删除会话"""
        await self.controller.delete_session(session_id)

    def get_session(self, session_id: str) -> Optional[BrowserSession]:
        """获取会话"""
        return self.controller.sessions.get(session_id)

    def list_sessions(self) -> Dict[str, BrowserSession]:
        """列出所有会话"""
        return self.controller.sessions
