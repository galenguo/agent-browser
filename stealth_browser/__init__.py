"""Stealth Browser - Anti-detection browser automation framework built on browser-use."""

__version__ = "0.1.0-dev"

# Public API - facade functions (from main.py)
# Adapters
from .adapters import list_adapters, run_adapter

# OOP interface
from .client import StealthBrowser

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
    "StealthBrowser",
    "FirstSessionError",
    # LLM
    "LLMFactory",
    "SkillConfig",
    "cascade",
    "click",
    # Configuration
    "configure",
    # Facade API
    "create_session",
    "delete_session",
    "detect_missing_deps",
    "detect_mode",
    "evaluate",
    # Explore
    "explore",
    "fill",
    "go_back",
    "hover",
    # Adapters
    "list_adapters",
    "load_config",
    "open_page",
    "press_key",
    "reset",
    "run_adapter",
    "run_task",
    "scroll",
    "select_option",
    # Setup / recovery
    "setup",
    "snapshot",
    "synthesize",
    "wait_for_selector",
]
