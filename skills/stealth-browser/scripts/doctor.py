"""Environment diagnostic and auto-fix for stealth-browser.

Wraps detect_missing_deps() from main.py with interactive auto-fix capability.
Designed to be invoked by SKILL.md on first use or by `stealth-browser doctor` CLI.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class CheckResult:
    """Single check result."""

    name: str
    status: str  # "pass" | "warn" | "fail" | "skip"
    message: str
    fixable: bool = False
    fix_command: str = ""
    output: str = ""


@dataclass
class DoctorReport:
    """Complete diagnostic report."""

    checks: List[CheckResult] = field(default_factory=list)
    passed: int = 0
    warned: int = 0
    failed: int = 0
    skipped: int = 0

    @property
    def ready(self) -> bool:
        return self.failed == 0 and self.warned == 0

    @property
    def summary(self) -> str:
        lines = []
        if self.passed:
            lines.append(f"{self.passed} passed")
        if self.warned:
            lines.append(f"{self.warned} warnings")
        if self.failed:
            lines.append(f"{self.failed} failed")
        if self.skipped:
            lines.append(f"{self.skipped} skipped")
        return ", ".join(lines) if lines else "All checks passed"

    def to_dict(self) -> dict:
        return {
            "ready": self.ready,
            "summary": self.summary,
            "passed": self.passed,
            "warned": self.warned,
            "failed": self.failed,
            "skipped": self.skipped,
            "checks": [
                {
                    "name": c.name,
                    "status": c.status,
                    "message": c.message,
                    "fixable": c.fixable,
                    "fix_command": c.fix_command,
                }
                for c in self.checks
            ],
        }


def _run_command(cmd: str, timeout: int = 60) -> CheckResult:
    """Run a shell command and return a CheckResult."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return CheckResult(
            name=cmd.split()[0] if " " in cmd else cmd,
            status="pass" if result.returncode == 0 else "fail",
            message=result.stdout.strip() or result.stderr.strip() or f"exit code {result.returncode}",
            fixable=False,
            output=result.stdout.strip(),
        )
    except subprocess.TimeoutExpired:
        return CheckResult(
            name=cmd[:50],
            status="fail",
            message=f"Command timed out after {timeout}s",
            fixable=False,
        )
    except FileNotFoundError:
        return CheckResult(
            name=cmd[:50],
            status="fail",
            message="Command not found",
            fixable=True,
            fix_command=cmd,
        )
    except Exception as e:
        return CheckResult(
            name=cmd[:50],
            status="fail",
            message=str(e),
            fixable=False,
        )


async def run_diagnosis(config=None) -> DoctorReport:
    """Run full environment diagnosis.

    Args:
        config: Optional SkillConfig to use for context. If None, auto-detects.

    Returns:
        DoctorReport with all check results.
    """
    report = DoctorReport()

    # ── Check 1: Python version ──────────────────────────
    py_version = sys.version_info
    py_major, py_minor = py_version.major, py_version.minor
    if py_major >= 3 and py_minor >= 11:
        report.checks.append(CheckResult(
            name="python_version",
            status="pass",
            message=f"Python {py_major}.{py_minor}+ OK (>=3.11 required)",
        ))
    else:
        report.checks.append(CheckResult(
            name="python_version",
            status="fail",
            message=f"Python {py_major}.{py_minor} found, need >=3.11",
            fixable=False,
        ))

    # ── Check 2: stealth-browser package installed ───────────────
    try:
        import stealth_browser  # noqa: F401

        # Try to get version
        version = None
        try:
            from importlib.metadata import version as v
            version = v("stealth-browser")
        except Exception:
            pass

        ver_str = f" (v{version})" if version else ""
        report.checks.append(CheckResult(
            name="package_installed",
            status="pass",
            message=f"stealth-browser installed{ver_str}",
        ))
    except ImportError:
        report.checks.append(CheckResult(
            name="package_installed",
            status="fail",
            message="stealth-browser not installed",
            fixable=True,
            fix_command="pip install stealth-browser[cloak]",
        ))

    # ── Check 3: Playwright browsers ────────────────────────────
    try:
        import playwright  # noqa: F401

        # Check if chromium is actually installed (not just the package)
        try:
            from playwright._impl._driver import compute_driver_executable
            chromepath = compute_driver_executable("chromium")
            if chromepath.exists():
                report.checks.append(CheckResult(
                    name="playwright_browsers",
                    status="pass",
                    message=f"Playwright Chromium installed at {chromepath}",
                ))
            else:
                report.checks.append(CheckResult(
                    name="playwright_browsers",
                    status="warn",
                    message="Playwright package installed but browsers not run 'playwright install chromium'",
                    fixable=True,
                    fix_command="playwright install chromium",
                ))
        except Exception:
            report.checks.append(CheckResult(
                name="playwright_browsers",
                status="warn",
                message="Playwright installed but cannot verify browser installation",
                fixable=True,
                fix_command="playwright install chromium",
            ))
    except ImportError:
        report.checks.append(CheckResult(
            name="playwright_browsers",
            status="fail",
            message="Playwright not installed",
            fixable=True,
            fix_command="pip install playwright && playwright install chromium",
        ))

    # ── Check 4: CloakBrowser (optional) ───────────────────────────
    try:
        import cloakbrowser  # noqa: F401
        report.checks.append(CheckResult(
            name="cloakbrowser",
            status="pass",
            message="CloakBrowser installed (full 7-layer anti-detection)",
        ))
    except ImportError:
        report.checks.append(CheckResult(
            name="cloakbrowser",
            status="warn",
            message="CloakBrowser not installed -- vanilla mode only (layers 6-7 stealth)",
            fixable=True,
            fix_command="pip install stealth-browser[cloak]",
        ))

    # ── Check 5: CDP endpoint ───────────────────────────────────
    cdp_url = "http://127.0.0.1:19222"
    browser_mode = "local"
    api_url = "http://localhost:8000"
    vnc_url = ""
    if config:
        cdp_url = config.cdp_url
        browser_mode = getattr(config, "browser_mode", "local")
        api_url = getattr(config, "api_url", "http://localhost:8000") or "http://localhost:8000"
        vnc_url = getattr(config, "vnc_url", "") or ""

    if browser_mode == "remote":
        report.checks.append(CheckResult(
            name="cdp_endpoint",
            status="skip",
            message="Remote browser mode -- CDP check skipped (browser runs on server)",
        ))
    else:
        try:
            import aiohttp

            async with (
                aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as s,
                s.get(f"{cdp_url}/json/version") as r,
            ):
                if r.status == 200:
                    report.checks.append(CheckResult(
                        name="cdp_endpoint",
                        status="pass",
                        message=f"CDP reachable at {cdp_url} (browser running)",
                    ))
                else:
                    report.checks.append(CheckResult(
                        name="cdp_endpoint",
                        status="warn",
                        message=f"CDP endpoint returned {r.status} at {cdp_url} -- browser may not be started",
                        fixable=True,
                        fix_command="# Start CloakBrowser or launch browser manually",
                    ))
        except ImportError:
            report.checks.append(CheckResult(
                name="cdp_endpoint",
                status="skip",
                message="aiohttp not installed, skipping CDP check (non-blocking)",
            ))
        except Exception:
            report.checks.append(CheckResult(
                name="cdp_endpoint",
                status="warn",
                message=f"CDP not reachable at {cdp_url} -- will attempt auto-connect on first session",
            ))

    # ── Check 5b: Remote API health (when browser_mode="remote") ───
    if browser_mode == "remote":
        try:
            import aiohttp

            async with (
                aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as s,
                s.get(f"{api_url}/health") as r,
            ):
                if r.status == 200:
                    report.checks.append(CheckResult(
                        name="remote_api",
                        status="pass",
                        message=f"Remote API reachable at {api_url}",
                    ))
                else:
                    report.checks.append(CheckResult(
                        name="remote_api",
                        status="warn",
                        message=f"Remote API returned {r.status} at {api_url}/health -- server may be unhealthy",
                    ))
        except ImportError:
            report.checks.append(CheckResult(
                name="remote_api",
                status="skip",
                message="aiohttp not installed, skipping remote API check (non-blocking)",
            ))
        except Exception:
            report.checks.append(CheckResult(
                name="remote_api",
                status="warn",
                message=f"Remote API not reachable at {api_url} -- check that the server is running",
                fixable=False,
            ))

    # ── Check 5c: VNC URL reachability (when vnc_url is set) ───────
    remote_type = getattr(config, "remote_type", "") if config else ""
    if browser_mode == "remote" and not vnc_url and remote_type == "distributed":
        report.checks.append(CheckResult(
            name="vnc_url",
            status="skip",
            message="Distributed mode: VNC URL is per-session (returned in create_session response, not pre-configured)",
        ))
    elif vnc_url:
        try:
            import aiohttp

            async with (
                aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as s,
                s.get(vnc_url) as r,
            ):
                if r.status < 500:
                    report.checks.append(CheckResult(
                        name="vnc_url",
                        status="pass",
                        message=f"VNC URL reachable at {vnc_url}",
                    ))
                else:
                    report.checks.append(CheckResult(
                        name="vnc_url",
                        status="warn",
                        message=f"VNC URL returned {r.status} at {vnc_url}",
                    ))
        except ImportError:
            report.checks.append(CheckResult(
                name="vnc_url",
                status="skip",
                message="aiohttp not installed, skipping VNC URL check (non-blocking)",
            ))
        except Exception:
            report.checks.append(CheckResult(
                name="vnc_url",
                status="warn",
                message=f"VNC URL not reachable at {vnc_url} -- visual browser access may be unavailable",
                fixable=False,
            ))

    # ─�─ Check 6: LLM API key (for Agent mode) ─────────────────
    has_key = bool(os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY") or os.getenv("GLM_API_KEY"))
    if has_key:
        report.checks.append(CheckResult(
            name="llm_api_key",
            status="pass",
            message="LLM API key found (Agent mode available)",
        ))
    else:
        report.checks.append(CheckResult(
            name="llm_api_key",
            status="warn",
            message="No LLM API key found -- Agent mode won't work, LLM ReAct mode works without it",
            fixable=False,  # User must provide this
        ))

    # ── Check 7: websockets (for Extension mode) ───────────────────
    try:
        import websockets  # noqa: F401
        report.checks.append(CheckResult(
            name="websockets",
            status="pass",
            message=f"websockets {websockets.__version__} installed (Extension mode available)",
        ))
    except ImportError:
        report.checks.append(CheckResult(
            name="websockets",
            status="warn",
            message="websockets not installed -- Extension mode unavailable",
            fixable=True,
            fix_command="pip install websockets",
        ))

    # Tally
    for c in report.checks:
        if c.status == "pass":
            report.passed += 1
        elif c.status == "warn":
            report.warned += 1
        elif c.status == "fail":
            report.failed += 1
        elif c.status == "skip":
            report.skipped += 1

    return report


async def auto_fix(report: DoctorReport) -> DoctorReport:
    """Attempt to auto-fix all fixable issues in a report.

    Modifies report in-place with updated results after attempting fixes.

    Returns the (possibly updated) report.
    """
    for check in report.checks:
        if not check.fixable or check.status in ("pass", "skip"):
            continue

        print(f"[AUTO-FIX] {check.name}: {check.message}")
        print(f"  Running: {check.fix_command}")

        result = _run_command(check.fix_command)
        result.name = check.name  # preserve original check name

        if result.status == "pass":
            result.message = f"Fixed: {check.output[:100]}"
            original_status = check.status
            check.status = "pass"
            check.fixable = False
            check.output = result.output
            report.passed += 1
            # Decrement only the counter matching the original status
            if original_status == "warn":
                report.warned -= 1
            elif original_status == "fail":
                report.failed -= 1
            print(f"  FIXED: {result.output[:120]}")
        else:
            result.message = f"Fix failed: {result.message}"
            print(f"  FAILED: {result.message}")

    return report


# CLI entry point
if __name__ == "__main__":
    async def main():
        report = await run_diagnosis()
        print(f"\n{'='*50}")
        print(f"Stealth Browser Doctor Report")
        print(f"{'='*50}")
        print(f"\n{report.summary}\n")

        for c in report.checks:
            icon = {"pass": "OK", "warn": "!!", "fail": "XX", "skip": "--"}[c.status]
            print(f"  [{icon}] {c.name}: {c.message}")
            if c.fixable:
                print(f"       Fix: {c.fix_command}")

        if not report.ready:
            print(f"\n{report.failed} issue(s), {report.warned} warning(s)")
            print("Run with --fix flag to attempt auto-fix:")
            print("  python -m stealth_browser.skill.scripts.doctor --fix")
        else:
            print("\nAll checks pass! Ready to use.")

    asyncio.run(main())
