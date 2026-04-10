"""Setup wizard for agent-browser skill config.

Writes ~/.agent-browser/skill.yaml from user-provided parameters.
Called when skill.yaml is missing or the user wants to reconfigure.

CLI usage:
    python -m agent_browser.skill.scripts.setup --mode local
    python -m agent_browser.skill.scripts.setup --mode remote-aio --api-url http://myhost:8000 --vnc-url http://myhost:6080
    python -m agent_browser.skill.scripts.setup --mode remote-distributed --api-url http://myhost:8000

Programmatic usage:
    from agent_browser.skill.scripts.setup import write_skill_config
    path = write_skill_config("remote-aio", api_url="http://myhost:8000", vnc_url="http://myhost:6080")
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

SKILL_YAML = Path.home() / ".agent-browser" / "skill.yaml"
CDP_URL_DEFAULT = "http://127.0.0.1:19222"

_VALID_MODES = ("local", "remote-aio", "remote-distributed")


def write_skill_config(
    mode: str,
    api_url: str = "",
    vnc_url: str = "",
    cdp_url: str = CDP_URL_DEFAULT,
    path: Path | None = None,
) -> Path:
    """Write ~/.agent-browser/skill.yaml for the given mode.

    Args:
        mode: One of "local", "remote-aio", "remote-distributed".
        api_url: Remote API URL (required for remote modes).
        vnc_url: VNC URL (required for remote-aio; empty for remote-distributed).
        cdp_url: CDP endpoint (only relevant for local mode).
        path: Override output path. Defaults to ~/.agent-browser/skill.yaml.

    Returns:
        Path to the written skill.yaml.

    Raises:
        ValueError: If mode is invalid or required params are missing.
    """
    if mode not in _VALID_MODES:
        raise ValueError(f"Invalid mode {mode!r}. Choose from: {', '.join(_VALID_MODES)}")

    if mode in ("remote-aio", "remote-distributed") and not api_url:
        raise ValueError(f"--api-url is required for mode {mode!r}")

    target = path or SKILL_YAML
    target.parent.mkdir(parents=True, exist_ok=True)

    if mode == "local":
        skill = {
            "calling_mode": "cli",
            "browser_mode": "local",
            "remote_type": "aio",
            "intelligence": "llm",
            "cdp_url": cdp_url,
            "api_url": "",
            "vnc_url": "",
        }
    elif mode == "remote-aio":
        skill = {
            "calling_mode": "api",
            "browser_mode": "remote",
            "remote_type": "aio",
            "intelligence": "llm",
            "api_url": api_url,
            "vnc_url": vnc_url,
            "cdp_url": cdp_url,
        }
    else:  # remote-distributed
        skill = {
            "calling_mode": "api",
            "browser_mode": "remote",
            "remote_type": "distributed",
            "intelligence": "llm",
            "api_url": api_url,
            "vnc_url": "",
            "cdp_url": cdp_url,
        }

    yaml_lines = []
    for k, v in skill.items():
        yaml_lines.append(f"{k}: {v!r}\n")
    yaml_content = "".join(yaml_lines)

    fd, tmp_path = tempfile.mkstemp(suffix=".yaml", prefix="ab-skill-", dir=target.parent)
    try:
        os.write(fd, yaml_content.encode("utf-8"))
    finally:
        os.close(fd)
    shutil.move(tmp_path, target)
    return target


def _main() -> None:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Configure agent-browser skill (writes ~/.agent-browser/skill.yaml)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modes:
  local              Direct CloakBrowser CDP -- no server needed (default)
  remote-aio         Remote all-in-one server (api_url + vnc_url required)
  remote-distributed Remote distributed (api_url required; vnc URL returned per-session)

Examples:
  python -m agent_browser.skill.scripts.setup --mode local
  python -m agent_browser.skill.scripts.setup --mode remote-aio --api-url http://myhost:8000 --vnc-url http://myhost:6080
  python -m agent_browser.skill.scripts.setup --mode remote-distributed --api-url http://myhost:8000
""",
    )
    parser.add_argument("--mode", required=True, choices=list(_VALID_MODES), help="Deployment mode")
    parser.add_argument("--api-url", default="", help="Remote API URL (required for remote modes)")
    parser.add_argument("--vnc-url", default="", help="VNC URL (for remote-aio mode)")
    parser.add_argument("--cdp-url", default=CDP_URL_DEFAULT, help="CDP endpoint (for local mode)")
    parser.add_argument("--output", default=None, help="Override output path (default: ~/.agent-browser/skill.yaml)")
    args = parser.parse_args()

    output_path = Path(args.output) if args.output else None

    try:
        target = write_skill_config(
            mode=args.mode,
            api_url=args.api_url,
            vnc_url=args.vnc_url,
            cdp_url=args.cdp_url,
            path=output_path,
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"skill.yaml written to {target}")
    print()

    # Run doctor to validate connectivity
    print("Running environment check...")
    import asyncio

    from agent_browser.config import SkillConfig
    from agent_browser.skill.scripts.doctor import run_diagnosis

    mode_map = {
        "local": SkillConfig(browser_mode="local", cdp_url=args.cdp_url),
        "remote-aio": SkillConfig(browser_mode="remote", remote_type="aio", api_url=args.api_url, vnc_url=args.vnc_url),
        "remote-distributed": SkillConfig(browser_mode="remote", remote_type="distributed", api_url=args.api_url),
    }
    cfg = mode_map[args.mode]

    report = asyncio.run(run_diagnosis(cfg))
    print(f"\n{report.summary}\n")
    for c in report.checks:
        icon = {"pass": "OK", "warn": "!!", "fail": "XX", "skip": "--"}[c.status]
        print(f"  [{icon}] {c.name}: {c.message}")
        if c.fixable:
            print(f"       Fix: {c.fix_command}")

    if report.failed:
        print(f"\n{report.failed} check(s) failed. Run doctor for details:")
        print("  python -m agent_browser.skill.scripts.doctor")
        sys.exit(1)
    else:
        print("\nReady to use.")


if __name__ == "__main__":
    _main()
