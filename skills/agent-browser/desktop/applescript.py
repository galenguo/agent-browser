"""AppleScript 桥接 — macOS UI 自动化辅助"""
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def run_applescript(script: str) -> str:
    """
    执行 AppleScript 并返回结果。

    隐匿性:
      - 通过 System Events（无障碍 API），不注入任何代码到目标应用
      - 使用 macOS 原生机制，不暴露指纹
    """
    proc = await asyncio.create_subprocess_exec(
        "osascript", "-e", script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        error_msg = stderr.decode().strip()
        logger.warning(f"AppleScript error: {error_msg}")
        return ""

    return stdout.decode().strip()


async def is_app_running(app_name: str) -> bool:
    """检查应用是否运行"""
    result = await run_applescript(f'application "{app_name}" is running')
    return result.lower() == "true"


async def activate_app(app_name: str) -> bool:
    """激活（前置）应用"""
    result = await run_applescript(f'tell application "{app_name}" to activate')
    return result == ""  # activate 无返回值，无错误即为成功


async def get_frontmost_app() -> str:
    """获取当前最前面的应用名"""
    return await run_applescript('name of application (path to frontmost application)')


async def screenshot_window(app_name: str, output_path: str) -> bool:
    """
    截取窗口截图（使用 macOS 原生 screencapture）。

    隐匿性: 使用 screencapture 命令（macOS 原生），不使用 CDP screenshot。
    """
    proc = await asyncio.create_subprocess_exec(
        "screencapture", "-l", output_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.warning(f"screencapture error: {stderr.decode().strip()}")
        return False
    return True


async def type_text(text: str) -> bool:
    """通过 System Events 输入文本"""
    # 转义双引号
    escaped = text.replace('"', '\\"')
    result = await run_applescript(
        f'tell application "System Events" to keystroke "{escaped}"'
    )
    return result == ""


async def press_key(key: str) -> bool:
    """通过 System Events 按键"""
    key_map = {
        "enter": "return",
        "tab": "tab",
        "escape": "escape",
        "backspace": "delete",
        "delete": "forward delete",
        "up": "up arrow",
        "down": "down arrow",
        "left": "left arrow",
        "right": "right arrow",
        "cmd": "command",
        "ctrl": "control",
        "alt": "option",
        "shift": "shift",
    }
    mapped = key_map.get(key.lower(), key)
    result = await run_applescript(
        f'tell application "System Events" to key code {mapped}'
    )
    return result == ""
