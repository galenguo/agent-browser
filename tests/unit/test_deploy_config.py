"""Tests for deploy_config.py — DeployConfig dataclass, validation, I/O."""

import os
from unittest import mock

from stealth_browser.deploy_config import (
    DeployConfig,
    detect_environment,
    generate_config,
    load_deploy_config,
    validate_config,
)


class TestDeployConfigDataclass:
    """DeployConfig default values and serialization."""

    def test_defaults(self):
        cfg = DeployConfig()
        assert cfg.mode == "local"
        assert cfg.browser_type == "cloakbrowser"
        assert cfg.cdp_url == "http://127.0.0.1:19222"
        assert cfg.headless is False
        assert cfg.api_enabled is True
        assert cfg.api_port == 8000
        assert cfg.stealth_enabled is True
        assert cfg.stealth_mode == "full"

    def test_custom_values(self):
        cfg = DeployConfig(mode="docker-aio", headless=True, api_port=9000)
        assert cfg.mode == "docker-aio"
        assert cfg.headless is True
        assert cfg.api_port == 9000

    def test_to_dict_excludes_empty(self):
        cfg = DeployConfig()  # all defaults
        d = cfg.to_dict()
        # Defaults like mode="local", browser_type="cloakbrowser" should appear
        # but empty/None fields should not
        assert "mode" in d
        assert "browser_type" in d
        assert "k8s_context" not in d  # None by default

    def test_to_dict_includes_set_values(self):
        cfg = DeployConfig(docker_registry="ghcr.io", k8s_context="my-cluster")
        d = cfg.to_dict()
        assert d["docker_registry"] == "ghcr.io"
        assert d["k8s_context"] == "my-cluster"


class TestValidateConfig:
    """validate_config() — returns list of ConfigIssue."""

    def test_valid_local_config(self):
        cfg = DeployConfig(mode="local")
        issues = validate_config(cfg, env_check=False)
        errors = [i for i in issues if i.severity == "error"]
        assert len(errors) == 0

    def test_invalid_mode_rejected(self):
        cfg = DeployConfig(mode="invalid-mode")
        issues = validate_config(cfg, env_check=False)
        modes = [i for i in issues if i.section == "general" and "Invalid deployment mode" in i.message]
        assert len(modes) == 1
        assert modes[0].severity == "error"

    def test_all_valid_modes_accepted(self):
        for mode in ("local", "docker-aio", "docker-distributed", "k8s-aio", "k8s-distributed"):
            cfg = DeployConfig(mode=mode)
            issues = validate_config(cfg, env_check=False)
            mode_errors = [i for i in issues if i.section == "general" and "Invalid" in i.message]
            assert len(mode_errors) == 0, f"Mode {mode} should be valid"

    def test_no_llm_key_is_info_not_error(self):
        """Missing LLM key should be info-level, not error."""
        with mock.patch.dict(os.environ, {}, clear=True):
            # Remove any API keys
            for k in list(os.environ.keys()):
                if "API_KEY" in k or "BASE_URL" in k:
                    del os.environ[k]

            cfg = DeployConfig()
            issues = validate_config(cfg, env_check=True)
            llm_issues = [i for i in issues if i.section == "llm"]
            assert len(llm_issues) >= 1
            assert llm_issues[0].severity == "info"

    def test_cloakbrowser_missing_is_error_with_fix_hint(self):
        """When CloakBrowser not installed and env_check=True, should report error."""
        with mock.patch("builtins.__import__", side_effect=ImportError("No module")):
            cfg = DeployConfig(browser_type="cloakbrowser")
            issues = validate_config(cfg, env_check=True)
            cb_issues = [i for i in issues if i.section == "browser" and "CloakBrowser" in i.message]
            assert len(cb_issues) == 1
            assert cb_issues[0].auto_fixable is True


class TestDetectEnvironment:
    """detect_environment() — OS/arch/tool detection."""

    def test_returns_dict(self):
        env = detect_environment()
        assert isinstance(env, dict)
        assert "os" in env
        assert "arch" in env
        assert "has_docker" in env

    def test_os_detection(self):
        env = detect_environment()
        assert env["os"] in ("darwin", "linux", "win32")

    def test_arch_detection(self):
        env = detect_environment()
        assert env["arch"] in ("amd64", "arm64", "x86_64", "aarch64")


class TestLoadDeployConfig:
    """load_deploy_config() — reads from config.yaml."""

    def test_missing_file_returns_defaults(self, tmp_path):
        """Non-existent file should return defaults without error."""
        with mock.patch("stealth_browser.deploy_config.CONFIG_PATH", tmp_path / "nonexistent.yaml"):
            cfg = load_deploy_config()
            assert isinstance(cfg, DeployConfig)
            assert cfg.mode == "local"

    def test_reads_deployment_section(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("""
deployment:
  mode: docker-aio
  os: linux
  arch: amd64
browser:
  type: cloakbrowser
  cdp_url: "http://127.0.0.1:19222"
""")
        with mock.patch("stealth_browser.deploy_config.CONFIG_PATH", cfg_file):
            cfg = load_deploy_config()
            assert cfg.mode == "docker-aio"
            assert cfg.os == "linux"
            assert cfg.arch == "amd64"

    def test_reads_browser_section(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("""
browser:
  type: chrome
  cdp_url: "http://localhost:9222"
  headless: true
  max_sessions: 5
""")
        with mock.patch("stealth_browser.deploy_config.CONFIG_PATH", cfg_file):
            cfg = load_deploy_config()
            assert cfg.browser_type == "chrome"
            assert cfg.cdp_url == "http://localhost:9222"
            assert cfg.headless is True
            assert cfg.max_sessions == 5

    def test_reads_docker_section(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("""
docker:
  registry: ghcr.io
  image_tag: v2.0
  shm_size: "512Mi"
  resource_limits:
    memory: "4Gi"
    cpu: "4000m"
""")
        with mock.patch("stealth_browser.deploy_config.CONFIG_PATH", cfg_file):
            cfg = load_deploy_config()
            assert cfg.docker_registry == "ghcr.io"
            assert cfg.docker_image_tag == "v2.0"
            assert cfg.docker_shm_size == "512Mi"
            assert cfg.docker_memory_limit == "4Gi"
            assert cfg.docker_cpu_limit == "4000m"

    def test_falls_back_to_defaults_for_missing_sections(self, tmp_path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("deployment:\n  mode: local\n")
        with mock.patch("stealth_browser.deploy_config.CONFIG_PATH", cfg_file):
            cfg = load_deploy_config()
            # Should have defaults for sections not in YAML
            assert cfg.browser_type == "cloakbrowser"  # default
            assert cfg.api_port == 8000  # default


class TestGenerateConfig:
    """generate_config() — writes YAML atomically."""

    def test_writes_valid_yaml(self, tmp_path):
        cfg = DeployConfig(mode="local", os="darwin", arch="arm64")
        target = tmp_path / "test-config.yaml"
        result = generate_config(cfg, path=target)
        assert result == target
        assert target.exists()

        content = target.read_text()
        assert "mode: local" in content
        assert "os: darwin" in content
        assert "arch: arm64" in content

    def test_atomic_write_preserves_existing(self, tmp_path):
        """Writing should preserve existing unrelated keys."""
        existing = tmp_path / "config.yaml"
        existing.write_text("custom_key: preserved\n")
        cfg = DeployConfig(mode="local")
        generate_config(cfg, path=existing)

        content = existing.read_text()
        assert "custom_key: preserved" in content
        assert "mode: local" in content

    def test_writes_all_sections(self, tmp_path):
        cfg = DeployConfig(
            mode="docker-aio",
            browser_type="cloakbrowser",
            docker_registry="ghcr.io",
            proxy_enabled=True,
            proxy_list=["http://proxy:8080"],
        )
        target = tmp_path / "full-config.yaml"
        generate_config(cfg, path=target)
        content = target.read_text()

        assert "deployment:" in content
        assert "browser:" in content
        assert "api:" in content
        assert "stealth:" in content
        assert "docker:" in content
        assert "proxy:" in content

    def test_yaml_roundtrip(self, tmp_path):
        """Write then read should produce equivalent config.

        Note: k8s section is only written for k8s modes; docker section only for
        docker modes. Test uses docker-aio and verifies docker fields.
        """
        original = DeployConfig(
            mode="docker-aio",
            browser_type="playwright",
            headless=True,
            api_port=9000,
            stealth_mode="vanilla",
            docker_memory_limit="8Gi",
        )
        target = tmp_path / "roundtrip.yaml"
        generate_config(original, path=target)

        with mock.patch("stealth_browser.deploy_config.CONFIG_PATH", target):
            loaded = load_deploy_config()

        assert loaded.mode == original.mode
        assert loaded.browser_type == original.browser_type
        assert loaded.headless == original.headless
        assert loaded.api_port == original.api_port
        assert loaded.stealth_mode == original.stealth_mode
        assert loaded.docker_memory_limit == original.docker_memory_limit
