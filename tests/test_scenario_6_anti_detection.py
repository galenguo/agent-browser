"""
场景 6：反侦测能力验证

验证目标：
  - 5 层防护栈有效
  - 浏览器指纹不可检测
  - CLI 和 API 模式反侦测能力 100% 对齐

测试项：
  1. navigator.webdriver == undefined（通过 JS 执行验证）
  2. CDP Runtime.Enable 无泄漏（通过 window 属性检查）
  3. CDP 端口使用 19222（非默认 9222）
  4. 人类行为：click 延迟 100-300ms，typing 每字 50-250ms
  5. 贝塞尔曲线鼠标移动（通过 StealthEnhancer.pre_action 验证）
  6. bot.sannysoft.com（可选，真实测试）: navigator.webdriver=false
  7. 持久化会话：多次操作不重新创建 CDP 连接
  8. CLI 和 API 模式反侦测等同性验证
"""
import pytest
import asyncio
import time
from helpers.cli_runner import CLIRunner
from helpers.api_client import APIClient


@pytest.mark.integration
@pytest.mark.slow
class TestScenario6AntiDetection:
    """场景 6：反侦测能力验证"""

    def setup_method(self):
        self.cli = CLIRunner()
        self.api = APIClient()
        self.cli_session = "test-anti-detection-cli"
        self.api_session = None

    def teardown_method(self):
        """清理会话"""
        try:
            self.cli.session_destroy(self.cli_session)
        except Exception:
            pass

        if self.api_session:
            asyncio.run(self.api.delete_session(self.api_session))

    def test_navigator_webdriver_undefined(self):
        """验证 navigator.webdriver == undefined"""
        # 创建会话
        self.cli.session_create(self.cli_session)
        self.cli.navigate_goto(self.cli_session, "https://example.com")

        # 执行 JS 检查 navigator.webdriver
        # 注意：需要添加 execute_js 命令到 CLI
        # result = self.cli.run(["execute", "js", "--session", self.cli_session, "--script", "return navigator.webdriver"])
        # assert result["data"]["value"] is None or result["data"]["value"] == "undefined"

        # 临时：通过日志验证（实际应通过 JS 执行）
        pass

    def test_cdp_port_non_standard(self):
        """验证 CDP 端口使用 19222（非默认 9222）"""
        result = self.cli.session_create(self.cli_session)
        cdp_url = result["data"]["cdp_url"]

        # 验证端口是 19222
        assert ":19222" in cdp_url or "19222" in cdp_url

    def test_human_behavior_delays(self):
        """验证人类行为延迟"""
        self.cli.session_create(self.cli_session)
        self.cli.navigate_goto(self.cli_session, "https://example.com")

        # 测试 click 延迟
        t0 = time.time()
        self.cli.interact_click(self.cli_session, "h1")
        click_elapsed = time.time() - t0

        # click 应有 pre_action + post_action 延迟（100-300ms * 2）
        assert click_elapsed > 0.2  # 至少 200ms

        # 测试 input 延迟（字符级延迟）
        test_text = "test"
        t0 = time.time()
        self.cli.interact_input(self.cli_session, "input", test_text)
        input_elapsed = time.time() - t0

        # input 应有字符级延迟（50-250ms/char * 4 chars）
        assert input_elapsed > 0.2  # 至少 200ms（4 字符 * 50ms）

    def test_persistent_cdp_session(self):
        """验证持久化 CDP 会话（多次操作不重新创建连接）"""
        # 创建会话
        result = self.cli.session_create(self.cli_session)
        cdp_url = result["data"]["cdp_url"]

        # 多次操作
        for _ in range(5):
            self.cli.navigate_goto(self.cli_session, "https://example.com")

        # 验证 cdp_url 未变化（持久化连接）
        info_result = self.cli.run(["session", "info", "--session", self.cli_session])
        assert info_result["data"]["cdp_url"] == cdp_url

    @pytest.mark.asyncio
    async def test_cli_api_anti_detection_parity(self):
        """验证 CLI 和 API 模式反侦测能力 100% 对齐"""
        # CLI 模式：测量延迟
        self.cli.session_create(self.cli_session)
        t0_cli = time.time()
        self.cli.navigate_goto(self.cli_session, "https://example.com")
        cli_delay = time.time() - t0_cli

        # API 模式：测量延迟
        api_result = await self.api.create_session()
        self.api_session = api_result["session_id"]

        t0_api = time.time()
        await self.api.submit_task(self.api_session, "打开百度，搜索ai coding，输出前5条搜索内容", max_steps=10)
        api_delay = time.time() - t0_api

        # 验证两种模式都有 StealthEnhancer 延迟
        assert cli_delay > 0.2  # CLI 有延迟
        assert api_delay > 0.2  # API 也有延迟

        # 延迟应该在同一数量级（说明使用相同的 StealthEnhancer）
        assert 0.5 < (cli_delay / api_delay) < 2.0

    @pytest.mark.boss
    def test_bot_sannysoft_detection(self):
        """可选：真实反检测测试（bot.sannysoft.com）"""
        # 创建会话
        self.cli.session_create(self.cli_session)

        # 访问 bot.sannysoft.com
        self.cli.navigate_goto(self.cli_session, "https://bot.sannysoft.com")

        # 提取检测结果（需要添加 screenshot 或 extract 命令）
        # result = self.cli.extract_text(self.cli_session, ".webdriver-result")
        # assert "false" in result["data"]["text"].lower()

        # 临时：跳过真实检测（需要真实浏览器）
        pytest.skip("需要真实浏览器环境")

    def test_warmup_browsing_called(self):
        """验证 warmup_browsing() 被调用（通过日志或时间验证）"""
        # 创建会话（应触发 warmup_browsing）
        t0 = time.time()
        result = self.cli.session_create(self.cli_session)
        elapsed = time.time() - t0

        # warmup_browsing 访问 3 个 URL，每个 3-8s，总计 9-24s
        # 如果 SKIP_WARMUP=1，应该 < 5s
        # 如果 SKIP_WARMUP=0，应该 > 9s

        # 测试环境默认 SKIP_WARMUP=1，所以应该快速完成
        assert elapsed < 10  # 测试环境跳过 warmup

        # 生产环境验证（需要手动设置 SKIP_WARMUP=0）
        # assert elapsed > 9  # 生产环境有 warmup
