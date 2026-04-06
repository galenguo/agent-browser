"""Agent Browser - Anti-detection browser automation framework built on browser-use."""

__version__ = "0.1.0-dev"

# Public API - facade functions (from main.py)
# Adapters
from .adapters import list_adapters, run_adapter

# OOP interface
from .client import AgentBrowser

# Configuration
from .config import SkillConfig, detect_mode, load_config
from .explore import cascade_explore as cascade

# Explore
from .explore import explore, synthesize

# LLM
from .llm.factory import LLMFactory
from .main import (
    FirstSessionError,
    click,
    configure,
    create_session,
    delete_session,
    detect_missing_deps,
    evaluate,
    fill,
    go_back,
    hover,
    open_page,
    press_key,
    reset,
    run_task,
    scroll,
    select_option,
    setup,
    snapshot,
    wait_for_selector,
)

__all__ = [
    # OOP interface
    "AgentBrowser",
    # Facade API
    "create_session",
    "delete_session",
    "open_page",
    "snapshot",
    "click",
    "fill",
    "scroll",
    "evaluate",
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
    # LLM
    "LLMFactory",
]
