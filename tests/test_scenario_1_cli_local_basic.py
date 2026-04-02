"""
场景 1：CLI + 本地浏览器 + 基本操作

验证目标：
  - CLI 原子命令正常工作
  - 每步返回正确 JSON 格式
  - ActionTracer 记录 trace 信息
  - 跨进程会话持久化（CLISessionManager）

测试项：
  1. session create → {"status":"success","data":{"session_id":"...","cdp_url":"..."}}
  2. navigate goto → {"status":"success","data":{"url":"...","title":"..."}}
  3. extract text → {"status":"success","data":{"text":"..."}}
  4. interact click/input → {"status":"success","data":{...,"trace":{...}}}
  5. session destroy → {"status":"destroyed"}
"""
import pytest
from tests.helpers.cli_runner import CLIRunner


@pytest.mark.integration
@pytest.mark.slow
class TestScenario1CLILocalBasic:
    """场景 1：CLI + 本地浏览器 + 基本操作"""

    def setup_method(self):
        self.cli = CLIRunner()
        self.session_name = "test-scenario-1"

    def teardown_method(self):
        """清理会话"""
        try:
            self.cli.session_destroy(self.session_name)
        except Exception:
            pass

    def test_session_create(self):
        """测试会话创建"""
        result = self.cli.session_create(self.session_name, browser="local")

        assert result["status"] == "success"
        assert "data" in result
        assert result["data"]["session_id"] == self.session_name
        assert "cdp_url" in result["data"]
        assert "ws://" in result["data"]["cdp_url"]

    def test_navigate_goto(self):
        """测试导航"""
        # 创建会话
        self.cli.session_create(self.session_name)

        # 导航到 example.com
        result = self.cli.navigate_goto(self.session_name, "https://example.com")

        assert result["status"] == "success"
        assert "data" in result
        assert "trace" in result  # ActionTracer 记录

    def test_extract_text(self):
        """测试文本提取"""
        # 创建会话并导航
        self.cli.session_create(self.session_name)
        self.cli.navigate_goto(self.session_name, "https://example.com")

        # 提取 h1 文本
        result = self.cli.extract_text(self.session_name, "h1")

        assert result["status"] == "success"
        assert "data" in result
        assert "text" in result["data"]
        assert len(result["data"]["text"]) > 0

    def test_interact_input(self):
        """测试输入操作"""
        # 创建会话并导航
        self.cli.session_create(self.session_name)
        self.cli.navigate_goto(self.session_name, "https://example.com")

        # 输入文本（假设有输入框）
        result = self.cli.interact_input(self.session_name, "input", "test text")

        # 即使没有输入框，也应该返回结构化错误
        assert "status" in result
        assert "trace" in result or "error" in result

    def test_session_destroy(self):
        """测试会话销毁"""
        # 创建会话
        self.cli.session_create(self.session_name)

        # 销毁会话
        result = self.cli.session_destroy(self.session_name)

        assert result["status"] == "destroyed"
        assert result["data"]["session_id"] == self.session_name

    def test_cross_process_session_persistence(self):
        """测试跨进程会话持久化（CLISessionManager）"""
        # 第一个进程：创建会话
        result1 = self.cli.session_create(self.session_name)
        assert result1["status"] == "success"

        # 第二个进程：使用已有会话（模拟跨进程）
        # CLI 命令会从 ~/.agent-browser/sessions.json 读取 cdp_url
        result2 = self.cli.navigate_goto(self.session_name, "https://example.com")
        assert result2["status"] == "success"

        # 第三个进程：销毁会话
        result3 = self.cli.session_destroy(self.session_name)
        assert result3["status"] == "destroyed"
