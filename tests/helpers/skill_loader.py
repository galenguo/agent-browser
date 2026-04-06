"""Test helper for loading agent_browser modules.

In the restructured package, agent_browser is a proper installable package.
This helper provides convenient access to core classes for tests that
need them without importing the full package at module level.
"""

from typing import Any


def get_skill_classes() -> dict[str, Any]:
    """Get core classes from the agent_browser package.

    Returns:
        Dict containing SkillConfig, load_config, BrowserDaemon, StealthEnhancer
    """
    from agent_browser.browser.daemon import BrowserDaemon
    from agent_browser.config import SkillConfig, load_config
    from agent_browser.stealth.enhancer import StealthEnhancer

    return {
        "SkillConfig": SkillConfig,
        "load_config": load_config,
        "BrowserDaemon": BrowserDaemon,
        "StealthEnhancer": StealthEnhancer,
    }


# Pre-loaded cache
_skill_classes: dict[str, Any] | None = None


def _ensure_loaded() -> dict[str, Any]:
    """Ensure skill modules are loaded."""
    global _skill_classes
    if _skill_classes is None:
        _skill_classes = get_skill_classes()
    return _skill_classes


# Convenience functions
def SkillConfig(*args, **kwargs):
    return _ensure_loaded()["SkillConfig"](*args, **kwargs)


def load_config_fn(*args, **kwargs):
    return _ensure_loaded()["load_config"](*args, **kwargs)


def BrowserDaemon(*args, **kwargs):
    return _ensure_loaded()["BrowserDaemon"](*args, **kwargs)


def StealthEnhancer(*args, **kwargs):
    return _ensure_loaded()["StealthEnhancer"](*args, **kwargs)


def load_skill_module(module_name: str):
    """Load a module from agent_browser package by name.

    Args:
        module_name: e.g. "config", "daemon", "stealth", "main"

    Returns:
        The imported module
    """
    import importlib

    return importlib.import_module(f"agent_browser.{module_name}")
