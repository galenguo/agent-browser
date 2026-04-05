"""
场景 2：CLI + 本地浏览器 + 完整任务流程

验证目标：
  - 模拟完整浏览器自动化流程
  - StealthEnhancer 延迟生效
  - 提取到有效数据
  - 会话自动清理

测试项：
  1. 创建会话 → 导航 → 输入 → 点击 → 提取 → 销毁会话
  2. 每步操作间有随机延迟（验证 StealthEnhancer）
  3. 提取到有效数据（非空）
  4. 会话自动清理（destroy 后验证 session 不存在）
"""
import pytest
import time
from helpers.cli_runner import CLIRunner


@pytest.mark.integration
@pytest.mark.slow
class TestScenario2CLILocalFullTask:
    """场景 2：CLI + 本地浏览器 + 完整任务流程"""

    def setup_method(self):
        self.cli = CLIRunner()
        self.session_name = "test-scenario-2"

    def teardown_method(self):
        """清理会话"""
        try:
            self.cli.session_destroy(self.session_name)
        except Exception:
            pass

    def test_full_task_flow(self):
        """测试完整任务流程"""
        # Step 1: 创建会话
        result = self.cli.session_create(self.session_name)
        assert result["status"] == "success"

        # Step 2: 导航到 example.com
        t0 = time.time()
        result = self.cli.navigate_goto(self.session_name, "https://example.com")
        elapsed = time.time() - t0
        assert result["status"] == "success"
        # 验证有延迟（StealthEnhancer pre_action + post_action）
        assert elapsed > 0.2  # 至少 200ms 延迟

        # Step 3: 提取标题
        result = self.cli.extract_text(self.session_name, "h1")
        assert result["status"] == "success"
        assert len(result["data"]["text"]) > 0

        # Step 4: 销毁会话
        result = self.cli.session_destroy(self.session_name)
        assert result["status"] == "destroyed"

        # Step 5: 验证会话已清理（再次访问应失败）
        result = self.cli.navigate_goto(self.session_name, "https://example.com")
        assert result["status"] == "error"
        assert "not found" in result["error"].lower()

    def test_stealth_delays(self):
        """验证 StealthEnhancer 延迟"""
        self.cli.session_create(self.session_name)

        # 测试多次导航，验证每次都有延迟
        delays = []
        for _ in range(3):
            t0 = time.time()
            self.cli.navigate_goto(self.session_name, "https://example.com")
            delays.append(time.time() - t0)

        # 每次延迟应该 > 200ms（pre_action + post_action）
        assert all(d > 0.2 for d in delays)
        # 延迟应该有随机性（不完全相同）
        assert len(set(int(d * 100) for d in delays)) > 1

    def test_data_extraction(self):
        """验证数据提取有效性"""
        self.cli.session_create(self.session_name)
        self.cli.navigate_goto(self.session_name, "https://example.com")

        # 提取多个元素
        h1_result = self.cli.extract_text(self.session_name, "h1")
        p_result = self.cli.extract_text(self.session_name, "p")

        # 验证提取到非空数据
        assert h1_result["status"] == "success"
        assert len(h1_result["data"]["text"]) > 0

        assert p_result["status"] == "success"
        assert len(p_result["data"]["text"]) > 0
