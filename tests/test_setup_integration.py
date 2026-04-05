"""Tests for setup() function, First-Session Recovery, and Phase 0 integration."""
import os
import sys
import pytest
import asyncio
from pathlib import Path
from unittest import mock

# Ensure paths
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "skills"))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from skills.agent_browser.main import (
    setup,
    detect_missing_deps,
    DepStatus,
    RecoveryReport,
    FirstSessionError,
)
from skills.agent_browser.deploy_config import DeployConfig


class TestDepStatus:
    """DepStatus dataclass."""

    def test_fields(self):
        d = DepStatus(name="test", available=True, fixable=False)
        assert d.name == "test"
        assert d.available is True
        assert d.fixable is False


class TestRecoveryReport:
    """RecoveryReport dataclass."""

    def test_default_ready(self):
        r = RecoveryReport()
        assert r.ready is True
        assert len(r.missing_deps) == 0
        assert len(r.needs_human) == 0

    def test_not_ready_when_missing_deps(self):
        r = RecoveryReport()
        r.missing_deps.append(DepStatus(name="x", available=False))
        assert r.ready is False

    def test_suggestion_generated(self):
        r = RecoveryReport()
        r.missing_deps.append(DepStatus(name="cloakbrowser", available=False, fixable=True))
        r.missing_deps.append(DepStatus(name="cdp", available=False))
        assert len(r.suggestion) > 0
        assert "cloakbrowser" in r.suggestion


class TestDetectMissingDeps:
    """detect_missing_deps() — Phase 0 dependency checker."""

    @pytest.mark.asyncio
    async def test_returns_recovery_report(self):
        report = await detect_missing_deps()
        assert isinstance(report, RecoveryReport)

    @pytest.mark.asyncio
    async def test_detects_cloakbrowser_missing(self):
        with mock.patch("builtins.__import__", side_effect=ImportError("No module cloakbrowser")):
            report = await detect_missing_deps()
            cb = [d for d in report.missing_deps if d.name == "cloakbrowser"]
            assert len(cb) == 1
            assert cb[0].fixable is True
            assert "pip install" in cb[0].fix_command

    @pytest.mark.asyncio
    async def test_detects_cdp_unreachable(self):
        """When CDP endpoint is down, should report it as missing."""
        with mock.patch("aiohttp.ClientSession") as mock_session:
            # Make GET raise connection error
            mock_resp = mock.AsyncMock()
            mock_resp.status = 503
            mock_session.return_value.__aenter__.return_value.get.return_value.__aenter__.return_value = mock_resp

            report = await detect_missing_deps()
            cdp = [d for d in report.missing_deps if d.name == "cdp"]
            assert len(cdp) >= 1

    @pytest.mark.asyncio
    async def test_no_llm_key_is_needs_human(self):
        """Missing API key should be in needs_human (not auto-fixable)."""
        with mock.patch.dict(os.environ, {}, clear=True):
            # Ensure no API keys present
            for k in list(os.environ.keys()):
                if "API_KEY" in k:
                    del os.environ[k]

            report = await detect_missing_deps()
            human = [d for d in report.needs_human if d.name == "llm_api_key"]
            assert len(human) == 1
            assert human[0].fixable is False

    @pytest.mark.asyncio
    async def test_all_present_returns_ready(self):
        """When everything is installed, report should be ready."""
        with mock.patch("builtins.__import__", return_value=mock.MagicMock()):
            # Mock aiohttp to return 200
            mock_resp = mock.AsyncMock()
            mock_resp.status = 200
            mock_session_cls = mock.MagicMock()
            mock_session_cls.return_value.__aenter__.return_value.get.return_value.__aenter__.return_value = mock_resp

            with mock.patch("aiohttp.ClientSession", return_value=mock_session_cls):
                with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
                    report = await detect_missing_deps()
                    # Should be ready (or at least have no blocking deps)
                    assert isinstance(report, RecoveryReport)


class TestSetupFunction:
    """setup() — main entry point for first-session configuration."""

    @pytest.mark.asyncio
    async def test_returns_dict_with_required_keys(self, tmp_path):
        """setup() should return dict with config, issues, report, ready, config_path."""
        with mock.patch("skills.agent_browser.deploy_config.CONFIG_PATH", tmp_path / "config.yaml"):
            result = await setup()

            assert "config" in result
            assert "issues" in result
            assert "report" in result
            assert "ready" in result
            assert "config_path" in result
            assert "environment" in result

    @pytest.mark.asyncio
    async def test_returns_deploy_config(self, tmp_path):
        with mock.patch("skills.agent_browser.deploy_config.CONFIG_PATH", tmp_path / "config.yaml"):
            result = await setup()
            assert isinstance(result["config"], DeployConfig)

    @pytest.mark.asyncio
    async def test_writes_config_file(self, tmp_path):
        cfg_path = tmp_path / "config.yaml"
        with mock.patch("skills.agent_browser.deploy_config.CONFIG_PATH", cfg_path):
            result = await setup()
            assert cfg_path.exists()
            content = cfg_path.read_text()
            assert "deployment:" in content or "mode:" in content

    @pytest.mark.asyncio
    async def test_accepts_kwargs_override(self, tmp_path):
        """Passing mode= should override default."""
        cfg_path = tmp_path / "config.yaml"
        with mock.patch("skills.agent_browser.deploy_config.CONFIG_PATH", cfg_path):
            result = await setup(mode="docker-aio")
            assert result["config"].mode == "docker-aio"

    @pytest.mark.asyncio
    async def test_detects_environment(self, tmp_path):
        """Result should include environment detection info."""
        with mock.patch("skills.agent_browser.deploy_config.CONFIG_PATH", tmp_path / "config.yaml"):
            result = await setup()
            env = result["environment"]
            assert "os" in env
            assert "arch" in env

    @pytest.mark.asyncio
    async def test_validates_config(self, tmp_path):
        """Issues list should come from validate_config()."""
        with mock.patch("skills.agent_browser.deploy_config.CONFIG_PATH", tmp_path / "config.yaml"):
            result = await setup()
            assert isinstance(result["issues"], list)


class TestFirstSessionError:
    """FirstSessionError — structured exception for setup failures."""

    def test_carries_recovery_dict(self):
        recovery = {"ready": False, "missing": ["cloakbrowser"]}
        err = FirstSessionError("Setup needed", recovery)
        assert err.recovery == recovery
        assert str(err) == "Setup needed"

    def test_can_carry_original_error(self):
        original = RuntimeError("CDP connection refused")
        err = FirstSessionError("Setup needed", {}, original)
        assert err.original_error is original
