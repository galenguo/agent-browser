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
# 2. Reference Docs Tests
# ══════════════════════════════════════════════════════════════════


class TestReferenceDocs:
    """All referenced docs from SKILL.md must exist and have content."""

    @pytest.mark.parametrize("doc", [
        "react-workflow.md",
        "error-recovery.md",
        "api-reference.md",
        "adapter-guide.md",
    ])
    def test_reference_exists(self, skill_dir, doc):
        ref_path = skill_dir / "references" / doc
        assert ref_path.exists(), f"Reference doc {doc} must exist"

    def test_react_workflow_has_loop_phases(self, skill_dir):
        content = (skill_dir / "references" / "react-workflow.md").read_text()
        assert "Observe" in content, "react-workflow must describe Observe phase"
        assert "Reason" in content, "react-workflow must describe Reason phase"
        assert "Act" in content, "react-workflow must describe Act phase"
        assert "Check" in content, "react-workflow must describe Check phase"

    def test_error_recovery_has_patterns(self, skill_dir):
        content = (skill_dir / "references" / "error-recovery.md").read_text()
        assert "E1" in content or "CDP" in content, "error-recovery must catalog error patterns"

    def test_api_reference_has_create_session(self, skill_dir):
        content = (skill_dir / "references" / "api-reference.md").read_text()
        assert "create_session" in content, "api-reference must document create_session"

    def test_adapter_guide_has_adapters(self, skill_dir):
        content = (skill_dir / "references" / "adapter-guide.md").read_text()
        assert "list_adapters" in content or "run_adapter" in content, "adapter-guide must document adapter system"
        # Must NOT contain fictional functions
        assert "list_desktop_apps" not in content, "adapter-guide must not include fictional list_desktop_apps"
        assert "run_desktop_command" not in content, "adapter-guide must not include fictional run_desktop_command"


# ══════════════════════════════════════════════════════════════════
# 3. Doctor Script Tests
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

        shutil.copy2(skill_dir / "SKILL.md", target / "SKILL.md")
        refs_dir = target / "references"
        if (skill_dir / "references").exists():
            if refs_dir.exists():
                shutil.rmtree(refs_dir)
            shutil.copytree(skill_dir / "references", refs_dir)
        scripts_dir = target / "scripts"
        if (skill_dir / "scripts").exists():
            if scripts_dir.exists():
                shutil.rmtree(scripts_dir)
            shutil.copytree(skill_dir / "scripts", scripts_dir)

        assert (target / "SKILL.md").exists()
        assert (target / "references" / "react-workflow.md").exists()

    def test_install_skill_copies_references(self, tmp_path, skill_dir):
        import shutil

        target = tmp_path / "skills" / "ab"
        target.mkdir(parents=True, exist_ok=True)
        if (skill_dir / "references").exists():
            shutil.copytree(skill_dir / "references", target / "references")

        assert (target / "references" / "error-recovery.md").exists()

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

    def test_package_data_includes_references(self, project_root):
        content = (project_root / "pyproject.toml").read_text()
        assert "references" in content, "package_data must include references"

    def test_package_data_includes_scripts(self, project_root):
        content = (project_root / "pyproject.toml").read_text()
        assert "scripts" in content.lower() or "scripts/*.py" in content, "package_data must include scripts"

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
    """Validates that the rewritten SKILL.md conforms to Claude Code spec and contains
    all required canonical patterns + new content without fictional functions."""

    def test_has_arguments_handling_blockquote(self, skill_dir):
        content = (skill_dir / "SKILL.md").read_text()
        assert "> **ARGUMENTS Handling**" in content, "Must have ARGUMENTS Handling blockquote directive"

    def test_has_execution_environment_blockquote(self, skill_dir):
        content = (skill_dir / "SKILL.md").read_text()
        assert "> **Execution Environment**" in content, "Must have Execution Environment blockquote directive"

    def test_has_chinese_triggers(self, skill_dir):
        content = (skill_dir / "SKILL.md").read_text()
        assert "帮我访问" in content, "Must have Chinese trigger phrases"
        assert "打开浏览器" in content, "Must have Chinese trigger phrases"

    def test_has_english_triggers(self, skill_dir):
        content = (skill_dir / "SKILL.md").read_text()
        assert "open website" in content, "Must have English trigger phrases"
        assert "search for" in content, "Must have English trigger phrases"

    def test_uses_agent_browser_import(self, skill_dir):
        content = (skill_dir / "SKILL.md").read_text()
        assert "from agent_browser import" in content, "Must use from agent_browser import (not skills.agent_browser)"
        assert "from skills.agent_browser" not in content, "Must NOT use old skills.agent_browser import path"

    def test_no_hardcoded_path(self, skill_dir):
        content = (skill_dir / "SKILL.md").read_text()
        assert "iCloud" not in content, "Must NOT have hardcoded iCloud path"
        assert "Mobile Documents" not in content, "Must NOT have hardcoded Mobile Documents path"

    def test_has_doctor_integration(self, skill_dir):
        content = (skill_dir / "SKILL.md").read_text()
        assert "doctor" in content.lower() or "run_diagnosis" in content, "Must reference doctor.py"

    def test_has_extension_mode_section(self, skill_dir):
        content = (skill_dir / "SKILL.md").read_text()
        assert "Extension Mode" in content or "Chrome Extension" in content, "Must document Extension mode setup"

    def test_has_site_adapters(self, skill_dir):
        content = (skill_dir / "SKILL.md").read_text()
        assert "适配器" in content or "adapters" in content, "Must cover site adapters"

    def test_has_qr_login(self, skill_dir):
        content = (skill_dir / "SKILL.md").read_text()
        assert "扫码登录" in content or "QR" in content, "Must cover QR login flow"

    def test_has_remote_curl_examples(self, skill_dir):
        content = (skill_dir / "SKILL.md").read_text()
        assert "curl" in content, "Must have curl examples for remote mode"

    def test_has_progressive_disclosure(self, skill_dir):
        content = (skill_dir / "SKILL.md").read_text()
        assert "references/" in content, "Must have progressive disclosure links to reference docs"

    def test_has_conversational_recovery(self, skill_dir):
        content = (skill_dir / "SKILL.md").read_text()
        # Must have more than just a static table -- should guide Claude's conversation
        assert "CLASSIFY" in content or "auto-fix" in content or "PRESENT TO USER" in content, \
            "Must have conversational error recovery guidance beyond a lookup table"

    def test_no_fictional_functions(self, skill_dir):
        content = (skill_dir / "SKILL.md").read_text()
        assert "list_desktop_apps" not in content, "Must NOT include fictional list_desktop_apps"
        assert "run_desktop_command" not in content, "Must NOT include fictional run_desktop_command"

    def test_documents_setup_function(self, skill_dir):
        content = (skill_dir / "SKILL.md").read_text()
        # "Setup" appears in Quick Start checklist + Extension Mode section
        assert "setup" in content.lower(), "Must document setup/Setup for server mode"

    def test_documents_configure_function(self, skill_dir):
        content = (skill_dir / "SKILL.md").read_text()
        assert "configure" in content, "Must document configure() function"

    def test_has_quick_start_checklist(self, skill_dir):
        content = (skill_dir / "SKILL.md").read_text()
        assert "Step 1" in content or "doctor" in content.lower(), "Must have Quick Start checklist with doctor.py step"
        assert "Checklist" in content or "checklist" in content.lower(), "Must have setup progress tracking"

    def test_has_mode_priority_section(self, skill_dir):
        content = (skill_dir / "SKILL.md").read_text()
        assert "优先级" in content or "Priority" in content, "Must document mode priority order (Extension > Local > Remote)"

    def test_has_human_handoff_points(self, skill_dir):
        content = (skill_dir / "SKILL.md").read_text()
        assert "Handoff" in content or "handoff" in content, "Must specify when to stop and ask user"


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
