"""
场景 4：CLI + 远程浏览器 + Gateway

验证目标：
  - Gateway 分配远程浏览器
  - CLI 通过 CDP 代理连接
  - 无效 API Key 返回错误

测试项：
  1. 设置 BROWSER_GATEWAY_URL/KEY 环境变量
  2. session create --browser remote --use-gateway → cdp_url 包含 "ws://gateway"
  3. navigate goto → 通过 Gateway WebSocket 代理执行成功
  4. session destroy → Gateway 释放资源（验证 /release 调用）
  5. 无效 API Key → 返回错误（401）
"""

import contextlib
import os
from unittest.mock import AsyncMock, patch

import pytest

from tests.helpers.cli_runner import CLIRunner


@pytest.mark.gateway
class TestScenario4CLIRemoteGateway:
    """场景 4：CLI + 远程浏览器 + Gateway"""

    def setup_method(self):
        self.cli = CLIRunner()
        self.session_name = "test-scenario-4"
        # 设置 Gateway 环境变量
        os.environ["BROWSER_GATEWAY_URL"] = "http://mock-gateway:8001"
        os.environ["BROWSER_GATEWAY_KEY"] = "test-api-key"

    def teardown_method(self):
        """清理会话和环境变量"""
        with contextlib.suppress(Exception):
            self.cli.session_destroy(self.session_name)
        os.environ.pop("BROWSER_GATEWAY_URL", None)
        os.environ.pop("BROWSER_GATEWAY_KEY", None)

    @patch("httpx.AsyncClient.post")
    def test_gateway_allocation(self, mock_post):
        """测试 Gateway 分配远程浏览器"""
        # Mock Gateway /allocate 响应
        mock_response = AsyncMock()
        mock_response.json.return_value = {
            "cdp_url": "ws://gateway:8001/cdp?apikey=test&instance=remote-123",
            "instance_id": "remote-123",
        }
        mock_response.raise_for_status = AsyncMock()
        mock_post.return_value = mock_response

        # 创建远程会话
        result = self.cli.run(
            [
                "session",
                "create",
                "--name",
                self.session_name,
                "--use-gateway",
            ]
        )

        assert result["status"] == "success"
        assert "cdp_url" in result["data"]
        assert "gateway" in result["data"]["cdp_url"].lower()

    @patch("httpx.AsyncClient.post")
    def test_gateway_release(self, mock_post):
        """测试 Gateway 释放资源"""
        # Mock Gateway /allocate
        mock_allocate = AsyncMock()
        mock_allocate.json.return_value = {
            "cdp_url": "ws://gateway:8001/cdp?instance=remote-123",
            "instance_id": "remote-123",
        }
        mock_allocate.raise_for_status = AsyncMock()

        # Mock Gateway /release
        mock_release = AsyncMock()
        mock_release.raise_for_status = AsyncMock()

        mock_post.side_effect = [mock_allocate, mock_release]

        # 创建并销毁会话
        self.cli.run(["session", "create", "--name", self.session_name, "--use-gateway"])
        result = self.cli.session_destroy(self.session_name)

        assert result["status"] == "destroyed"
        # 验证 /release 被调用
        assert mock_post.call_count >= 2

    def test_invalid_api_key(self):
        """测试无效 API Key"""
        # 设置无效 API Key
        os.environ["BROWSER_GATEWAY_KEY"] = "invalid-key"

        # 尝试创建会话（应失败）
        result = self.cli.run(
            [
                "session",
                "create",
                "--name",
                self.session_name,
                "--use-gateway",
            ]
        )

        # 应返回错误
        assert result["status"] == "error"
        assert "401" in str(result) or "unauthorized" in str(result).lower()

    def test_gateway_url_not_set(self):
        """测试 Gateway URL 未设置"""
        # 移除 Gateway URL
        os.environ.pop("BROWSER_GATEWAY_URL", None)

        # 尝试创建会话（应失败）
        result = self.cli.run(
            [
                "session",
                "create",
                "--name",
                self.session_name,
                "--use-gateway",
            ]
        )

        assert result["status"] == "error"
        assert "BROWSER_GATEWAY_URL" in result["error"]
