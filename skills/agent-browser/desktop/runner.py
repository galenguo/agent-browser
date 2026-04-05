"""桌面应用命令执行器 — 路由到 CDP 或 AppleScript"""
import asyncio
import logging
import os
import random
from typing import Any, List, Optional

import yaml

from .cdp_discovery import discover_cdp, get_cdp
from .applescript import (
    run_applescript, is_app_running, activate_app, screenshot_window,
)

logger = logging.getLogger(__name__)

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

    路由到 CDP 或 AppleScript 执行器。CDP 操作通过 StealthMiddleware 隐匿包装。
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
                    from ..main import create_session, delete_session
                    # 通过 StealthMiddleware 创建 session + 获取 handle
                    sid = await create_session(cdp_url=cdp_url)
                    try:
                        from ..main import _ensure_middleware
                        mw = await _ensure_middleware()
                        handle = await mw.get_page(sid)
                        result["cdp_result"] = await handle.evaluate(js_code)
                    finally:
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

        await asyncio.sleep(random.uniform(0.3, 1.0))

    return result
