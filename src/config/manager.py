import os
import yaml
from pathlib import Path
from typing import Any, Optional
from dataclasses import dataclass

@dataclass
class LLMConfig:
    provider: str
    model: str
    api_key: Optional[str]
    base_url: Optional[str]
    temperature: float

@dataclass
class BrowserConfig:
    headless: bool
    cdp_port: int
    cloakbrowser_path: str
    default_timeout: int

@dataclass
class APIConfig:
    host: str
    port: int
    max_sessions: int
    idle_timeout_seconds: int
    profile_storage: str
    browser_mode: str

@dataclass
class CLIConfig:
    profile_storage: str
    session_storage: str
    default_max_steps: int
    auto_cleanup: bool
    idle_timeout_minutes: int
    max_sessions: int

class ConfigManager:
    """统一配置管理器"""

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or Path.home() / ".agent-browser" / "config.yaml"
        self._config = self._load_config()

    def _load_config(self) -> dict:
        """加载配置文件，支持环境变量替换"""
        if not self.config_path.exists():
            return self._get_default_config()

        with open(self.config_path) as f:
            config = yaml.safe_load(f)

        return self._resolve_env_vars(config)

    def _resolve_env_vars(self, obj: Any) -> Any:
        """递归解析环境变量引用 ${VAR_NAME}"""
        if isinstance(obj, dict):
            return {k: self._resolve_env_vars(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._resolve_env_vars(item) for item in obj]
        elif isinstance(obj, str) and obj.startswith("${") and obj.endswith("}"):
            var_name = obj[2:-1]
            return os.getenv(var_name)
        return obj

    def _get_default_config(self) -> dict:
        """默认配置"""
        return {
            "llm": {
                "default_provider": "anthropic",
                "openai": {"default_model": "gpt-4", "temperature": 0.1},
                "anthropic": {"default_model": "claude-3-5-sonnet-20241022", "temperature": 0.1}
            },
            "browser": {
                "local": {"headless": False, "cdp_port": 19222},
                "remote": {"enabled": False, "host": None, "port": 19222, "cdp_url": None}
            },
            "cli": {
                "default_max_steps": 10,
                "browser_mode": "local",
                "session": {"storage": "~/.agent-browser/sessions.json", "max_sessions": 5, "idle_timeout_minutes": 30}
            },
            "api": {"host": "0.0.0.0", "port": 8000, "max_sessions": 10, "idle_timeout_seconds": 1800, "browser_mode": "local"}
        }

    def get_llm_config(self, provider: Optional[str] = None, **overrides) -> LLMConfig:
        """获取 LLM 配置，支持参数覆盖"""
        provider = provider or self._config["llm"]["default_provider"]
        llm_cfg = self._config["llm"][provider]

        return LLMConfig(
            provider=provider,
            model=overrides.get("model") or llm_cfg.get("default_model"),
            api_key=overrides.get("api_key") or llm_cfg.get("api_key") or os.getenv(f"{provider.upper()}_API_KEY"),
            base_url=overrides.get("base_url") or llm_cfg.get("base_url") or os.getenv(f"{provider.upper()}_BASE_URL"),
            temperature=overrides.get("temperature") or llm_cfg.get("temperature", 0.1)
        )

    def get_browser_config(self, **overrides) -> BrowserConfig:
        """获取浏览器配置"""
        cfg = self._config.get("browser", {}).get("local", {})
        return BrowserConfig(
            headless=overrides.get("headless", cfg.get("headless", False)),
            cdp_port=overrides.get("cdp_port", cfg.get("cdp_port", 19222)),
            cloakbrowser_path=overrides.get("cloakbrowser_path", "/opt/cloakbrowser/chrome"),
            default_timeout=overrides.get("default_timeout", 30000)
        )

    def get_browser_remote_config(self) -> Optional[dict]:
        """获取远程浏览器配置"""
        remote_cfg = self._config.get("browser", {}).get("remote", {})
        if not remote_cfg.get("enabled"):
            return None
        return {
            "host": remote_cfg.get("host"),
            "port": remote_cfg.get("port", 19222),
            "cdp_url": remote_cfg.get("cdp_url")
        }

    def get_cli_browser_mode(self) -> str:
        """获取 CLI 默认浏览器模式"""
        return self._config.get("cli", {}).get("browser_mode", "local")

    def get_api_config(self) -> APIConfig:
        """获取 API 模式配置"""
        cfg = self._config["api"]
        return APIConfig(
            host=cfg.get("host", "0.0.0.0"),
            port=cfg.get("port", 8000),
            max_sessions=cfg.get("max_sessions", 10),
            idle_timeout_seconds=cfg.get("idle_timeout_seconds", 1800),
            profile_storage=cfg.get("profile_storage", "/data/profiles"),
            browser_mode=cfg.get("browser_mode", "local")
        )

    def get_cli_config(self) -> CLIConfig:
        """获取 CLI 模式配置"""
        cfg = self._config["cli"]
        session_cfg = cfg.get("session", {})
        return CLIConfig(
            profile_storage=cfg.get("profile_storage", "~/.agent-browser/profiles"),
            session_storage=cfg.get("session_storage", "~/.agent-browser/sessions.json"),
            default_max_steps=cfg.get("default_max_steps", 10),
            auto_cleanup=session_cfg.get("auto_cleanup", True),
            idle_timeout_minutes=session_cfg.get("idle_timeout_minutes", 30),
            max_sessions=session_cfg.get("max_sessions", 5)
        )

    def get_execution_mode(self) -> str:
        """获取执行模式"""
        return self._config.get("execution", {}).get("mode", "autonomous")

    def save_config(self):
        """保存配置到文件（带注释）"""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        # 生成带注释的配置文件
        config_content = """# Agent Browser 配置文件
#
# 快速开始：
# 1. 设置 LLM API key（必需）
# 2. 其他配置使用默认值即可
# 3. 高级用户可根据需要调整

# ============================================
# LLM 配置（必需 - CLI 和 API 模式都需要）
# ============================================
llm:
  # 选择 LLM 提供商：openai 或 anthropic
  default_provider: anthropic

  # Anthropic 配置
  anthropic:
    api_key: ${ANTHROPIC_API_KEY}  # 从环境变量读取
    default_model: claude-3-5-sonnet-20241022
    temperature: 0.1

  # OpenAI 配置（或兼容接口，如 glm）
  openai:
    api_key: ${OPENAI_API_KEY}
    default_model: gpt-4
    temperature: 0.1

# ============================================
# 浏览器配置（CLI 和 API 模式共享）
# ============================================
browser:
  # 本地浏览器配置
  local:
    headless: false  # 是否无头模式
    cdp_port: 19222  # CDP 端口

  # 远程浏览器配置（可选）
  remote:
    enabled: false        # 是否启用远程模式
    host: null            # 远程主机，如：192.168.1.100
    port: 19222           # 远程 CDP 端口
    cdp_url: null         # 或直接指定完整 URL

# ============================================
# CLI 模式配置（仅命令行使用时需要）
# ============================================
cli:
  default_max_steps: 10   # 默认最大步骤数
  browser_mode: local     # local（本地）或 remote（远程）

  # Session 管理
  session:
    storage: ~/.agent-browser/sessions.json
    max_sessions: 5
    idle_timeout_minutes: 30

# ============================================
# API 模式配置（仅运行 API 服务时需要）
# ============================================
api:
  host: 0.0.0.0
  port: 8000
  max_sessions: 10
  idle_timeout_seconds: 1800
  browser_mode: local  # local 或 docker
"""

        self.config_path.write_text(config_content)

