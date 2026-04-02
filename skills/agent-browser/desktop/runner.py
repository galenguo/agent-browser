"""桌面应用命令执行器 — 路由到 CDP 或 AppleScript"""
import asyncio
import json
import logging
import os
import random
from typing import Any, Dict, List, Optional

import yaml

from .cdp_discovery import discover_cdp, get_cdp
from .applescript import (
    run_applescript, is_app_running, activate_app, screenshot_window,
)

logger = logging.getLogger(__name__)

# 桌面适配器目录
_ADAPTER_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "adapters", "desktop",
)


def list_desktop_apps() -> List[dict]:
    """列出所有桌面应用适配器"""
    apps = []
    if not os.path.isdir(_ADAPTER_DIR):
        return apps

    for fname in os.listdir(_ADAPTER_DIR):
        if not fname.endswith((".yaml", ".yml")):
            continue
        fpath = os.path.join(_ADAPTER_DIR, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                adapter = yaml.safe_load(f)
            if adapter and "app" in adapter:
                apps.append({
                    "app": adapter["app"],
                    "name": adapter.get("name", adapter["app"]),
                    "type": adapter.get("type", "electron"),
                    "commands": list(adapter.get("commands", {}).keys()),
                })
        except Exception as e:
            logger.warning(f"Failed to load desktop adapter {fpath}: {e}")

    return apps


def _load_app_adapter(app_name: str) -> Optional[dict]:
    """加载应用适配器"""
    if not os.path.isdir(_ADAPTER_DIR):
        return None

    for fname in os.listdir(_ADAPTER_DIR):
        if not fname.endswith((".yaml", ".yml")):
            continue
        fpath = os.path.join(_ADAPTER_DIR, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                adapter = yaml.safe_load(f)
            if adapter and adapter.get("app", "").lower() == app_name.lower():
                return adapter
        except Exception:
            continue
    return None


async def run_desktop_command(
    app_name: str,
    command: str,
    **kwargs: Any,
) -> dict:
    """
    执行桌面应用命令。

    路由到 CDP 或 AppleScript 执行器。

    隐匿性:
      - CDP 连接复用 patchright 驱动级补丁
      - AppleScript 通过 System Events（无障碍 API），不注入代码
      - 截图使用 screencapture（macOS 原生），不使用 CDP screenshot
    """
    adapter = _load_app_adapter(app_name)
    if not adapter:
        raise ValueError(f"Desktop adapter not found: {app_name}")

    commands = adapter.get("commands", {})
    if command not in commands:
        raise ValueError(f"Command '{command}' not found for {app_name}")

    command_def = commands[command]
    pipeline = command_def.get("pipeline", [])

    result = {}
    for step in pipeline:
        if "applescript" in step:
            script = step["applescript"]
            if isinstance(script, str):
                output = await run_applescript(script)
                result["applescript"] = output

        elif "cdp_discover" in step:
            infos = await discover_cdp()
            app_info = [i for i in infos if app_name.lower() in i.app_name.lower()]
            result["cdp"] = {
                "found": len(app_info) > 0,
                "url": app_info[0].url if app_info else None,
            }

        elif "cdp_evaluate" in step:
            js_code = step["cdp_evaluate"]
            cdp_url = await get_cdp(app_name)
            if cdp_url:
                try:
                    from ..main import _manager, create_session
                    # 使用 patchright 连接（隐匿性保障）
                    sid = await create_session(cdp_url)
                    try:
                        session = _manager.get_session(sid)
                        page = session.page
                        result["cdp_result"] = await page.evaluate(js_code)
                    finally:
                        from ..main import delete_session
                        await delete_session(sid)
                except Exception as e:
                    result["cdp_error"] = str(e)
            else:
                result["cdp_error"] = "CDP not found"

        elif "is_running" in step:
            result["running"] = await is_app_running(app_name)

        elif "activate" in step:
            await activate_app(app_name)
            result["activated"] = True

        elif "screenshot" in step:
            output_path = kwargs.get("output_path", "/tmp/desktop_screenshot.png")
            result["screenshot"] = await screenshot_window(app_name, output_path)
            result["screenshot_path"] = output_path if result["screenshot"] else None

        # 隐匿性：步骤间随机延迟
        await asyncio.sleep(random.uniform(0.3, 1.0))

    return result
