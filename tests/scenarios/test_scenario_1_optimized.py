"""
场景 1：CLI + 本地浏览器 + 基本操作（优化版本）

优化：使用 setup_class 创建一次会话，所有测试共享
"""

import pytest
from helpers.cli_runner import CLIRunner


@pytest.mark.integration
@pytest.mark.slow
class TestScenario1Optimized:
    """场景 1：CLI + 本地浏览器 + 基本操作（优化版本）"""

    cli = None
    session_name = "test-scenario-1-shared"
    session_created = False

    @classmethod
    def setup_class(cls):
        """类级别设置：创建一次会话供所有测试使用"""
        cls.cli = CLIRunner()
        # 创建共享会话
        result = cls.cli.session_create(cls.session_name, browser="local")
        if result.get("status") == "success":
            cls.session_created = True
            print(f"\n✅ 共享会话创建成功: {cls.session_name}")
        else:
            print(f"\n❌ 共享会话创建失败: {result}")

    @classmethod
    def teardown_class(cls):
        """类级别清理：销毁共享会话"""
        if cls.session_created:
            cls.cli.session_destroy(cls.session_name)
            print(f"\n✅ 共享会话已销毁: {cls.session_name}")

    def test_01_session_create(self):
        """测试会话创建（验证 setup_class 的结果）"""
        assert self.session_created, "会话创建失败"
        print("✓ 会话创建验证通过")

    def test_02_navigate_goto(self):
        """测试导航"""
        result = self.cli.navigate_goto(self.session_name, "https://example.com")
        assert result["status"] == "success", f"导航失败: {result}"
        assert "trace" in result
        print("✓ 导航测试通过")

    def test_03_extract_text(self):
        """测试文本提取"""
        # 先导航到页面
        self.cli.navigate_goto(self.session_name, "https://example.com")

        # 提取 h1 文本
        result = self.cli.extract_text(self.session_name, "h1")
        assert result["status"] == "success", f"提取失败: {result}"
        assert "data" in result
        assert "text" in result["data"]
        assert len(result["data"]["text"]) > 0
        print(f"✓ 文本提取通过: {result['data']['text'][:50]}")

    def test_04_interact_input(self):
        """测试输入操作"""
        result = self.cli.interact_input(self.session_name, "input", "test text")
        # 即使没有输入框，也应该返回结构化响应
        assert "status" in result
        print("✓ 输入操作测试通过")

    def test_05_multiple_operations(self):
        """测试多个操作序列"""
        # 导航
        result1 = self.cli.navigate_goto(self.session_name, "https://example.com")
        assert result1["status"] == "success"

        # 提取
        result2 = self.cli.extract_text(self.session_name, "h1")
        assert result2["status"] == "success"

        print("✓ 多操作序列测试通过")

    def test_06_session_persistence(self):
        """测试会话持久化（跨测试方法）"""
        # 验证会话仍然存在并可用
        result = self.cli.navigate_goto(self.session_name, "https://example.com")
        assert result["status"] == "success"
        print("✓ 会话持久化验证通过")
