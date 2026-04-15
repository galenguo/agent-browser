"""Unit tests for StealthProfile system (stealth/profiles.py)."""

import os
from unittest import mock

import pytest

from agent_browser.stealth.profiles import (
    BALANCED_PROFILE,
    BUILTIN_PROFILES,
    FULL_PROFILE,
    MINIMAL_PROFILE,
    OFF_PROFILE,
    StealthProfile,
    profile_from_env,
    resolve_stealth_profile,
)


class TestBuiltinProfiles:
    def test_all_four_profiles_exist(self):
        assert set(BUILTIN_PROFILES.keys()) == {"full", "balanced", "minimal", "off"}

    def test_minimal_profile_mouse_steps(self):
        assert MINIMAL_PROFILE.mouse_move_steps == 3

    def test_minimal_profile_typing_range(self):
        assert MINIMAL_PROFILE.typing_delay_range == (20, 30)

    def test_minimal_profile_typo_probability(self):
        assert MINIMAL_PROFILE.typo_probability == 0.01

    def test_minimal_profile_long_pause_probability(self):
        assert MINIMAL_PROFILE.long_pause_probability == 0.01

    def test_minimal_profile_warmup_enabled(self):
        assert MINIMAL_PROFILE.warmup_enabled is True

    def test_minimal_profile_human_scroll_enabled(self):
        assert MINIMAL_PROFILE.human_scroll_enabled is True

    def test_off_profile_all_delays_zero(self):
        for action, (lo, hi) in OFF_PROFILE.delay_map.items():
            assert lo == 0.0 and hi == 0.0, f"{action} delay should be zero in off profile"

    def test_off_profile_features_disabled(self):
        assert OFF_PROFILE.mouse_move_enabled is False
        assert OFF_PROFILE.human_type_enabled is False
        assert OFF_PROFILE.warmup_enabled is False

    def test_full_profile_has_nonzero_delays(self):
        assert FULL_PROFILE.delay_map["navigate"][1] > 0

    def test_profiles_are_immutable(self):
        with pytest.raises((AttributeError, TypeError)):
            MINIMAL_PROFILE.name = "hacked"  # type: ignore[misc]


class TestResolveStealthProfile:
    def test_resolve_full(self):
        assert resolve_stealth_profile("full") is FULL_PROFILE

    def test_resolve_balanced(self):
        assert resolve_stealth_profile("balanced") is BALANCED_PROFILE

    def test_resolve_minimal(self):
        assert resolve_stealth_profile("minimal") is MINIMAL_PROFILE

    def test_resolve_off(self):
        assert resolve_stealth_profile("off") is OFF_PROFILE

    def test_resolve_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown stealth profile"):
            resolve_stealth_profile("nonexistent")

    def test_resolve_unknown_lists_available(self):
        with pytest.raises(ValueError, match="balanced"):
            resolve_stealth_profile("bad")


class TestProfileFromEnv:
    def test_default_is_minimal(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AGENT_BROWSER_STEALTH_PROFILE", None)
            profile = profile_from_env()
        assert profile is MINIMAL_PROFILE

    def test_env_full(self):
        with mock.patch.dict(os.environ, {"AGENT_BROWSER_STEALTH_PROFILE": "full"}):
            assert profile_from_env() is FULL_PROFILE

    def test_env_off(self):
        with mock.patch.dict(os.environ, {"AGENT_BROWSER_STEALTH_PROFILE": "off"}):
            assert profile_from_env() is OFF_PROFILE

    def test_env_unknown_falls_back_to_full(self):
        with mock.patch.dict(os.environ, {"AGENT_BROWSER_STEALTH_PROFILE": "bogus"}):
            profile = profile_from_env()
        assert profile is FULL_PROFILE

    def test_env_unknown_logs_warning(self, caplog):
        import logging
        with caplog.at_level(logging.WARNING, logger="agent_browser.stealth.profiles"):
            with mock.patch.dict(os.environ, {"AGENT_BROWSER_STEALTH_PROFILE": "bogus"}):
                profile_from_env()
        assert "bogus" in caplog.text
