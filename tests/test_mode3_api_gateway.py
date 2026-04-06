"""模式3测试：API网关"""
import asyncio

import httpx
import pytest
from websockets import connect


@pytest.mark.asyncio
async def test_websocket_realtime_push():
    """WebSocket实时推送测试"""
    session_id = "test_session_123"

    async with connect(f"ws://localhost:8000/ws/sessions/{session_id}") as ws:
        # 提交命令
        async with httpx.AsyncClient() as client:
            await client.post(
                "http://localhost:8000/cli/execute",
                json={
                    "command": "open",
                    "session_id": session_id,
                    "args": {"url": "https://www.zhipin.com"}
                }
            )

        # 接收事件
        event = await asyncio.wait_for(ws.recv(), timeout=5.0)
        assert "command:started" in event or "command:completed" in event


@pytest.mark.asyncio
async def test_cli_command_execution():
    """CLI命令执行测试"""
    async with httpx.AsyncClient() as client:
        # 创建会话
        session_id = "test_session_456"

        # 执行snapshot命令
        response = await client.post(
            "http://localhost:8000/cli/execute",
            json={
                "command": "snapshot",
                "session_id": session_id,
                "args": {"interactive": True}
            }
        )

        assert response.status_code == 200
        result = response.json()
        assert result["status"] == "success"
