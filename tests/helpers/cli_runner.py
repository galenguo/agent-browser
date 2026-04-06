"""
CLI 命令执行工具

通过 subprocess 运行 CLI 命令并解析 JSON 输出。
"""
import json
import subprocess


class CLIRunner:
    """CLI 命令执行器"""

    def __init__(self, cli_path: str = "python -m src.cli.commands"):
        self.cli_path = cli_path

    def run(self, args: list[str], timeout: int = 900) -> dict:
        """
        执行 CLI 命令并返回 JSON 结果。

        Args:
            args: 命令参数列表，如 ["session", "create", "--name", "test"]
            timeout: 超时时间（秒），默认 180 秒（包含浏览器启动时间）

        Returns:
            解析后的 JSON 结果字典
        """
        cmd = self.cli_path.split() + args
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        # 解析 JSON 输出
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return {
                "status": "error",
                "error": f"Failed to parse JSON: {result.stdout}",
                "stderr": result.stderr,
            }

    def session_create(self, name: str, browser: str = "local") -> dict:
        """创建会话"""
        return self.run(["session", "create", "--name", name, "--browser", browser])

    def session_destroy(self, name: str) -> dict:
        """销毁会话"""
        return self.run(["session", "destroy", "--session", name])

    def navigate_goto(self, session: str, url: str) -> dict:
        """导航到 URL"""
        return self.run(["navigate", "goto", "--session", session, "--url", url])

    def interact_click(self, session: str, selector: str) -> dict:
        """点击元素"""
        return self.run(["interact", "click", "--session", session, "--selector", selector])

    def interact_input(self, session: str, selector: str, text: str) -> dict:
        """输入文本"""
        return self.run(["interact", "input", "--session", session, "--selector", selector, "--text", text])

    def extract_text(self, session: str, selector: str) -> dict:
        """提取文本"""
        return self.run(["extract", "text", "--session", session, "--selector", selector])
