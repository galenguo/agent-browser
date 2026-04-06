"""Tests for extended config.yaml integration — precedence chain, DeployConfig→SkillConfig merge."""
import os
from unittest import mock

from agent_browser.config import from_deploy_config, load_config
from agent_browser.deploy_config import DeployConfig, load_deploy_config


class TestFromDeployConfig:
    """from_deploy_config() — merges DeployConfig into SkillConfig."""

    def test_local_mode_maps_to_cli(self):
        dep = DeployConfig(mode="local")
        cfg = from_deploy_config(dep)
        assert cfg.calling_mode == "cli"

    def test_docker_mode_maps_to_api(self):
        dep = DeployConfig(mode="docker-aio")
        cfg = from_deploy_config(dep)
        assert cfg.calling_mode == "api"

    def test_k8s_mode_maps_to_api(self):
        dep = DeployConfig(mode="k8s-aio")
        cfg = from_deploy_config(dep)
        assert cfg.calling_mode == "api"

    def test_cdp_url_transferred(self):
        dep = DeployConfig(cdp_url="http://localhost:9222")
        cfg = from_deploy_config(dep)
        assert cfg.cdp_url == "http://localhost:9222"

    def test_headless_transferred(self):
        dep = DeployConfig(headless=True)
        cfg = from_deploy_config(dep)
        assert cfg.headless is True

    def test_api_port_creates_api_url(self):
        dep = DeployConfig(api_port=9000)
        cfg = from_deploy_config(dep)
        assert "9000" in cfg.api_url

    def test_stealth_settings_transferred(self):
        dep = DeployConfig(stealth_enabled=False, stealth_mode="vanilla")
        cfg = from_deploy_config(dep)
        assert cfg.stealth_enabled is False
        assert cfg.stealth_mode == "vanilla"

    def test_default_skillconfig_preserved_for_unset_fields(self):
        """Fields not set in DeployConfig should keep SkillConfig defaults."""
        dep = DeployConfig()  # all defaults
        cfg = from_deploy_config(dep)
        # Default SkillConfig values should remain
        assert cfg.intelligence == "llm"
        assert cfg.daemon_enabled is True


class TestPrecedenceChain:
    """Config precedence: explicit params > env vars > YAML > auto-detect > defaults."""

    def test_explicit_params_override_yaml(self, tmp_path):
        """Explicit kwargs should win over YAML."""
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("""
skill:
  calling_mode: api
  cdp_url: "http://localhost:9222"
""")
        with mock.patch("agent_browser.config.Path.home", return_value=tmp_path):
            cfg = load_config(calling_mode="cli", cdp_url="http://127.0.0.1:19222")
            assert cfg.calling_mode == "cli"
            assert cfg.cdp_url == "http://127.0.0.1:19222"

    def test_env_vars_override_yaml(self, tmp_path):
        """Environment variables should override YAML."""
        cfg_file = tmp_path / ".agent-browser" / "config.yaml"
        cfg_file.parent.mkdir(exist_ok=True)
        cfg_file.write_text("""
skill:
  calling_mode: cli
""")

        with mock.patch.dict(os.environ, {"AGENT_BROWSER_CALLING_MODE": "api"}), \
             mock.patch("agent_browser.config.Path.home", return_value=cfg_file.parent.parent):
                cfg = load_config()
                assert cfg.calling_mode == "api"

    def test_yaml_overrides_defaults(self, tmp_path):
        """YAML config should override hardcoded defaults."""
        cfg_file = tmp_path / ".agent-browser" / "config.yaml"
        cfg_file.parent.mkdir(exist_ok=True)
        cfg_file.write_text("""
skill:
  calling_mode: api
  browser_mode: remote
  intelligence: agent
""")
        with mock.patch("agent_browser.config.Path.home", return_value=cfg_file.parent.parent):
            cfg = load_config()
            assert cfg.calling_mode == "api"
            assert cfg.intelligence == "agent"


class TestExtendedYAMLSections:
    """New deployment/docker/k8s/proxy sections in config.yaml don't break existing loading."""

    def test_full_extended_yaml_loads_without_error(self, tmp_path):
        """A config.yaml with all new sections should not break existing load_config()."""
        cfg_file = tmp_path / ".agent-browser" / "config.yaml"
        cfg_file.parent.mkdir(exist_ok=True)
        cfg_file.write_text("""
skill:
  calling_mode: cli
  browser_mode: local

deployment:
  mode: local
  os: darwin
  arch: arm64

browser:
  type: cloakbrowser
  cdp_url: "http://127.0.0.1:19222"
  headless: false

api:
  enabled: true
  port: 8000

stealth:
  enabled: true
  mode: full

docker:
  registry: ghcr.io
  image_tag: latest
  resource_limits:
    memory: "2Gi"
    cpu: "2000m"

k8s:
  namespace: agent-browser
  replicas: 1

proxy:
  enabled: false
  list: []
""")
        with mock.patch("agent_browser.config.Path.home", return_value=cfg_file.parent.parent):
            # Should not raise
            cfg = load_config()
            assert cfg.calling_mode == "cli"

    def test_new_sections_loaded_by_deploy_config(self, tmp_path):
        """DeployConfig should read new sections that SkillConfig ignores."""
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("""
deployment:
  mode: docker-aio
docker:
  registry: ghcr.io/myorg
  resource_limits:
    memory: "8Gi"
k8s:
  namespace: production
  replicas: 3
""")
        with mock.patch("agent_browser.deploy_config.CONFIG_PATH", cfg_file):
            dep = load_deploy_config()
            assert dep.mode == "docker-aio"
            assert dep.docker_registry == "ghcr.io/myorg"
            assert dep.docker_memory_limit == "8Gi"
            assert dep.k8s_namespace == "production"
            assert dep.k8s_replicas == 3

    def test_missing_new_sections_use_defaults(self, tmp_path):
        """If new sections are missing, use DeployConfig defaults."""
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("deployment:\n  mode: local\n")
        with mock.patch("agent_browser.deploy_config.CONFIG_PATH", cfg_file):
            dep = load_deploy_config()
            assert dep.docker_registry is None  # default
            assert dep.k8s_replicas == 1  # default
            assert dep.proxy_enabled is False  # default


class TestBackwardCompatibility:
    """Existing config.yaml without new sections still works."""

    def test_old_format_still_works(self, tmp_path):
        """Pre-existing config.yaml (no deployment/docker/k8s) loads fine."""
        cfg_file = tmp_path / ".agent-browser" / "config.yaml"
        cfg_file.parent.mkdir(exist_ok=True)
        cfg_file.write_text("""
skill:
  calling_mode: cli
  browser_mode: local
  intelligence: llm
""")
        with mock.patch("agent_browser.config.Path.home", return_value=cfg_file.parent.parent):
            cfg = load_config()
            assert cfg.calling_mode == "cli"
