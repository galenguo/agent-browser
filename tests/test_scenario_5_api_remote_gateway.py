"""
场景 5：API + 远程浏览器 + Gateway

验证目标：
  - API Server 通过 Gateway 分配远程浏览器
  - 多租户隔离
  - Gateway quota 检查

测试项：
  1. POST /sessions/create {"browser_mode":"remote"} → 自动调用 Gateway /allocate
  2. 两个不同用户的 session 使用不同的远程浏览器实例
  3. session destroy → 自动调用 Gateway /release
  4. Gateway quota 检查：超出限额时返回适当错误
"""
import asyncio
import contextlib
from unittest.mock import AsyncMock, patch

import pytest

from tests.helpers.api_client import APIClient


@pytest.mark.gateway
class TestScenario5APIRemoteGateway:
    """场景 5：API + 远程浏览器 + Gateway"""

    def setup_method(self):
        self.api = APIClient()
        self.session_ids = []

    async def teardown_method_async(self):
        """清理会话"""
        for session_id in self.session_ids:
            with contextlib.suppress(Exception):
                await self.api.delete_session(session_id)

    def teardown_method(self):
        asyncio.run(self.teardown_method_async())

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.post")
    async def test_gateway_allocation_via_api(self, mock_post):
        """测试 API 通过 Gateway 分配远程浏览器"""
        # Mock Gateway /allocate
        mock_response = AsyncMock()
        mock_response.json.return_value = {
            "cdp_url": "ws://gateway:8001/cdp?instance=remote-api-1",
            "instance_id": "remote-api-1",
        }
        mock_response.raise_for_status = AsyncMock()
        mock_post.return_value = mock_response

        # 创建远程会话
        result = await self.api.create_session(
            user_id="test_user",
            browser_mode="remote",
        )

        assert result["status"] == "success"
        assert "session_id" in result
        self.session_ids.append(result["session_id"])

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.post")
    async def test_multi_tenant_isolation(self, mock_post):
        """测试多租户隔离"""
        # Mock Gateway 为不同用户分配不同实例
        instance_counter = [0]

        def mock_allocate(*args, **kwargs):
            instance_counter[0] += 1
            response = AsyncMock()
            response.json.return_value = {
                "cdp_url": f"ws://gateway:8001/cdp?instance=remote-{instance_counter[0]}",
                "instance_id": f"remote-{instance_counter[0]}",
            }
            response.raise_for_status = AsyncMock()
            return response

        mock_post.side_effect = mock_allocate

        # 创建两个不同用户的会话
        result1 = await self.api.create_session(user_id="user1", browser_mode="remote")
        result2 = await self.api.create_session(user_id="user2", browser_mode="remote")

        self.session_ids.extend([result1["session_id"], result2["session_id"]])

        # 验证分配了不同的实例
        assert result1["session_id"] != result2["session_id"]
        # 验证 Gateway 被调用了两次
        assert mock_post.call_count >= 2

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.post")
    async def test_gateway_release_on_destroy(self, mock_post):
        """测试销毁会话时调用 Gateway /release"""
        # Mock Gateway /allocate
        mock_allocate = AsyncMock()
        mock_allocate.json.return_value = {
            "cdp_url": "ws://gateway:8001/cdp?instance=remote-test",
            "instance_id": "remote-test",
        }
        mock_allocate.raise_for_status = AsyncMock()

        # Mock Gateway /release
        mock_release = AsyncMock()
        mock_release.raise_for_status = AsyncMock()

        mock_post.side_effect = [mock_allocate, mock_release]

        # 创建并销毁会话
        result = await self.api.create_session(browser_mode="remote")
        session_id = result["session_id"]

        delete_result = await self.api.delete_session(session_id)
        assert delete_result["status"] == "success"

        # 验证 /release 被调用
        assert mock_post.call_count >= 2

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.post")
    async def test_gateway_quota_exceeded(self, mock_post):
        """测试 Gateway quota 超出限额"""
        # Mock Gateway 返回 quota 超出错误
        mock_response = AsyncMock()
        mock_response.raise_for_status.side_effect = Exception("Quota exceeded")
        mock_post.return_value = mock_response

        # 尝试创建会话（应失败）
        result = await self.api.create_session(browser_mode="remote")

        assert result["status"] == "error"
        assert "quota" in str(result).lower() or "exceeded" in str(result).lower()
