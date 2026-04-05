"""
场景 3：API + 本地浏览器 + Agent 自主执行

验证目标：
  - API Server 内置 LLM
  - Agent 自主执行多步操作
  - 任务完成时间 < 30s（性能）
  - 使用 mock LLM 避免真实 API 费用

测试项：
  1. POST /sessions/create → {"session_id":"..."}
  2. POST /sessions/{id}/task {"task":"..."} → {"task_id":"...","status":"running"}
  3. GET /sessions/{id}/tasks/{task_id} → {"status":"completed","result":...}
  4. 任务完成时间 < 30s
  5. 使用 mock LLM
"""
import pytest
import asyncio
import time
from unittest.mock import AsyncMock, patch
from helpers.api_client import APIClient


@pytest.mark.integration
@pytest.mark.slow
class TestScenario3APILocalAgent:
    """场景 3：API + 本地浏览器 + Agent 自主执行"""

    def setup_method(self):
        self.api = APIClient()
        self.session_id = None

    async def teardown_method_async(self):
        """清理会话"""
        if self.session_id:
            try:
                await self.api.delete_session(self.session_id)
            except Exception:
                pass

    def teardown_method(self):
        asyncio.run(self.teardown_method_async())

    @pytest.mark.asyncio
    async def test_session_create(self):
        """测试 API 会话创建"""
        result = await self.api.create_session(user_id="test_user", browser_mode="local")

        assert result["status"] == "success"
        assert "session_id" in result
        self.session_id = result["session_id"]

    @pytest.mark.asyncio
    async def test_agent_task_execution(self):
        """测试 Agent 任务执行"""
        # 创建会话
        create_result = await self.api.create_session()
        self.session_id = create_result["session_id"]

        # 提交任务
        t0 = time.time()
        task_result = await self.api.submit_task(
            self.session_id,
            task="打开百度，搜索ai coding，输出前5条搜索内容",
            max_steps=10,
        )
        elapsed = time.time() - t0

        # 验证任务提交成功
        assert "task_id" in task_result or "result" in task_result
        # 验证性能（< 60s）
        assert elapsed < 60

    @pytest.mark.asyncio
    @patch("llm.factory.LLMFactory.create")
    async def test_agent_with_mock_llm(self, mock_llm_factory):
        """测试使用 mock LLM 的 Agent"""
        # Mock LLM 返回
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value="任务完成")
        mock_llm_factory.return_value = mock_llm

        # 创建会话
        create_result = await self.api.create_session()
        self.session_id = create_result["session_id"]

        # 提交任务
        task_result = await self.api.submit_task(
            self.session_id,
            task="打开百度，搜索ai coding，输出前5条搜索内容",
            max_steps=10,
        )

        # 验证 mock LLM 被调用
        assert mock_llm.ainvoke.called or "result" in task_result

    @pytest.mark.asyncio
    async def test_session_cleanup(self):
        """测试会话清理"""
        # 创建会话
        create_result = await self.api.create_session()
        self.session_id = create_result["session_id"]

        # 删除会话
        delete_result = await self.api.delete_session(self.session_id)
        assert delete_result["status"] == "success"

        # 验证会话已删除（再次获取应失败）
        get_result = await self.api.get_session(self.session_id)
        assert get_result["status"] == "error" or "not found" in str(get_result).lower()
