"""桌面 Electron 应用控制 — CDP 直连 + AppleScript 桥接"""
from .runner import run_desktop_command, list_desktop_apps
from .cdp_discovery import discover_cdp
from .applescript import run_applescript

__all__ = ["run_desktop_command", "list_desktop_apps", "discover_cdp", "run_applescript"]
