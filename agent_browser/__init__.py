"""Agent Browser - Anti-detection browser automation framework built on browser-use."""

__version__ = "0.1.0-dev"

# Public API - facade functions (from main.py)
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

# Configuration
from .config import SkillConfig, load_config, detect_mode

# Adapters
from .adapters import list_adapters, run_adapter

# Explore
from .explore import explore, synthesize, cascade_explore as cascade

__all__ = [
    # Facade API
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
    # Configuration
    "configure",
    "SkillConfig",
    "load_config",
    "detect_mode",
    # Setup / recovery
    "setup",
    "FirstSessionError",
    "detect_missing_deps",
    # Adapters
    "list_adapters",
    "run_adapter",
    # Explore
    "explore",
    "synthesize",
    "cascade",
]
