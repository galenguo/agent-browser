"""
Phase 1: 配置系统单元测试

测试目标：
- A1.1 默认配置加载
- A1.2 环境变量覆盖
- A1.3 YAML 配置加载
- A1.4 显式参数优先级
- A1.5 CLI+remote 约束（应降级为 local）
"""

import os
import tempfile
from pathlib import Path
from unittest import mock

# 使用 skill_loader 助手加载模块
from helpers.skill_loader import load_skill_module

config = load_skill_module("config")
SkillConfig = config.SkillConfig
load_config = config.load_config
_apply_env_overrides = config._apply_env_overrides
_apply_yaml_overrides = config._apply_yaml_overrides
_load_yaml_config = config._load_yaml_config
_resolve_env_vars = config._resolve_env_vars


class TestSkillConfigDefaults:
    """A1.1 默认配置测试"""

    def test_default_calling_mode(self):
        """默认 calling_mode 为 cli"""
        cfg = SkillConfig()
        assert cfg.calling_mode == "cli"

    def test_default_browser_mode(self):
        """默认 browser_mode 为 local"""
        cfg = SkillConfig()
        assert cfg.browser_mode == "local"

    def test_default_intelligence(self):
        """默认 intelligence 为 llm"""
        cfg = SkillConfig()
        assert cfg.intelligence == "llm"

    def test_default_cdp_url(self):
        """默认 CDP URL 为 127.0.0.1:19222"""
        cfg = SkillConfig()
        assert cfg.cdp_url == "http://127.0.0.1:19222"

    def test_default_api_url(self):
        """默认 API URL 为 localhost:8000"""
        cfg = SkillConfig()
        assert cfg.api_url == "http://localhost:8000"

    def test_default_daemon_settings(self):
        """默认 daemon 配置"""
        cfg = SkillConfig()
        assert cfg.daemon_enabled is True
        assert cfg.daemon_idle_timeout == 1800
        assert cfg.daemon_state_path == "~/.agent-browser/daemon-state.json"

    def test_default_stealth_settings(self):
        """默认隐匿配置"""
        cfg = SkillConfig()
        assert cfg.stealth_enabled is True
        assert cfg.warmup_enabled is False


class TestEnvOverrides:
    """A1.2 环境变量覆盖测试"""

    def test_env_calling_mode(self):
        """AGENT_BROWSER_CALLING_MODE 环境变量"""
        with mock.patch.dict(os.environ, {"AGENT_BROWSER_CALLING_MODE": "api"}):
            cfg = SkillConfig()
            cfg = _apply_env_overrides(cfg)
            assert cfg.calling_mode == "api"

    def test_env_browser_mode(self):
        """AGENT_BROWSER_BROWSER_MODE 环境变量"""
        with mock.patch.dict(os.environ, {"AGENT_BROWSER_BROWSER_MODE": "remote"}):
            cfg = SkillConfig()
            cfg = _apply_env_overrides(cfg)
            assert cfg.browser_mode == "remote"

    def test_env_intelligence(self):
        """AGENT_BROWSER_INTELLIGENCE 环境变量"""
        with mock.patch.dict(os.environ, {"AGENT_BROWSER_INTELLIGENCE": "agent"}):
            cfg = SkillConfig()
            cfg = _apply_env_overrides(cfg)
            assert cfg.intelligence == "agent"

    def test_env_cdp_url(self):
        """AGENT_BROWSER_CDP_URL 环境变量"""
        with mock.patch.dict(os.environ, {"AGENT_BROWSER_CDP_URL": "http://192.168.1.100:9222"}):
            cfg = SkillConfig()
            cfg = _apply_env_overrides(cfg)
            assert cfg.cdp_url == "http://192.168.1.100:9222"

    def test_env_api_url(self):
        """AGENT_BROWSER_API_URL 环境变量"""
        with mock.patch.dict(os.environ, {"AGENT_BROWSER_API_URL": "http://api.example.com:8080"}):
            cfg = SkillConfig()
            cfg = _apply_env_overrides(cfg)
            assert cfg.api_url == "http://api.example.com:8080"

    def test_env_api_key(self):
        """AGENT_BROWSER_API_KEY 环境变量"""
        with mock.patch.dict(os.environ, {"AGENT_BROWSER_API_KEY": "test-key-123"}):
            cfg = SkillConfig()
            cfg = _apply_env_overrides(cfg)
            assert cfg.api_key == "test-key-123"

    def test_env_daemon_enabled_true(self):
        """AGENT_BROWSER_DAEMON_ENABLED=true"""
        for val in ("1", "true", "yes"):
            with mock.patch.dict(os.environ, {"AGENT_BROWSER_DAEMON_ENABLED": val}):
                cfg = SkillConfig()
                cfg = _apply_env_overrides(cfg)
                assert cfg.daemon_enabled is True

    def test_env_daemon_enabled_false(self):
        """AGENT_BROWSER_DAEMON_ENABLED=false"""
        for val in ("0", "false", "no"):
            with mock.patch.dict(os.environ, {"AGENT_BROWSER_DAEMON_ENABLED": val}):
                cfg = SkillConfig()
                cfg = _apply_env_overrides(cfg)
                assert cfg.daemon_enabled is False

    def test_env_daemon_idle_timeout(self):
        """AGENT_BROWSER_DAEMON_IDLE_TIMEOUT 环境变量"""
        with mock.patch.dict(os.environ, {"AGENT_BROWSER_DAEMON_IDLE_TIMEOUT": "3600"}):
            cfg = SkillConfig()
            cfg = _apply_env_overrides(cfg)
            assert cfg.daemon_idle_timeout == 3600

    def test_env_stealth_enabled(self):
        """AGENT_BROWSER_STEALTH_ENABLED 环境变量"""
        with mock.patch.dict(os.environ, {"AGENT_BROWSER_STEALTH_ENABLED": "false"}):
            cfg = SkillConfig()
            cfg = _apply_env_overrides(cfg)
            assert cfg.stealth_enabled is False


class TestYAMLOverrides:
    """A1.3 YAML 配置加载测试"""

    def test_yaml_skill_settings(self):
        """YAML skill 节配置"""
        yaml_data = {
            "skill": {
                "calling_mode": "api",
                "browser_mode": "remote",
                "intelligence": "agent",
            }
        }
        cfg = SkillConfig()
        cfg = _apply_yaml_overrides(cfg, yaml_data)
        assert cfg.calling_mode == "api"
        assert cfg.browser_mode == "remote"
        assert cfg.intelligence == "agent"

    def test_yaml_daemon_settings(self):
        """YAML daemon 节配置"""
        yaml_data = {
            "daemon": {
                "enabled": False,
                "idle_timeout": 7200,
                "state_path": "/custom/path/state.json",
            }
        }
        cfg = SkillConfig()
        cfg = _apply_yaml_overrides(cfg, {"skill": yaml_data})
        assert cfg.daemon_enabled is False
        assert cfg.daemon_idle_timeout == 7200
        assert cfg.daemon_state_path == "/custom/path/state.json"

    def test_yaml_browser_settings(self):
        """YAML browser 节配置"""
        yaml_data = {
            "browser": {
                "headless": True,
                "default_timeout": 60000,
            }
        }
        cfg = SkillConfig()
        cfg = _apply_yaml_overrides(cfg, {"skill": yaml_data})
        assert cfg.headless is True
        assert cfg.default_timeout == 60000

    def test_yaml_stealth_settings(self):
        """YAML stealth 节配置"""
        yaml_data = {
            "stealth": {
                "enabled": False,
                "warmup": True,
            }
        }
        cfg = SkillConfig()
        cfg = _apply_yaml_overrides(cfg, {"skill": yaml_data})
        assert cfg.stealth_enabled is False
        assert cfg.warmup_enabled is True

    def test_yaml_env_var_resolution(self):
        """YAML 中 ${VAR_NAME} 环境变量解析"""
        with mock.patch.dict(os.environ, {"MY_API_KEY": "secret-key"}):
            resolved = _resolve_env_vars({"api_key": "${MY_API_KEY}"})
            assert resolved["api_key"] == "secret-key"


class TestLoadConfigPriority:
    """A1.4 显式参数优先级测试"""

    def test_explicit_params_override_all(self):
        """显式参数优先级最高"""
        with mock.patch.dict(os.environ, {"AGENT_BROWSER_CALLING_MODE": "api"}):
            cfg = load_config(calling_mode="cli")
            assert cfg.calling_mode == "cli"

    def test_env_overrides_yaml(self):
        """环境变量优先级高于 YAML"""
        yaml_data = {"skill": {"calling_mode": "api"}}
        with mock.patch.dict(os.environ, {"AGENT_BROWSER_CALLING_MODE": "cli"}):
            cfg = SkillConfig()
            cfg = _apply_yaml_overrides(cfg, yaml_data)
            cfg = _apply_env_overrides(cfg)
            assert cfg.calling_mode == "cli"

    def test_yaml_overrides_defaults(self):
        """YAML 优先级高于默认值"""
        yaml_data = {"skill": {"calling_mode": "api"}}
        cfg = SkillConfig()
        cfg = _apply_yaml_overrides(cfg, yaml_data)
        assert cfg.calling_mode == "api"


class TestCLIRemoteConstraint:
    """A1.5 CLI+remote 约束测试"""

    def test_cli_remote_falls_back_to_local(self):
        """CLI 模式不支持 remote 浏览器，应降级为 local"""
        cfg = load_config(calling_mode="cli", browser_mode="remote")
        assert cfg.browser_mode == "local"

    def test_cli_local_remains_local(self):
        """CLI + local 保持不变"""
        cfg = load_config(calling_mode="cli", browser_mode="local")
        assert cfg.browser_mode == "local"

    def test_api_remote_remains_remote(self):
        """API + remote 保持不变"""
        cfg = load_config(calling_mode="api", browser_mode="remote")
        assert cfg.browser_mode == "remote"


class TestLoadYAMLConfig:
    """YAML 配置加载边界测试"""

    def test_missing_file_returns_empty(self):
        """不存在的文件返回空字典"""
        result = _load_yaml_config(Path("/nonexistent/path/config.yaml"))
        assert result == {}

    def test_invalid_yaml_returns_empty(self):
        """无效 YAML 返回空字典"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("invalid: yaml: content: [")
            f.flush()
            try:
                result = _load_yaml_config(Path(f.name))
                assert result == {}
            finally:
                os.unlink(f.name)

    def test_empty_yaml_returns_empty(self):
        """空 YAML 返回空字典"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")
            f.flush()
            try:
                result = _load_yaml_config(Path(f.name))
                assert result == {}
            finally:
                os.unlink(f.name)
