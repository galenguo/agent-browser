"""
Skill 包加载助手

解决 agent-browser 包名中 hyphen 无法直接 import 的问题。
"""
import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict

_SKILL_DIR = Path(__file__).parent.parent.parent / "skills" / "agent-browser"

# 导出 SKILL_DIR 供外部使用
SKILL_DIR = _SKILL_DIR


def _register_parent_package():
    """注册父包以支持相对导入"""
    if "agent_browser" not in sys.modules:
        # 创建父包
        parent_spec = importlib.util.spec_from_file_location(
            "agent_browser",
            _SKILL_DIR / "__init__.py"
        )
        parent_module = importlib.util.module_from_spec(parent_spec)
        sys.modules["agent_browser"] = parent_module
        parent_spec.loader.exec_module(parent_module)


def _load_module_with_deps(module_name: str) -> Any:
    """
    加载模块及其依赖，处理相对导入。
    """
    module_path = _SKILL_DIR / f"{module_name}.py"
    package_path = _SKILL_DIR / module_name / "__init__.py"

    # 确保父包已注册
    _register_parent_package()

    if module_name == "main":
        # main.py 的依赖链
        deps = ["config", "backends", "daemon", "stealth"]
        for dep in deps:
            dep_key = f"agent_browser.{dep}"
            if dep_key not in sys.modules:
                _load_single_module(dep)

        # 加载 main
        return _load_single_module("main")

    return _load_single_module(module_name)


def _load_single_module(module_name: str) -> Any:
    """加载单个模块"""
    module_path = _SKILL_DIR / f"{module_name}.py"
    package_path = _SKILL_DIR / module_name / "__init__.py"

    module_key = f"agent_browser.{module_name}"

    if module_key in sys.modules:
        return sys.modules[module_key]

    if package_path.exists():
        # 包目录
        spec = importlib.util.spec_from_file_location(
            module_key,
            package_path
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_key] = module
        spec.loader.exec_module(module)
        return module

    if module_path.exists():
        spec = importlib.util.spec_from_file_location(
            module_key,
            module_path
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_key] = module
        spec.loader.exec_module(module)
        return module

    raise FileNotFoundError(f"Module not found: {module_path} or {package_path}")


def load_skill_module(module_name: str) -> Any:
    """
    加载 skill 模块。

    Args:
        module_name: 模块名，如 "config", "daemon", "stealth", "backends", "main"

    Returns:
        模块对象
    """
    return _load_module_with_deps(module_name)


def get_skill_classes() -> Dict[str, Any]:
    """
    获取 skill 包的核心类。

    Returns:
        字典包含 SkillConfig, BrowserDaemon, StealthEnhancer
    """
    config = load_skill_module("config")
    stealth = load_skill_module("stealth")
    daemon = load_skill_module("daemon")

    return {
        "SkillConfig": config.SkillConfig,
        "load_config": config.load_config,
        "BrowserDaemon": daemon.BrowserDaemon,
        "StealthEnhancer": stealth.StealthEnhancer,
    }


# 预加载的便捷访问
_skill_classes = None


def _ensure_loaded():
    """确保 skill 模块已加载"""
    global _skill_classes
    if _skill_classes is None:
        _skill_classes = get_skill_classes()
    return _skill_classes


# 便捷函数
def SkillConfig(*args, **kwargs):
    return _ensure_loaded()["SkillConfig"](*args, **kwargs)


def load_config(*args, **kwargs):
    return _ensure_loaded()["load_config"](*args, **kwargs)


def BrowserDaemon(*args, **kwargs):
    return _ensure_loaded()["BrowserDaemon"](*args, **kwargs)


def StealthEnhancer(*args, **kwargs):
    return _ensure_loaded()["StealthEnhancer"](*args, **kwargs)


# 导出模块级函数
config_module = property(lambda self: load_skill_module("config"))
daemon_module = property(lambda self: load_skill_module("daemon"))
stealth_module = property(lambda self: load_skill_module("stealth"))
