"""Configuration management -- supports YAML + environment variables + auto-detection.

Merges SkillConfig (primary, skill-layer config) with server-side dataclasses
(LLMConfig, BrowserConfig, APIConfig, CLIConfig) from the former ConfigManager.
This is the single source of truth for all configuration in the stealth_browser package.

Config precedence:
  1. Explicit parameters (function kwargs)
  2. Environment variables (STEALTH_BROWSER_*)
  3. YAML config (~/.stealth-browser/config.yaml)
  4. Auto-detection (localhost:8000, 127.0.0.1:19222)
  5. Hardcoded defaults
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)


# ── Primary: SkillConfig (skill-layer unified config) ──────────


@dataclass
class SkillConfig:
    """Unified skill configuration for the stealth_browser runtime."""

    # Mode
    calling_mode: str = "api"  # "cli" | "api"
    browser_mode: str = "remote"  # "remote" only (local mode deprecated)
    intelligence: str = "llm"  # "llm" | "agent"

    # Local CDP
    cdp_url: str = "http://127.0.0.1:19222"

    # Remote API
    api_url: str = "http://localhost:8000"
    api_key: str = ""
    remote_type: str = "aio"  # "aio" | "distributed" (only when browser_mode="remote")
    vnc_url: str = ""         # noVNC endpoint; static for aio, empty for distributed (per-session)

    # Daemon
    daemon_enabled: bool = True
    daemon_idle_timeout: int = 1800  # seconds
    daemon_state_path: str = "~/.stealth-browser/daemon-state.json"

    # Browser
    headless: bool = False
    default_timeout: int = 30000  # ms

    # Stealth
    stealth_enabled: bool = True
    stealth_mode: Literal["full", "vanilla"] = "full"
    stealth_profile: str = "minimal"  # "full" | "balanced" | "minimal" | "off"
    #   full:    CloakBrowser + full 6-layer anti-detection stack + StealthEnhancer behavior simulation
    #   vanilla: Standard Playwright + only StealthEnhancer delay behavior (no CloakBrowser needed)
    warmup_enabled: bool = False

    # Extension (Chrome Extension mode)
    extension_enabled: bool = True  # Whether to attempt ExtensionBackend (Chrome Extension → natural fingerprints)


# ── Server-side dataclasses (absorbed from former ConfigManager) ──


@dataclass
class LLMConfig:
    """LLM provider configuration."""

    provider: str
    model: str
    api_key: str | None
    base_url: str | None
    temperature: float


@dataclass
class BrowserConfig:
    """Browser engine configuration."""

    headless: bool
    cdp_port: int
    cloakbrowser_path: str
    default_timeout: int


@dataclass
class APIConfig:
    """API server configuration."""

    host: str
    port: int
    max_sessions: int
    idle_timeout_seconds: int
    profile_storage: str
    browser_mode: str


@dataclass
class CLIConfig:
    """CLI mode configuration."""

    profile_storage: str
    session_storage: str
    default_max_steps: int
    auto_cleanup: bool
    idle_timeout_minutes: int
    max_sessions: int


# ── ConfigManager (server-side config manager) ──────────────────


class ConfigManager:
    """Unified configuration manager with YAML file support and env var resolution."""

    def __init__(self, config_path: Path | None = None):
        self.config_path = config_path or Path.home() / ".stealth-browser" / "config.yaml"
        self._config = self._load_config()

    def _load_config(self) -> dict:
        """Load configuration file with environment variable substitution."""
        if not self.config_path.exists():
            return self._get_default_config()

        try:
            import yaml

            with open(self.config_path) as f:
                config = yaml.safe_load(f)
        except Exception:
            return self._get_default_config()

        return self._resolve_env_vars(config)

    def _resolve_env_vars(self, obj: Any) -> Any:
        """Recursively resolve ${VAR_NAME} environment variable references."""
        if isinstance(obj, dict):
            return {k: self._resolve_env_vars(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._resolve_env_vars(item) for item in obj]
        if isinstance(obj, str) and obj.startswith("${") and obj.endswith("}"):
            var_name = obj[2:-1]
            return os.getenv(var_name)
        return obj

    def _get_default_config(self) -> dict:
        """Default configuration values."""
        return {
            "llm": {
                "default_provider": "anthropic",
                "openai": {"default_model": "gpt-4", "temperature": 0.1},
                "anthropic": {"default_model": "claude-3-5-sonnet-20241022", "temperature": 0.1},
            },
            "browser": {
                "local": {"headless": False, "cdp_port": 19222},
                "remote": {"enabled": False, "host": None, "port": 19222, "cdp_url": None},
            },
            "cli": {
                "default_max_steps": 10,
                "browser_mode": "local",
                "session": {"storage": "~/.stealth-browser/sessions.json", "max_sessions": 5, "idle_timeout_minutes": 30},
            },
            "api": {
                "host": "0.0.0.0",
                "port": 8000,
                "max_sessions": 10,
                "idle_timeout_seconds": 1800,
                "browser_mode": "local",
            },
        }

    def get_llm_config(self, provider: str | None = None, **overrides) -> LLMConfig:
        """Get LLM configuration with parameter override support."""
        provider = provider or self._config["llm"]["default_provider"]
        llm_cfg = self._config["llm"][provider]

        return LLMConfig(
            provider=provider,
            model=overrides.get("model") or llm_cfg.get("default_model"),
            api_key=overrides.get("api_key") or llm_cfg.get("api_key") or os.getenv(f"{provider.upper()}_API_KEY"),
            base_url=overrides.get("base_url") or llm_cfg.get("base_url") or os.getenv(f"{provider.upper()}_BASE_URL"),
            temperature=overrides.get("temperature") or llm_cfg.get("temperature", 0.1),
        )

    def get_browser_config(self, **overrides) -> BrowserConfig:
        """Get browser configuration."""
        cfg = self._config.get("browser", {}).get("local", {})
        return BrowserConfig(
            headless=overrides.get("headless", cfg.get("headless", False)),
            cdp_port=overrides.get("cdp_port", cfg.get("cdp_port", 19222)),
            cloakbrowser_path=overrides.get("cloakbrowser_path", "/opt/cloakbrowser/chrome"),
            default_timeout=overrides.get("default_timeout", 30000),
        )

    def get_browser_remote_config(self) -> dict | None:
        """Get remote browser configuration."""
        remote_cfg = self._config.get("browser", {}).get("remote", {})
        if not remote_cfg.get("enabled"):
            return None
        return {
            "host": remote_cfg.get("host"),
            "port": remote_cfg.get("port", 19222),
            "cdp_url": remote_cfg.get("cdp_url"),
        }

    def get_cli_browser_mode(self) -> str:
        """Get CLI default browser mode."""
        return self._config.get("cli", {}).get("browser_mode", "local")

    def get_api_config(self) -> APIConfig:
        """Get API mode configuration."""
        cfg = self._config["api"]
        return APIConfig(
            host=cfg.get("host", "0.0.0.0"),
            port=cfg.get("port", 8000),
            max_sessions=cfg.get("max_sessions", 10),
            idle_timeout_seconds=cfg.get("idle_timeout_seconds", 1800),
            profile_storage=cfg.get("profile_storage", "/data/profiles"),
            browser_mode=cfg.get("browser_mode", "local"),
        )

    def get_cli_config(self) -> CLIConfig:
        """Get CLI mode configuration."""
        cfg = self._config["cli"]
        session_cfg = cfg.get("session", {})
        return CLIConfig(
            profile_storage=cfg.get("profile_storage", "~/.stealth-browser/profiles"),
            session_storage=cfg.get("session_storage", "~/.stealth-browser/sessions.json"),
            default_max_steps=cfg.get("default_max_steps", 10),
            auto_cleanup=session_cfg.get("auto_cleanup", True),
            idle_timeout_minutes=session_cfg.get("idle_timeout_minutes", 30),
            max_sessions=session_cfg.get("max_sessions", 5),
        )

    def get_execution_mode(self) -> str:
        """Get execution mode."""
        return self._config.get("execution", {}).get("mode", "autonomous")

    def save_config(self):
        """Save configuration to file with comments."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        config_content = """# Stealth Browser Configuration File
#
# Quick start:
# 1. Set LLM API key (required)
# 2. Other settings use defaults
# 3. Advanced users can adjust as needed

# ============================================
# LLM Configuration (required - needed by both CLI and API modes)
# ============================================
llm:
  # Choose LLM provider: openai or anthropic
  default_provider: anthropic

  # Anthropic config
  anthropic:
    api_key: ${ANTHROPIC_API_KEY}  # Read from environment variable
    default_model: claude-3-5-sonnet-20241022
    temperature: 0.1

  # OpenAI config (or compatible APIs like GLM)
  openai:
    api_key: ${OPENAI_API_KEY}
    default_model: gpt-4
    temperature: 0.1

# ============================================
# Browser Configuration (shared by CLI and API modes)
# ============================================
browser:
  # Local browser config
  local:
    headless: false  # Whether to run in headless mode
    cdp_port: 19222  # CDP port

  # Remote browser config (optional)
  remote:
    enabled: false        # Enable remote mode
    host: null            # Remote host, e.g.: 192.168.1.100
    port: 19222           # Remote CDP port
    cdp_url: null         # Or specify full URL directly

# ============================================
# CLI Mode Configuration (only needed when using command line)
# ============================================
cli:
  default_max_steps: 10   # Default max steps per task
  browser_mode: local     # local (local) or remote (remote)

  # Session management
  session:
    storage: ~/.stealth-browser/sessions.json
    max_sessions: 5
    idle_timeout_minutes: 30

# ============================================
# API Mode Configuration (only needed when running API server)
# ============================================
api:
  host: 0.0.0.0
  port: 8000
  max_sessions: 10
  idle_timeout_seconds: 1800
  browser_mode: local  # local or docker
"""

        self.config_path.write_text(config_content)


# ── SkillConfig helpers (environment variable / YAML resolution) ──


def _resolve_env_vars(config: dict) -> dict:
    """Recursively resolve ${VAR_NAME} environment variable references."""
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
    """Load YAML configuration file."""
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
    """Override configuration with environment variables."""
    if v := os.getenv("STEALTH_BROWSER_CALLING_MODE"):
        cfg.calling_mode = v
    if v := os.getenv("STEALTH_BROWSER_BROWSER_MODE"):
        cfg.browser_mode = v
    if v := os.getenv("STEALTH_BROWSER_INTELLIGENCE"):
        cfg.intelligence = v
    if v := os.getenv("STEALTH_BROWSER_CDP_URL"):
        cfg.cdp_url = v
    if v := os.getenv("STEALTH_BROWSER_API_URL"):
        cfg.api_url = v
    if v := os.getenv("STEALTH_BROWSER_API_KEY"):
        cfg.api_key = v
    if v := os.getenv("STEALTH_BROWSER_REMOTE_TYPE"):
        cfg.remote_type = v
    if v := os.getenv("STEALTH_BROWSER_VNC_URL"):
        cfg.vnc_url = v
    if v := os.getenv("STEALTH_BROWSER_DAEMON_ENABLED"):
        cfg.daemon_enabled = v.lower() in ("1", "true", "yes")
    if v := os.getenv("STEALTH_BROWSER_DAEMON_IDLE_TIMEOUT"):
        cfg.daemon_idle_timeout = int(v)
    if v := os.getenv("STEALTH_BROWSER_STEALTH_ENABLED"):
        cfg.stealth_enabled = v.lower() in ("1", "true", "yes")
    if (v := os.getenv("STEALTH_BROWSER_STEALTH_MODE")) and v in ("full", "vanilla"):
        cfg.stealth_mode = v
    if v := os.getenv("STEALTH_BROWSER_STEALTH_PROFILE"):
        cfg.stealth_profile = v
    if v := os.getenv("STEALTH_BROWSER_EXTENSION_ENABLED"):
        cfg.extension_enabled = v.lower() in ("1", "true", "yes")
    return cfg


def _apply_yaml_overrides(cfg: SkillConfig, yaml_data: dict) -> SkillConfig:
    """Override configuration from YAML (only non-default values).

    Reads flat keys directly from skill.yaml (no 'skill:' namespace indirection).
    """
    # skill.yaml is a dedicated flat-key file — use yaml_data directly
    skill = yaml_data

    if "calling_mode" in skill:
        cfg.calling_mode = skill["calling_mode"]
    if "browser_mode" in skill:
        cfg.browser_mode = skill["browser_mode"]
    if "remote_type" in skill:
        cfg.remote_type = skill["remote_type"]
    if "intelligence" in skill:
        cfg.intelligence = skill["intelligence"]
    if "cdp_url" in skill:
        cfg.cdp_url = skill["cdp_url"]
    if "api_url" in skill:
        cfg.api_url = skill["api_url"]
    if "api_key" in skill:
        cfg.api_key = skill["api_key"]
    if "vnc_url" in skill:
        cfg.vnc_url = skill["vnc_url"]

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
    if "profile" in stealth:
        cfg.stealth_profile = stealth["profile"]
    if "warmup" in stealth:
        cfg.warmup_enabled = stealth["warmup"]

    extension = skill.get("extension", {})
    if "enabled" in extension:
        cfg.extension_enabled = extension["enabled"]

    return cfg


async def detect_mode() -> SkillConfig:
    """
    Auto-detect operating mode (last resort).

    Precedence: explicit params > env vars > YAML > auto-detection > defaults

    Detection logic:
    1. localhost:8000/health reachable -> API mode
    2. 127.0.0.1:19222/json/version reachable -> CLI mode
    3. Default -> CLI + local
    """
    cfg = SkillConfig()

    # 1. Load YAML config
    config_path = Path.home() / ".stealth-browser" / "skill.yaml"
    yaml_data = _load_yaml_config(config_path)
    if yaml_data:
        cfg = _apply_yaml_overrides(cfg, yaml_data)

    # 2. Environment variable overrides
    cfg = _apply_env_overrides(cfg)

    # 3. Auto-detection (only when no explicit setting exists)
    if not os.getenv("STEALTH_BROWSER_CALLING_MODE") and not yaml_data.get("calling_mode"):
        try:
            import aiohttp

            async with (
                aiohttp.ClientSession() as s,
                s.get(
                    "http://localhost:8000/health",
                    timeout=aiohttp.ClientTimeout(total=1),
                ) as r,
            ):
                if r.status == 200:
                    cfg.calling_mode = "api"
                    cfg.api_url = "http://localhost:8000"
                    logger.info("Auto-detected: API mode (FastAPI reachable)")
                    return cfg
        except Exception:
            pass

        try:
            import aiohttp

            async with (
                aiohttp.ClientSession() as s,
                s.get(
                    "http://127.0.0.1:19222/json/version",
                    timeout=aiohttp.ClientTimeout(total=1),
                ) as r,
            ):
                if r.status == 200:
                    cfg.calling_mode = "cli"
                    cfg.browser_mode = "local"
                    logger.info("Auto-detected: CLI mode (CDP reachable)")
                    return cfg
        except Exception:
            pass

    return cfg


def load_config(**overrides) -> SkillConfig:
    """Synchronous config loading (for scenarios that don't need auto-detection)."""
    cfg = SkillConfig()

    config_path = Path.home() / ".stealth-browser" / "skill.yaml"
    yaml_data = _load_yaml_config(config_path)
    if yaml_data:
        cfg = _apply_yaml_overrides(cfg, yaml_data)

    cfg = _apply_env_overrides(cfg)

    # Explicit parameter overrides
    for k, v in overrides.items():
        if hasattr(cfg, k) and v is not None:
            setattr(cfg, k, v)

    # Constraint: CLI mode does not support remote browser
    if cfg.calling_mode == "cli" and cfg.browser_mode == "remote":
        logger.warning("CLI mode does not support remote browser, falling back to local")
        cfg.browser_mode = "local"

    return cfg


def from_deploy_config(dep_cfg) -> SkillConfig:
    """Merge DeployConfig fields into SkillConfig.

    Converts deployment-level settings (mode, browser type, CDP URL, etc.)
    into the SkillConfig format used by the runtime. Called by setup() after
    loading deploy-config.yaml.

    Mode mapping:
      local              -> cli,  local,  aio,         api_url unchanged, vnc_url=""
      docker-aio         -> api,  remote, aio,         remote_api_url or http://{host}:{port}, dep_cfg.vnc_url
      docker-distributed -> api,  remote, distributed, remote_api_url or http://{host}:{port}, ""
      k8s-aio            -> api,  remote, aio,         remote_api_url or http://{host}:{port}, dep_cfg.vnc_url
      k8s-distributed    -> api,  remote, distributed, remote_api_url or http://{host}:{port}, ""
    """
    cfg = SkillConfig()

    mode = getattr(dep_cfg, "mode", "local") or "local"
    api_host = getattr(dep_cfg, "api_host", "localhost") or "localhost"
    api_port = getattr(dep_cfg, "api_port", 8000) or 8000
    remote_api_url = getattr(dep_cfg, "remote_api_url", "") or ""
    dep_vnc_url = getattr(dep_cfg, "vnc_url", "") or ""

    default_api_url = remote_api_url or f"http://{api_host}:{api_port}"

    if mode == "local":
        cfg.calling_mode = "cli"
        cfg.browser_mode = "local"
        cfg.remote_type = "aio"
        cfg.api_url = default_api_url
        cfg.vnc_url = ""
    elif mode == "docker-aio":
        cfg.calling_mode = "api"
        cfg.browser_mode = "remote"
        cfg.remote_type = "aio"
        cfg.api_url = default_api_url
        cfg.vnc_url = dep_vnc_url
    elif mode == "docker-distributed":
        cfg.calling_mode = "api"
        cfg.browser_mode = "remote"
        cfg.remote_type = "distributed"
        cfg.api_url = default_api_url
        cfg.vnc_url = ""
    elif mode == "k8s-aio":
        cfg.calling_mode = "api"
        cfg.browser_mode = "remote"
        cfg.remote_type = "aio"
        cfg.api_url = default_api_url
        cfg.vnc_url = dep_vnc_url
    elif mode == "k8s-distributed":
        cfg.calling_mode = "api"
        cfg.browser_mode = "remote"
        cfg.remote_type = "distributed"
        cfg.api_url = default_api_url
        cfg.vnc_url = ""
    else:
        # Unknown mode — fall back to local
        cfg.calling_mode = "cli"
        cfg.browser_mode = "local"
        cfg.remote_type = "aio"
        cfg.vnc_url = ""

    # Browser settings
    cdp_url = getattr(dep_cfg, "cdp_url", None)
    if cdp_url:
        cfg.cdp_url = cdp_url

    headless = getattr(dep_cfg, "headless", None)
    if headless is not None:
        cfg.headless = headless

    # Stealth settings
    stealth_enabled = getattr(dep_cfg, "stealth_enabled", None)
    if stealth_enabled is not None:
        cfg.stealth_enabled = stealth_enabled

    stealth_mode = getattr(dep_cfg, "stealth_mode", None)
    if stealth_mode in ("full", "vanilla"):
        cfg.stealth_mode = stealth_mode

    return cfg
