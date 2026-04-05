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
    configure,
    run_task,
    reset,
    setup,
    FirstSessionError,
    detect_missing_deps,
)

# 配置系统
from .config import SkillConfig, load_config

# 部署配置（Phase 1+）
from .deploy_config import (
    DeployConfig,
    ConfigIssue,
    load_deploy_config,
    generate_config,
    validate_config,
    detect_environment,
)

# 适配器系统
from .adapters import list_adapters, run_adapter

# AI 探索生成
from .explore import explore, synthesize, cascade

# 桌面应用控制
from .desktop import run_desktop_command, list_desktop_apps

__all__ = [
    # 原有 API（向后兼容）
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
    "run_task",
    "reset",
    # 配置
    "configure",
    "SkillConfig",
    "load_config",
    # 部署配置 + First-Session Recovery
    "setup",
    "FirstSessionError",
    "detect_missing_deps",
    "DeployConfig",
    "ConfigIssue",
    "load_deploy_config",
    "generate_config",
    "validate_config",
    "detect_environment",
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
