"""
API HTTP 客户端工具

封装 httpx.AsyncClient 用于测试 API Server。
"""
import httpx
from typing import Dict, Optional


class APIClient:
    """API HTTP 客户端"""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url

    async def create_session(self, user_id: str = "test_user", browser_mode: str = "local") -> Dict:
        """创建会话"""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}/sessions/create",
                json={"user_id": user_id, "browser_mode": browser_mode},
                timeout=30,
            )
            return resp.json()

    async def get_session(self, session_id: str) -> Dict:
        """获取会话信息"""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base_url}/sessions/{session_id}",
                timeout=10,
            )
            return resp.json()

    async def delete_session(self, session_id: str) -> Dict:
        """删除会话"""
        async with httpx.AsyncClient() as client:
            resp = await client.delete(
                f"{self.base_url}/sessions/{session_id}",
                timeout=10,
            )
            return resp.json()

    async def submit_task(
        self,
        session_id: str,
        task: str,
        max_steps: int = 10,
    ) -> Dict:
        """提交任务"""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}/sessions/{session_id}/task",
                json={"task": task, "max_steps": max_steps},
                timeout=60,
            )
            return resp.json()

    async def get_task_status(self, session_id: str, task_id: str) -> Dict:
        """获取任务状态"""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base_url}/sessions/{session_id}/tasks/{task_id}",
                timeout=10,
            )
            return resp.json()
