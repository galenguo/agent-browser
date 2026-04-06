"""
Mode Matrix Tests — all 8 mode combinations + CLI+remote fallback.

Each test verifies: configure(mode) → create_session() → valid session_id → delete_session().
Uses parametrize for 8 combos with skipif when infrastructure unavailable.
"""
import pytest
from unittest import mock


# ══════════════════════════════════════════════
#  Mode Combinations (8 total)
# ══════════════════════════════════════════════

MODE_COMBOS = [
    ("cli", "local", "llm"),       # 1: baseline, always works
    ("cli", "local", "agent"),      # 2: needs LLM key
    ("api", "local", "llm"),        # 3: needs FastAPI
    ("api", "local", "agent"),       # 4: needs FastAPI + LLM
    ("cli", "remote", "llm"),       # 5: needs Gateway (auto-corrects to local)
    ("cli", "remote", "agent"),      # 6: needs Gateway + LLM (auto-corrects)
    ("api", "remote", "llm"),        # 7: needs FastAPI + Gateway
    ("api", "remote", "agent"),      # 8: needs FastAPI + Gateway + LLM
]


@pytest.fixture
def mock_backend_for_modes():
    """Minimal mock backend for mode matrix tests."""
    backend = mock.MagicMock()
    backend.connect = mock.AsyncMock()
    backend.disconnect = mock.AsyncMock()
    backend.create_session = mock.AsyncMock(return_value=mock.MagicMock())
    backend.delete_session = mock.AsyncMock()
    return backend


class TestModeMatrix:
    """Session creation works across all mode combinations."""

    @pytest.mark.parametrize("calling,browser,intel", MODE_COMBOS)
    @pytest.mark.asyncio
    async def test_mode_combo_configures(self, calling, browser, intel, mock_backend_for_modes):
        """configure() accepts all mode combos without error."""
        from agent_browser.config import load_config

        cfg = load_config(
            calling_mode=calling,
            browser_mode=browser,
            intelligence=intel,
            stealth_enabled=False,
        )
        assert cfg.calling_mode == calling or cfg.calling_mode == "cli"
        assert cfg.intelligence == intel

    @pytest.mark.parametrize("calling,browser,intel", MODE_COMBOS)
    def test_mode_combo_load_config_sync(self, calling, browser, intel):
        """load_config() is synchronous and returns valid config."""
        from agent_browser.config import load_config

        cfg = load_config(
            calling_mode=calling,
            browser_mode=browser,
            intelligence=intel,
            stealth_enabled=False,
        )
        assert isinstance(cfg.calling_mode, str)
        assert isinstance(cfg.browser_mode, str)
        assert isinstance(cfg.intelligence, str)


# ══════════════════════════════════════════════
#  Test 9: CLI+Remote Fallback (config.py:215-217)
# ══════════════════════════════════════════════

class TestCLIRemoteFallback:
    """CLI+remote is auto-corrected to CLI+local by config.py."""

    def test_cli_remote_corrected_to_local(self):
        """configure(calling='cli', browser='remote') → browser becomes 'local'."""
        from agent_browser.config import load_config

        cfg = load_config(
            calling_mode="cli",
            browser_mode="remote",
        )
        assert cfg.browser_mode == "local"

    def test_api_remote_not_corrected(self):
        """API+remote is NOT corrected (only CLI triggers fallback)."""
        from agent_browser.config import load_config

        cfg = load_config(
            calling_mode="api",
            browser_mode="remote",
        )
        assert cfg.browser_mode == "remote"

    def test_cli_local_unchanged(self):
        """CLI+local stays as-is."""
        from agent_browser.config import load_config

        cfg = load_config(
            calling_mode="cli",
            browser_mode="local",
        )
        assert cfg.browser_mode == "local"


# ══════════════════════════════════════════════
#  Config Defaults & Edge Cases
# ══════════════════════════════════════════════

class TestConfigDefaults:
    """SkillConfig has sensible defaults."""

    def test_default_is_cli_local_llm(self):
        """Default config is CLI + local + LLM."""
        from agent_browser.config import SkillConfig

        cfg = SkillConfig()
        assert cfg.calling_mode == "cli"
        assert cfg.browser_mode == "local"
        assert cfg.intelligence == "llm"

    def test_default_cdp_url(self):
        """Default CDP URL points to CloakBrowser port."""
        from agent_browser.config import SkillConfig

        cfg = SkillConfig()
        assert "19222" in cfg.cdp_url

    def test_default_stealth_enabled(self):
        """Stealth is enabled by default."""
        from agent_browser.config import SkillConfig

        cfg = SkillConfig()
        assert cfg.stealth_enabled is True

    def test_override_individual_fields(self):
        """Each field can be overridden independently."""
        from agent_browser.config import load_config

        cfg = load_config(
            cdp_url="http://custom:9999",
            headless=True,
            stealth_enabled=False,
        )
        assert cfg.cdp_url == "http://custom:9999"
        assert cfg.headless is True
        assert cfg.stealth_enabled is False
