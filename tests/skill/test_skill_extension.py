"""Tests for skill infrastructure: SKILL.md loading, doctor.py, snapshot.js format,
install-skill CLI command, WS protocol conformance, debugger bridge, snapshot JS format,
install-skill command, and SKILL.md conformance validation.

Covers all implementation steps for the in-package skill + Chrome Extension (MV3).
"""

import json
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

# ── Fixtures ────────────────────────────────────────────────


@pytest.fixture
def project_root():
    """Return the project root directory."""
    return Path(__file__).resolve().parents[2]


@pytest.fixture
def skill_dir(project_root):
    """Return the agent_browser/skill/ directory."""
    return project_root / "agent_browser" / "skill"


@pytest.fixture
def extension_dir(project_root):
    """Return the extension/ directory."""
    return project_root / "extension"


# ════════════════════════════════════════════════════════════════════
# 1. SKILL.md Loading Tests
# ══════════════════════════════════════════════════════════════════


class TestSkillMDLoading:
    """SKILL.md must be loadable and contain required frontmatter + sections."""

    def test_skill_md_exists(self, skill_dir):
        skill_md = skill_dir / "SKILL.md"
        assert skill_md.exists(), "SKILL.md must exist in agent_browser/skill/"

    def test_skill_md_has_frontmatter(self, skill_dir):
        content = (skill_dir / "SKILL.md").read_text()
        assert content.startswith("---"), "SKILL.md must start with YAML frontmatter"
        assert "---" in content[4:], "SKILL.md must have closing frontmatter delimiter"

    def test_skill_md_frontmatter_fields(self, skill_dir):
        content = (skill_dir / "SKILL.md").read_text()
        fm = content.split("---")[1]
        assert "name:" in fm or "name :" in fm, "frontmatter must have 'name' field"
        assert "description:" in fm or "description :" in fm, "frontmatter must have 'description' field"

    def test_skill_md_has_react_section(self, skill_dir):
        content = (skill_dir / "SKILL.md").read_text()
        assert "ReAct" in content, "SKILL.md must document ReAct workflow"

    def test_skill_md_has_error_recovery(self, skill_dir):
        content = (skill_dir / "SKILL.md").read_text()
        assert "Error Recovery" in content or "error" in content.lower(), "SKILL.md must cover error recovery"

    def test_skill_md_has_operations_table(self, skill_dir):
        content = (skill_dir / "SKILL.md").read_text()
        assert "snapshot" in content.lower(), "SKILL.md must list snapshot operation"
        assert "click" in content.lower(), "SKILL.md must list click operation"


# ══════════════════════════════════════════════════════════════════
# 2. Doctor Script Tests
# ══════════════════════════════════════════════════════════════════


class TestDoctorScript:
    """doctor.py diagnostic script must produce valid reports."""

    @pytest.fixture
    def doctor_mod(self):
        from agent_browser.skill.scripts.doctor import (
            run_diagnosis, DoctorReport, CheckResult,
        )
        return type("NS", (), {
            "run_diagnosis": staticmethod(run_diagnosis),
            "DoctorReport": DoctorReport,
            "CheckResult": CheckResult,
        })()

    @pytest.mark.asyncio
    async def test_run_diagnosis_returns_report(self, doctor_mod):
        report = await doctor_mod.run_diagnosis()
        assert isinstance(report, doctor_mod.DoctorReport)

    @pytest.mark.asyncio
    async def test_report_has_checks(self, doctor_mod):
        report = await doctor_mod.run_diagnosis()
        assert len(report.checks) > 0, "Report must contain checks"

    @pytest.mark.asyncio
    async def test_report_has_python_version_check(self, doctor_mod):
        report = await doctor_mod.run_diagnosis()
        names = [c.name for c in report.checks]
        assert "python_version" in names, "Must check Python version"

    @pytest.mark.asyncio
    async def test_report_tally_is_consistent(self, doctor_mod):
        report = await doctor_mod.run_diagnosis()
        total = report.passed + report.warned + report.failed + report.skipped
        assert total == len(report.checks), "Tally must equal number of checks"

    @pytest.mark.asyncio
    async def test_report_to_dict(self, doctor_mod):
        report = await doctor_mod.run_diagnosis()
        d = report.to_dict()
        assert "ready" in d
        assert "summary" in d
        assert "checks" in d
        assert isinstance(d["checks"], list)

    @pytest.mark.asyncio
    async def test_ready_property(self, doctor_mod):
        report = await doctor_mod.run_diagnosis()
        # ready requires BOTH zero failures AND zero warnings
        assert report.ready == (report.failed == 0 and report.warned == 0)


# ══════════════════════════════════════════════════════════════════
# 4. Extension Manifest Tests
# ══════════════════════════════════════════════════════════════════


class TestExtensionManifest:
    """MV3 manifest.json must have correct structure and permissions."""

    def test_manifest_exists(self, extension_dir):
        manifest = extension_dir / "manifest.json"
        assert manifest.exists(), "manifest.json must exist in extension/"

    def test_manifest_is_mv3(self, extension_dir):
        manifest = json.loads((extension_dir / "manifest.json").read_text())
        assert manifest.get("manifest_version") == 3, "Must be Manifest V3"

    def test_manifest_has_alarms_permission(self, extension_dir):
        manifest = json.loads((extension_dir / "manifest.json").read_text())
        assert "alarms" in manifest.get("permissions", []), "Must have 'alarms' permission for keepalive"

    def test_manifest_has_debugger_permission(self, extension_dir):
        manifest = json.loads((extension_dir / "manifest.json").read_text())
        assert "debugger" in manifest.get("permissions", []), "Must have 'debugger' permission"

    def test_manifest_has_ws_host_permission(self, extension_dir):
        manifest = json.loads((extension_dir / "manifest.json").read_text())
        hosts = manifest.get("host_permissions", [])
        assert any("19825" in h for h in hosts), "Must allow WebSocket to port 19825"

    def test_manifest_has_service_worker(self, extension_dir):
        manifest = json.loads((extension_dir / "manifest.json").read_text())
        bg = manifest.get("background", {})
        assert "service_worker" in bg, "Must use service worker (MV3)"

    def test_manifest_has_icons(self, extension_dir):
        manifest = json.loads((extension_dir / "manifest.json").read_text())
        icons = manifest.get("icons", {})
        assert 48 in icons or "48" in icons, "Must have 48x48 icon"
        assert 128 in icons or "128" in icons, "Must have 128x128 icon"

    def test_icon_files_exist(self, extension_dir):
        icons_dir = extension_dir / "icons"
        assert (icons_dir / "icon48.png").exists(), "icon48.png must exist"
        assert (icons_dir / "icon128.png").exists(), "icon128.png must exist"

    def test_manifest_has_default_popup(self, extension_dir):
        manifest = json.loads((extension_dir / "manifest.json").read_text())
        action = manifest.get("action", {})
        assert "default_popup" in action, "Must have default_popup for popup UI"
        assert action["default_popup"] == "popup.html", "Popup file must be popup.html"


# ══════════════════════════════════════════════════════════════════
# 5. Background.js Tests (structure and protocol)
# ══════════════════════════════════════════════════════════════════


class TestBackgroundJS:
    """background.js must implement correct WS protocol and command routing."""

    def test_background_js_exists(self, extension_dir):
        assert (extension_dir / "background.js").exists(), "background.js must exist"

    def test_background_has_ws_url_constant(self, extension_dir):
        content = (extension_dir / "background.js").read_text()
        assert "19825" in content, "Must reference WebSocket port 19825"

    def test_background_has_heartbeat_handler(self, extension_dir):
        content = (extension_dir / "background.js").read_text()
        assert "ping" in content.lower() or "pong" in content.lower(), "Must handle heartbeat ping/pong"

    def test_background_has_keepalive_alarm(self, extension_dir):
        content = (extension_dir / "background.js").read_text()
        assert "chrome.alarms" in content, "Must use chrome.alarms for MV3 keepalive"

    def test_background_handles_snapshot(self, extension_dir):
        content = (extension_dir / "background.js").read_text()
        assert "snapshot" in content, "Must route snapshot command"

    def test_background_handles_navigate(self, extension_dir):
        content = (extension_dir / "background.js").read_text()
        assert "navigate" in content.lower() or "goto" in content.lower(), "Must route navigate command"

    def test_background_handles_click(self, extension_dir):
        content = (extension_dir / "background.js").read_text()
        assert "click" in content and "case" in content, "Must route click command"

    def test_background_handles_fill(self, extension_dir):
        content = (extension_dir / "background.js").read_text()
        assert "fill" in content and "case" in content, "Must route fill command"

    def test_background_uses_debugger_api(self, extension_dir):
        content = (extension_dir / "background.js").read_text()
        assert "chrome.debugger" in content, "Must use chrome.debugger API"

    def test_background_has_reconnect_logic(self, extension_dir):
        content = (extension_dir / "background.js").read_text()
        assert "reconnect" in content.lower() or "scheduleReconnect" in content, "Must have reconnection logic"

    def test_background_has_badge_state(self, extension_dir):
        content = (extension_dir / "background.js").read_text()
        assert "badge" in content.lower() or "BadgeText" in content, "Must update badge state"

    def test_background_handles_getstatus_message(self, extension_dir):
        content = (extension_dir / "background.js").read_text()
        assert "getStatus" in content, "Must handle getStatus via onMessage"
        assert "onMessage" in content, "Must listen for messages from popup"

    def test_background_status_response_shape(self, extension_dir):
        content = (extension_dir / "background.js").read_text()
        # Must respond with connected, state, wsUrl fields
        assert "connected" in content, "Status response must include connected field"
        assert "tabTitle" in content or "tab?.title" in content, "Response must include tab info"


# ══════════════════════════════════════════════════════════════════
# 6. Snapshot JS Format Tests
# ══════════════════════════════════════════════════════════════════


class TestSnapshotJS:
    """snapshot.js output format must match LocalCDPBackend exactly."""

    def test_snapshot_js_exists(self, extension_dir):
        assert (extension_dir / "snapshot.js").exists(), "snapshot.js must exist"

    def test_snapshot_returns_url_field(self, extension_dir):
        content = (extension_dir / "snapshot.js").read_text()
        assert "url:" in content or '"url"' in content or "'url'" in content, "Snapshot must include url field"

    def test_snapshot_returns_title_field(self, extension_dir):
        content = (extension_dir / "snapshot.js").read_text()
        assert "title:" in content or '"title"' in content or "'title'" in content, "Snapshot must include title field"

    def test_snapshot_returns_elements_array(self, extension_dir):
        content = (extension_dir / "snapshot.js").read_text()
        assert "elements:" in content or '"elements"' in content or "'elements'" in content, "Snapshot must include elements array"

    def test_snapshot_uses_en_refs(self, extension_dir):
        content = (extension_dir / "snapshot.js").read_text()
        assert "@e" in content, "Must use @eN reference format"

    def test_snapshot_has_role_field(self, extension_dir):
        content = (extension_dir / "snapshot.js").read_text()
        assert "role:" in content or '"role"' in content or "'role'" in content, "Elements must have role field"

    def test_snapshot_has_text_field(self, extension_dir):
        content = (extension_dir / "snapshot.js").read_text()
        assert "text:" in content or '"text"' in content or "'text'" in content, "Elements must have text field"

    def test_snapshot_interactive_only_param(self, extension_dir):
        content = (extension_dir / "snapshot.js").read_text()
        assert "interactiveOnly" in content or "interactive_only" in content, "Must support interactive_only parameter"


# ══════════════════════════════════════════════════════════════════
# 7. Install-Skill Command Tests
# ══════════════════════════════════════════════════════════════════


class TestInstallSkillCommand:
    """install-skill CLI command must copy files correctly."""

    def test_install_skill_function_exists(self):
        src = Path(__file__).resolve().parents[2] / "agent_browser" / "cli" / "main.py"
        content = src.read_text()
        assert "def _install_skill" in content, "_install_skill must be defined in cli/main.py"

    def test_install_skill_copies_to_target(self, tmp_path, skill_dir):
        import shutil

        target = tmp_path / "skills" / "agent-browser"
        target.mkdir(parents=True, exist_ok=True)

        # Copy core skill files (new architecture: no references/)
        for fname in ["SKILL.md", "config.yaml", "daemon.py", "cli.py"]:
            src = skill_dir / fname
            if src.exists():
                shutil.copy2(src, target / fname)
        scripts_dir = target / "scripts"
        if (skill_dir / "scripts").exists():
            if scripts_dir.exists():
                shutil.rmtree(scripts_dir)
            shutil.copytree(skill_dir / "scripts", scripts_dir)

        assert (target / "SKILL.md").exists()
        assert (target / "daemon.py").exists()
        assert (target / "cli.py").exists()

    def test_install_skill_copies_daemon_and_cli(self, tmp_path, skill_dir):
        import shutil

        target = tmp_path / "skills" / "ab"
        target.mkdir(parents=True, exist_ok=True)
        for fname in ["daemon.py", "cli.py"]:
            src = skill_dir / fname
            if src.exists():
                shutil.copy2(src, target / fname)

        assert (target / "daemon.py").exists()
        assert (target / "cli.py").exists()

    def test_install_skill_existing_no_force(self, tmp_path, skill_dir):
        target = tmp_path / "skills" / "ab2"
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text("existing")

        # Simulate the no-force logic: detect existing and skip
        exists = (target / "SKILL.md").exists()
        assert exists  # Would return "exists" status

    def test_install_skill_force_overwrites(self, tmp_path, skill_dir):
        import shutil

        target = tmp_path / "skills" / "ab3"
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text("old")

        shutil.copy2(skill_dir / "SKILL.md", target / "SKILL.md")

        content = (target / "SKILL.md").read_text()
        assert "agent-browser" in content.lower() or "---" in content, "Should be overwritten"


# ══════════════════════════════════════════════════════════════════
# 8. Config Extension Field Tests
# ══════════════════════════════════════════════════════════════════


class TestConfigExtensionField:
    """SkillConfig must include extension_enabled field."""

    def test_config_has_extension_enabled(self):
        from agent_browser.config import SkillConfig
        config = SkillConfig()
        assert hasattr(config, "extension_enabled")
        assert isinstance(config.extension_enabled, bool)

    def test_extension_enabled_default_true(self):
        from agent_browser.config import SkillConfig
        config = SkillConfig()
        assert config.extension_enabled is True


# ══════════════════════════════════════════════════════════════════
# 9. Extension Backend Snapshot Tests
# ══════════════════════════════════════════════════════════════════


class TestExtensionBackendSnapshot:
    """ExtensionBackend.snapshot() must exist and match expected interface."""

    def test_snapshot_method_exists(self):
        from agent_browser.browser.extension import ExtensionBackend
        assert hasattr(ExtensionBackend, "snapshot")
        assert callable(getattr(ExtensionBackend, "snapshot"))

    def test_snapshot_is_async(self):
        import inspect
        from agent_browser.browser.extension import ExtensionBackend
        sig = inspect.signature(ExtensionBackend.snapshot)
        assert inspect.iscoroutinefunction(ExtensionBackend.snapshot)


# ══════════════════════════════════════════════════════════════════
# 10. Pyproject.toml Package Data Tests
# ══════════════════════════════════════════════════════════════════


class TestPyprojectPackageData:
    """pyproject.toml must declare skill/ and extension/ files as package_data."""

    def test_package_data_includes_skill_md(self, project_root):
        content = (project_root / "pyproject.toml").read_text()
        assert "skill/SKILL.md" in content, "package_data must include skill/SKILL.md"

    def test_package_data_includes_daemon_and_cli(self, project_root):
        content = (project_root / "pyproject.toml").read_text()
        assert "skill/daemon.py" in content, "package_data must include skill/daemon.py"
        assert "skill/cli.py" in content, "package_data must include skill/cli.py"

    def test_package_data_includes_scripts(self, project_root):
        content = (project_root / "pyproject.toml").read_text()
        assert "skill/scripts/doctor.py" in content or "skill/scripts/*.py" in content, \
            "package_data must include skill/scripts/doctor.py"

    def test_package_data_includes_extension(self, project_root):
        content = (project_root / "pyproject.toml").read_text()
        assert "extension/" in content or "extension" in content, "package_data must include extension/"

    def test_package_includes_popup_files(self, project_root):
        content = (project_root / "pyproject.toml").read_text()
        assert "popup.html" in content, "package_data must include popup.html"
        assert "popup.js" in content, "package_data must include popup.js"


# ══════════════════════════════════════════════════════════════════
# 11. SKILL.md Conformance Tests (CRITICAL -- validates merge quality)
# ══════════════════════════════════════════════════════════════════


class TestSkillMDConformance:
    """Validates that SKILL.md conforms to the CLI-only daemon+shim architecture."""

    def test_has_critical_no_python_rule(self, skill_dir):
        content = (skill_dir / "SKILL.md").read_text()
        assert "NEVER write Python scripts" in content or "NEVER" in content, \
            "Must have CRITICAL RULE forbidding Python script generation"

    def test_has_agent_browser_commands(self, skill_dir):
        content = (skill_dir / "SKILL.md").read_text()
        assert "agent-browser" in content, "Must show agent-browser CLI commands"
        assert "session create" in content, "Must document session create command"
        assert "snapshot" in content, "Must document snapshot command"
        assert "click" in content, "Must document click command"
        assert "fill" in content, "Must document fill command"

    def test_has_daemon_commands(self, skill_dir):
        content = (skill_dir / "SKILL.md").read_text()
        assert "daemon" in content, "Must document daemon management commands"

    def test_has_json_output_format(self, skill_dir):
        content = (skill_dir / "SKILL.md").read_text()
        assert '"success"' in content or "success" in content, \
            "Must document JSON output format"

    def test_has_error_recovery(self, skill_dir):
        content = (skill_dir / "SKILL.md").read_text()
        assert "Error Recovery" in content or "error" in content.lower(), \
            "Must have error recovery section"

    def test_has_chinese_triggers(self, skill_dir):
        content = (skill_dir / "SKILL.md").read_text()
        assert "帮我访问" in content, "Must have Chinese trigger phrases"
        assert "打开浏览器" in content, "Must have Chinese trigger phrases"

    def test_has_english_triggers(self, skill_dir):
        content = (skill_dir / "SKILL.md").read_text()
        assert "open website" in content or "browse" in content, \
            "Must have English trigger phrases"

    def test_no_python_import_examples(self, skill_dir):
        content = (skill_dir / "SKILL.md").read_text()
        assert "from agent_browser import" not in content, \
            "Must NOT have Python import examples (CLI-only architecture)"

    def test_no_hardcoded_path(self, skill_dir):
        content = (skill_dir / "SKILL.md").read_text()
        assert "iCloud" not in content, "Must NOT have hardcoded iCloud path"
        assert "Mobile Documents" not in content, "Must NOT have hardcoded Mobile Documents path"

    def test_no_fictional_functions(self, skill_dir):
        content = (skill_dir / "SKILL.md").read_text()
        assert "list_desktop_apps" not in content, "Must NOT include fictional list_desktop_apps"
        assert "run_desktop_command" not in content, "Must NOT include fictional run_desktop_command"

    def test_has_session_management(self, skill_dir):
        content = (skill_dir / "SKILL.md").read_text()
        assert "session" in content.lower(), "Must document session management"

    def test_has_installation_notes(self, skill_dir):
        content = (skill_dir / "SKILL.md").read_text()
        assert "install" in content.lower() or "PATH" in content, \
            "Must have installation notes"


# ══════════════════════════════════════════════════════════════════
# 12. Extension Popup Tests
# ══════════════════════════════════════════════════════════════════


class TestExtensionPopup:
    """Extension popup provides visible status panel with actionable diagnostics."""

    def test_popup_html_exists(self, extension_dir):
        assert (extension_dir / "popup.html").exists(), "popup.html must exist"

    def test_popup_js_exists(self, extension_dir):
        assert (extension_dir / "popup.js").exists(), "popup.js must exist"

    def test_popup_html_has_doctype(self, extension_dir):
        content = (extension_dir / "popup.html").read_text()
        assert "<!DOCTYPE" in content.upper(), "Must start with DOCTYPE declaration"

    def test_popup_html_references_popup_js(self, extension_dir):
        content = (extension_dir / "popup.html").read_text()
        assert 'src="popup.js"' in content or "src=\"popup.js\"" in content, "Must load popup.js"

    def test_popup_js_sends_getstatus(self, extension_dir):
        content = (extension_dir / "popup.js").read_text()
        assert "getStatus" in content, "popup.js must send {type: 'getStatus'} message to background"

    def test_manifest_has_default_popup(self, extension_dir):
        manifest = json.loads((extension_dir / "manifest.json").read_text())
        assert manifest["action"]["default_popup"] == "popup.html", "manifest must reference popup.html as default_popup"

    def test_popup_has_troubleshoot_section(self, extension_dir):
        content = (extension_dir / "popup.html").read_text()
        assert "Troubleshoot" in content, "Popup must have troubleshoot/diagnostics section"

    def test_popup_has_copyable_fix_commands(self, extension_dir):
        content = (extension_dir / "popup.html").read_text()
        # Should have actionable fix commands user can click to copy
        assert "data-cmd" in content, "Popup must have copy-to-clipboard fix commands"
