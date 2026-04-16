"""CLI session cache and intervention commands tests."""

import json
from unittest import mock

from agent_browser.skill.cli import (
    _del_session_id,
    _get_session_id,
    _get_vnc_url,
    _load_session_cache,
    _save_session_cache,
    _set_session_id,
)


class TestSessionCacheMigration:
    """Legacy str format is auto-migrated to dict format."""

    def test_load_legacy_str_format(self, tmp_path):
        cache_file = tmp_path / "skill-session.json"
        cache_file.write_text(json.dumps({"default": "sid-123"}))
        with mock.patch("agent_browser.skill.cli.SESSION_CACHE", cache_file):
            cache = _load_session_cache()
            assert cache["default"] == {"session_id": "sid-123", "vnc_url": ""}

    def test_load_new_dict_format(self, tmp_path):
        cache_file = tmp_path / "skill-session.json"
        cache_file.write_text(json.dumps({
            "default": {"session_id": "sid-456", "vnc_url": "https://vnc.example.com/vnc.html"}
        }))
        with mock.patch("agent_browser.skill.cli.SESSION_CACHE", cache_file):
            cache = _load_session_cache()
            assert cache["default"]["session_id"] == "sid-456"
            assert cache["default"]["vnc_url"] == "https://vnc.example.com/vnc.html"

    def test_load_empty_cache(self, tmp_path):
        cache_file = tmp_path / "nonexistent.json"
        with mock.patch("agent_browser.skill.cli.SESSION_CACHE", cache_file):
            cache = _load_session_cache()
            assert cache == {}


class TestSessionIdOperations:
    """get/set/del session_id with VNC URL storage."""

    def test_set_and_get_session_id(self, tmp_path):
        cache_file = tmp_path / "skill-session.json"
        with mock.patch("agent_browser.skill.cli.SESSION_CACHE", cache_file):
            _set_session_id("default", "sid-abc", vnc_url="https://vnc.example.com/vnc.html")
            assert _get_session_id("default") == "sid-abc"

    def test_set_and_get_vnc_url(self, tmp_path):
        cache_file = tmp_path / "skill-session.json"
        with mock.patch("agent_browser.skill.cli.SESSION_CACHE", cache_file):
            _set_session_id("default", "sid-abc", vnc_url="https://vnc.example.com/vnc.html")
            assert _get_vnc_url("default") == "https://vnc.example.com/vnc.html"

    def test_get_vnc_url_empty_string(self, tmp_path):
        cache_file = tmp_path / "skill-session.json"
        with mock.patch("agent_browser.skill.cli.SESSION_CACHE", cache_file):
            _set_session_id("default", "sid-abc", vnc_url="")
            assert _get_vnc_url("default") is None

    def test_get_vnc_url_no_entry(self, tmp_path):
        cache_file = tmp_path / "skill-session.json"
        with mock.patch("agent_browser.skill.cli.SESSION_CACHE", cache_file):
            assert _get_vnc_url("nonexistent") is None

    def test_get_session_id_no_entry(self, tmp_path):
        cache_file = tmp_path / "skill-session.json"
        with mock.patch("agent_browser.skill.cli.SESSION_CACHE", cache_file):
            assert _get_session_id("nonexistent") is None

    def test_del_session_id(self, tmp_path):
        cache_file = tmp_path / "skill-session.json"
        with mock.patch("agent_browser.skill.cli.SESSION_CACHE", cache_file):
            _set_session_id("default", "sid-abc", vnc_url="https://vnc.example.com")
            _del_session_id("default")
            assert _get_session_id("default") is None
            assert _get_vnc_url("default") is None

    def test_set_without_vnc_url(self, tmp_path):
        cache_file = tmp_path / "skill-session.json"
        with mock.patch("agent_browser.skill.cli.SESSION_CACHE", cache_file):
            _set_session_id("default", "sid-abc")
            assert _get_session_id("default") == "sid-abc"
            assert _get_vnc_url("default") is None

    def test_multiple_sessions(self, tmp_path):
        cache_file = tmp_path / "skill-session.json"
        with mock.patch("agent_browser.skill.cli.SESSION_CACHE", cache_file):
            _set_session_id("default", "sid-1", vnc_url="https://vnc1.example.com")
            _set_session_id("work", "sid-2", vnc_url="https://vnc2.example.com")
            assert _get_session_id("default") == "sid-1"
            assert _get_vnc_url("default") == "https://vnc1.example.com"
            assert _get_session_id("work") == "sid-2"
            assert _get_vnc_url("work") == "https://vnc2.example.com"

    def test_name_defaults_to_default(self, tmp_path):
        cache_file = tmp_path / "skill-session.json"
        with mock.patch("agent_browser.skill.cli.SESSION_CACHE", cache_file):
            _set_session_id(None, "sid-xyz", vnc_url="https://vnc.example.com")
            assert _get_session_id(None) == "sid-xyz"
            assert _get_vnc_url(None) == "https://vnc.example.com"

    def test_legacy_cache_get_session_id(self, tmp_path):
        """Reading session_id from old-format cache works."""
        cache_file = tmp_path / "skill-session.json"
        cache_file.write_text(json.dumps({"default": "sid-legacy"}))
        with mock.patch("agent_browser.skill.cli.SESSION_CACHE", cache_file):
            assert _get_session_id("default") == "sid-legacy"

    def test_overwrite_session(self, tmp_path):
        cache_file = tmp_path / "skill-session.json"
        with mock.patch("agent_browser.skill.cli.SESSION_CACHE", cache_file):
            _set_session_id("default", "sid-1", vnc_url="https://old.example.com")
            _set_session_id("default", "sid-2", vnc_url="https://new.example.com")
            assert _get_session_id("default") == "sid-2"
            assert _get_vnc_url("default") == "https://new.example.com"
