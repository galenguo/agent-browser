"""Agent Browser Skill"""
from .main import (
    create_session,
    delete_session,
    open_page,
    snapshot,
    click,
    fill,
    scroll,
    select_option,
    hover,
    press_key,
    wait_for_selector,
    go_back,
)

# 适配器系统
from .adapters import list_adapters, run_adapter

# AI 探索生成
from .explore import explore, synthesize, cascade

# 桌面应用控制
from .desktop import run_desktop_command, list_desktop_apps

__all__ = [
    # 原有 API
    "create_session",
    "delete_session",
    "open_page",
    "snapshot",
    "click",
    "fill",
    "scroll",
    "select_option",
    "hover",
    "press_key",
    "wait_for_selector",
    "go_back",
    # 站点适配器
    "list_adapters",
    "run_adapter",
    # AI 探索
    "explore",
    "synthesize",
    "cascade",
    # 桌面控制
    "run_desktop_command",
    "list_desktop_apps",
]
