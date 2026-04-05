"""配置管理器 — 支持 YAML + 环境变量 + 自动探测"""
import os
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Literal, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class SkillConfig:
    """Skill 统一配置"""
    # 模式
    calling_mode: str = "cli"         # "cli" | "api"
    browser_mode: str = "local"       # "local" | "remote"
    intelligence: str = "llm"         # "llm" | "agent"

    # 本地 CDP
    cdp_url: str = "http://127.0.0.1:19222"

    # 远程 API
    api_url: str = "http://localhost:8000"
    api_key: str = ""

    # Daemon
    daemon_enabled: bool = True
    daemon_idle_timeout: int = 1800   # 秒
    daemon_state_path: str = "~/.agent-browser/daemon-state.json"

    # 浏览器
    headless: bool = False
    default_timeout: int = 30000      # ms

    # 隐匿
    stealth_enabled: bool = True
    stealth_mode: Literal["full", "vanilla"] = "full"
    #   full:    CloakBrowser + 全部 6 层反检测栈 + StealthEnhancer 行为模拟
    #   vanilla: 标准 Playwright + 仅 StealthEnhancer 延迟行为（无需 CloakBrowser）
    warmup_enabled: bool = False


def _resolve_env_vars(config: dict) -> dict:
    """递归解析 ${VAR_NAME} 环境变量引用"""
    result = {}
    for k, v in config.items():
        if isinstance(v, dict):
            result[k] = _resolve_env_vars(v)
        elif isinstance(v, str) and v.startswith("${") and v.endswith("}"):
            result[k] = os.getenv(v[2:-1])
        else:
            result[k] = v
    return result


def _load_yaml_config(path: Path) -> dict:
    """加载 YAML 配置文件"""
    if not path.exists():
        return {}
    try:
        import yaml
        with open(path) as f:
            config = yaml.safe_load(f) or {}
        return _resolve_env_vars(config)
    except Exception as e:
        logger.warning(f"Failed to load config from {path}: {e}")
        return {}


def _apply_env_overrides(cfg: SkillConfig) -> SkillConfig:
    """用环境变量覆盖配置"""
    if v := os.getenv("AGENT_BROWSER_CALLING_MODE"):
        cfg.calling_mode = v
    if v := os.getenv("AGENT_BROWSER_BROWSER_MODE"):
        cfg.browser_mode = v
    if v := os.getenv("AGENT_BROWSER_INTELLIGENCE"):
        cfg.intelligence = v
    if v := os.getenv("AGENT_BROWSER_CDP_URL"):
        cfg.cdp_url = v
    if v := os.getenv("AGENT_BROWSER_API_URL"):
        cfg.api_url = v
    if v := os.getenv("AGENT_BROWSER_API_KEY"):
        cfg.api_key = v
    if v := os.getenv("AGENT_BROWSER_DAEMON_ENABLED"):
        cfg.daemon_enabled = v.lower() in ("1", "true", "yes")
    if v := os.getenv("AGENT_BROWSER_DAEMON_IDLE_TIMEOUT"):
        cfg.daemon_idle_timeout = int(v)
    if v := os.getenv("AGENT_BROWSER_STEALTH_ENABLED"):
        cfg.stealth_enabled = v.lower() in ("1", "true", "yes")
    if v := os.getenv("AGENT_BROWSER_STEALTH_MODE"):
        if v in ("full", "vanilla"):
            cfg.stealth_mode = v
    return cfg


def _apply_yaml_overrides(cfg: SkillConfig, yaml_data: dict) -> SkillConfig:
    """用 YAML 配置覆盖（仅覆盖非默认值）"""
    skill = yaml_data.get("skill", yaml_data)

    if "calling_mode" in skill:
        cfg.calling_mode = skill["calling_mode"]
    if "browser_mode" in skill:
        cfg.browser_mode = skill["browser_mode"]
    if "intelligence" in skill:
        cfg.intelligence = skill["intelligence"]
    if "cdp_url" in skill:
        cfg.cdp_url = skill["cdp_url"]
    if "api_url" in skill:
        cfg.api_url = skill["api_url"]
    if "api_key" in skill:
        cfg.api_key = skill["api_key"]

    daemon = skill.get("daemon", {})
    if "enabled" in daemon:
        cfg.daemon_enabled = daemon["enabled"]
    if "idle_timeout" in daemon:
        cfg.daemon_idle_timeout = daemon["idle_timeout"]
    if "state_path" in daemon:
        cfg.daemon_state_path = daemon["state_path"]

    browser = skill.get("browser", {})
    if "headless" in browser:
        cfg.headless = browser["headless"]
    if "default_timeout" in browser:
        cfg.default_timeout = browser["default_timeout"]

    stealth = skill.get("stealth", {})
    if "enabled" in stealth:
        cfg.stealth_enabled = stealth["enabled"]
    if "mode" in stealth:
        mode_val = stealth["mode"]
        if mode_val in ("full", "vanilla"):
            cfg.stealth_mode = mode_val
    if "warmup" in stealth:
        cfg.warmup_enabled = stealth["warmup"]

    return cfg


async def detect_mode() -> SkillConfig:
    """
    自动探测模式（最后手段）。

    优先级：显式参数 > 环境变量 > YAML > 自动探测 > 默认

    探测逻辑：
    1. localhost:8000/health 可达 → API mode
    2. 127.0.0.1:19222/json/version 可达 → CLI mode
    3. 默认 → CLI + local
    """
    cfg = SkillConfig()

    # 1. 加载 YAML 配置
    config_path = Path.home() / ".agent-browser" / "config.yaml"
    yaml_data = _load_yaml_config(config_path)
    if yaml_data:
        cfg = _apply_yaml_overrides(cfg, yaml_data)

    # 2. 环境变量覆盖
    cfg = _apply_env_overrides(cfg)

    # 3. 自动探测（仅在未明确设置时）
    if not os.getenv("AGENT_BROWSER_CALLING_MODE") and not yaml_data.get("skill", {}).get("calling_mode"):
        try:
            import aiohttp
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    "http://localhost:8000/health",
                    timeout=aiohttp.ClientTimeout(total=1),
                ) as r:
                    if r.status == 200:
                        cfg.calling_mode = "api"
                        cfg.api_url = "http://localhost:8000"
                        logger.info("Auto-detected: API mode (FastAPI reachable)")
                        return cfg
        except Exception:
            pass

        try:
            import aiohttp
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    f"http://127.0.0.1:19222/json/version",
                    timeout=aiohttp.ClientTimeout(total=1),
                ) as r:
                    if r.status == 200:
                        cfg.calling_mode = "cli"
                        cfg.browser_mode = "local"
                        logger.info("Auto-detected: CLI mode (CDP reachable)")
                        return cfg
        except Exception:
            pass

    return cfg


def load_config(**overrides) -> SkillConfig:
    """同步加载配置（用于不依赖自动探测的场景）"""
    cfg = SkillConfig()

    config_path = Path.home() / ".agent-browser" / "config.yaml"
    yaml_data = _load_yaml_config(config_path)
    if yaml_data:
        cfg = _apply_yaml_overrides(cfg, yaml_data)

    cfg = _apply_env_overrides(cfg)

    # 显式参数覆盖
    for k, v in overrides.items():
        if hasattr(cfg, k) and v is not None:
            setattr(cfg, k, v)

    # 约束：CLI 模式不支持 remote 浏览器
    if cfg.calling_mode == "cli" and cfg.browser_mode == "remote":
        logger.warning("CLI mode does not support remote browser, falling back to local")
        cfg.browser_mode = "local"

    return cfg
