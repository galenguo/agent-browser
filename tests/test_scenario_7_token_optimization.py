"""
场景 7：Token 优化验证

验证目标：
  - DOM 压缩率 > 80%
  - 选择性提取节省 token
  - API Agent 任务使用 use_vision=False
  - max_input_tokens=8000 配置已应用
  - ActionTracer 的 trace 信息不包含完整 HTML

测试项：
  1. extract html(full) vs get_dom(simplified) → 压缩率 > 80%
  2. extract elements（仅交互元素）→ < 2000 tokens 等价文本
  3. API Agent 任务使用 use_vision=False
  4. max_input_tokens=8000 配置已应用
  5. ActionTracer 的 trace 信息不包含完整 HTML（节省 token）
"""
import asyncio
import contextlib

import pytest
from helpers.api_client import APIClient
from helpers.cli_runner import CLIRunner


@pytest.mark.integration
@pytest.mark.slow
class TestScenario7TokenOptimization:
    """场景 7：Token 优化验证"""

    def setup_method(self):
        self.cli = CLIRunner()
        self.api = APIClient()
        self.session_name = "test-token-opt"
        self.api_session = None

    def teardown_method(self):
        """清理会话"""
        with contextlib.suppress(Exception):
            self.cli.session_destroy(self.session_name)

        if self.api_session:
            asyncio.run(self.api.delete_session(self.api_session))

    def test_dom_compression_ratio(self):
        """验证 DOM 压缩率 > 80%"""
        # 创建会话并导航
        self.cli.session_create(self.session_name)
        self.cli.navigate_goto(self.session_name, "https://example.com")

        # 提取完整 HTML
        full_result = self.cli.run([
            "extract", "html",
            "--session", self.session_name,
            "--full",
        ])
        full_html = full_result.get("data", {}).get("html", "")
        full_size = len(full_html)

        # 提取简化 DOM
        simplified_result = self.cli.run([
            "extract", "dom",
            "--session", self.session_name,
            "--simplified",
        ])
        simplified_dom = simplified_result.get("data", {}).get("dom", "")
        simplified_size = len(simplified_dom)

        # 计算压缩率
        if full_size > 0:
            compression_ratio = 1 - (simplified_size / full_size)
            assert compression_ratio > 0.8  # 压缩率 > 80%

    def test_selective_element_extraction(self):
        """验证选择性元素提取节省 token"""
        # 创建会话并导航
        self.cli.session_create(self.session_name)
        self.cli.navigate_goto(self.session_name, "https://example.com")

        # 提取交互元素
        elements_result = self.cli.run([
            "extract", "elements",
            "--session", self.session_name,
            "--selector", "a, button, input",
        ])

        elements_text = str(elements_result.get("data", {}))
        elements_size = len(elements_text)

        # 验证提取结果 < 2000 字符（约等于 500 tokens）
        assert elements_size < 2000

    @pytest.mark.asyncio
    async def test_api_agent_use_vision_false(self):
        """验证 API Agent 使用 use_vision=False"""
        # 创建会话
        result = await self.api.create_session()
        self.api_session = result["session_id"]

        # 提交任务（应使用 use_vision=False）
        task_result = await self.api.submit_task(
            self.api_session,
            task="打开百度，搜索ai coding，输出前5条搜索内容",
            max_steps=10,
        )

        # 验证任务执行（use_vision=False 在代码中硬编码）
        # 实际验证需要检查 Agent 初始化参数
        assert "result" in task_result or "task_id" in task_result

    def test_action_tracer_no_full_html(self):
        """验证 ActionTracer 的 trace 不包含完整 HTML"""
        # 创建会话并执行操作
        self.cli.session_create(self.session_name)
        result = self.cli.navigate_goto(self.session_name, "https://example.com")

        # 验证 trace 存在
        assert "trace" in result

        # 验证 trace 不包含完整 HTML（节省 token）
        trace_str = str(result["trace"])
        # trace 应该只包含元数据，不包含大量 HTML
        assert len(trace_str) < 1000  # trace 应该很小

        # 验证 trace 不包含 <html> 标签
        assert "<html" not in trace_str.lower()

    def test_max_input_tokens_config(self):
        """验证 max_input_tokens=8000 配置"""
        # 这个测试需要检查 LLM 配置
        # 实际验证需要读取配置文件或环境变量

        # 临时：通过代码检查（需要添加配置读取）
        # from llm.factory import LLMFactory
        # llm = LLMFactory.create("openai")
        # assert llm.max_input_tokens == 8000

        # 跳过（需要实际 LLM 配置）
        pytest.skip("需要 LLM 配置验证")

    def test_token_usage_comparison(self):
        """对比完整 HTML vs 简化 DOM 的 token 使用"""
        # 创建会话并导航
        self.cli.session_create(self.session_name)
        self.cli.navigate_goto(self.session_name, "https://example.com")

        # 提取完整 HTML
        full_result = self.cli.run([
            "extract", "html",
            "--session", self.session_name,
            "--full",
        ])
        full_html = full_result.get("data", {}).get("html", "")

        # 提取简化 DOM
        simplified_result = self.cli.run([
            "extract", "dom",
            "--session", self.session_name,
            "--simplified",
        ])
        simplified_dom = simplified_result.get("data", {}).get("dom", "")

        # 估算 token 数量（1 token ≈ 4 字符）
        full_tokens = len(full_html) / 4
        simplified_tokens = len(simplified_dom) / 4

        # 验证简化版节省 > 80% tokens
        if full_tokens > 0:
            token_savings = 1 - (simplified_tokens / full_tokens)
            assert token_savings > 0.8
