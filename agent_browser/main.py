"""Agent Browser main entry point -- lightweight facade (routes all operations through StealthMiddleware)

Phase 0: First-Session Recovery -- auto-detect missing deps, auto-fix, retry.
When something fails, return structured dict so Claude Code can present options.
"""
import asyncio
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from .config import SkillConfig, detect_mode, load_config

logger = logging.getLogger(__name__)
_REF_PATTERN = re.compile(r'^@e\d+$')

_config: SkillConfig | None = None
_middleware = None
_middleware_lock = asyncio.Lock()


# ── Phase 0: Structured Recovery Types ──────────────────────

@dataclass
class DepStatus:
    """Single dependency check result."""
    name: str
    available: bool
    fixable: bool = False
    fix_command: str = ""
    message: str = ""


@dataclass
class RecoveryReport:
    """Structured report returned when first-session setup needs attention.

    Claude Code receives this and presents options via AskUserQuestion.
    """
    missing_deps: list[DepStatus] = field(default_factory=list)
    fixable: list[DepStatus] = field(default_factory=list)
    needs_human: list[DepStatus] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return len(self.missing_deps) == 0

    @property
    def suggestion(self) -> str:
        if self.ready:
            return ""
        auto_fix = [d for d in self.missing_deps if d.fixable]
        return (
            f"Missing {len(self.missing_deps)} dep(s): "
            f"{', '.join(d.name for d in self.missing_deps)}. "
            f"{len(auto_fix)} can be auto-fixed."
        )


async def detect_missing_deps(config: SkillConfig = None) -> RecoveryReport:
    """Check environment for missing dependencies. Returns structured report.

    Called by _ensure_middleware() on first use. Non-blocking checks only.
    """
    if config is None:
        config = _config or SkillConfig()

    report = RecoveryReport()

    # 1. CloakBrowser package
    try:
        import cloakbrowser  # noqa: F401
    except ImportError:
        report.missing_deps.append(DepStatus(
            name="cloakbrowser",
            available=False,
            fixable=True,
            fix_command="pip install cloakbrowser==0.3.18",
            message="CloakBrowser package not installed (anti-detection browser)",
        ))

    # 2. CDP reachability
    cdp_ok = False
    try:
        import aiohttp
        async with (
            aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=2)) as s,
            s.get(f"{config.cdp_url}/json/version") as r,
        ):
                cdp_ok = r.status == 200
    except Exception:
        pass

    if not cdp_ok:
        report.missing_deps.append(DepStatus(
            name="cdp",
            available=False,
            fixable=True,
            fix_command="auto-launch on connect",
            message=f"CDP endpoint not reachable at {config.cdp_url}",
        ))

    # 3. LLM API key (only for agent mode)
    has_key = bool(
        os.getenv("OPENAI_API_KEY")
        or os.getenv("ANTHROPIC_API_KEY")
        or os.getenv("GLM_API_KEY")
    )
    if not has_key:
        report.needs_human.append(DepStatus(
            name="llm_api_key",
            available=False,
            fixable=False,
            message="No LLM API key found (needed for Agent mode; LLM mode works without)",
        ))

    # 4. Playwright browsers installed
    try:
        import playwright  # noqa: F401 — just verify package is installed
    except ImportError:
        report.missing_deps.append(DepStatus(
            name="playwright",
            available=False,
            fixable=True,
            fix_command="pip install playwright && playwright install chromium",
            message="Playwright not installed",
        ))

    return report


def _format_recovery_for_claude(report: RecoveryReport) -> dict[str, Any]:
    """Convert RecoveryReport to plain dict for Claude Code tool context."""
    return {
        "ready": report.ready,
        "missing": [d.name for d in report.missing_deps],
        "fixable": [{"name": d.name, "command": d.fix_command} for d in report.fixable or report.missing_deps if d.fixable],
        "needs_human": [d.name for d in report.needs_human],
        "suggestion": report.suggestion,
    }


async def _ensure_middleware(config: SkillConfig = None):
    global _config, _middleware
    if _middleware is not None:
        return _middleware
    async with _middleware_lock:
        if _middleware is not None:
            return _middleware
        if config:
            _config = config
        elif _config is not None:
            pass
        else:
            _config = await detect_mode()

    # ── Phase 0: First-Session Recovery ──
    # Quick pre-check: detect missing deps before attempting connection
    report = await detect_missing_deps(_config)
    if not report.ready:
        logger.info(f"First-session recovery: {report.suggestion}")

    # ── Backend selection: Extension > Local (CloakBrowser) > Remote ──
    raw_backend = await _select_backend(_config)

    from agent_browser.stealth.middleware import StealthMiddleware
    _middleware = StealthMiddleware(raw_backend, _config)

    # Connect with recovery: if it fails, diagnose and return structured info
    try:
        await _middleware.connect()
        logger.info(f"Middleware ready: {_config.calling_mode}/{_config.browser_mode}")
        return _middleware
    except Exception as e:
        logger.warning(f"Middleware connect failed: {e}")
        # Re-check deps after failure -- may have more detail now
        post_report = await detect_missing_deps(_config)
        if not post_report.ready:
            # Return structured dict for Claude Code to present to user
            raise FirstSessionError(
                message=f"Setup needed: {post_report.suggestion}",
                recovery=_format_recovery_for_claude(post_report),
                original_error=e,
            ) from e
        raise


class FirstSessionError(Exception):
    """Structured error for first-session setup failures.

    Carries a 'recovery' dict that Claude Code can use to present options.
    """

    def __init__(self, message: str, recovery: dict[str, Any], original_error: Exception = None):
        super().__init__(message)
        self.recovery = recovery
        self.original_error = original_error


async def _select_backend(config: SkillConfig):
    """
    Backend selection logic (priority):

    1. Extension mode: Chrome Extension connected -> use user's real Chrome
    2. Local mode: CloakBrowser CDP reachable -> use local anti-detection browser
    3. API mode: FastAPI service available -> remote call
    4. Fallback: Local mode (default)
    """
    # Priority 1: Try Extension mode (user's real Chrome)
    if await _try_extension_connection(config):
        try:
            from agent_browser.browser.extension import ExtensionBackend
            logger.info("Using Extension backend (real Chrome via Chrome Extension)")
            return ExtensionBackend(config)
        except Exception as e:
            logger.warning(f"Extension backend failed, falling back to local: {e}")

    # Priority 2-4: Existing logic (Local / API / fallback)
    if config.calling_mode == "cli":
        from agent_browser.browser.local import LocalCDPBackend
        return LocalCDPBackend(config)
    elif config.calling_mode == "api":
        try:
            from agent_browser.browser.remote import RemoteAPIBackend
            return RemoteAPIBackend(config)
        except ImportError:
            from agent_browser.browser.local import LocalCDPBackend
            return LocalCDPBackend(config)
    else:
        from agent_browser.browser.local import LocalCDPBackend
        return LocalCDPBackend(config)


async def _try_extension_connection(config: SkillConfig) -> bool:
    """
    Check whether Chrome Extension is connected.

    Method: Check WebSocket connection status via Daemon's ExtensionBridge.
    Does not actually create a backend -- just a lightweight probe.
    """
    # Quick check: skip if config explicitly disables Extension
    if getattr(config, 'extension_enabled', True) is False:
        return False

    try:
        from agent_browser.browser.daemon import BrowserDaemon  # noqa: F401 — ExtensionBridge used later in file

        daemon = BrowserDaemon.get(config)
        await daemon.ensure_connected()

        bridge = daemon.extension_bridge
        if bridge and bridge.is_connected:
            logger.info("Chrome Extension detected and connected")
            return True
    except ImportError:
        # websockets not installed, skip Extension mode
        pass
    except Exception as e:
        logger.debug(f"Extension detection failed (non-fatal): {e}")

    return False


def configure(**kwargs) -> SkillConfig:
    global _config
    _config = load_config(**kwargs)
    return _config


def reset():
    global _config, _middleware
    if _middleware:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(_middleware.disconnect())
            else:
                loop.run_until_complete(_middleware.disconnect())
        except Exception as e:
            logger.warning(f"reset(): disconnect failed (non-fatal): {e}")
    _config = None
    _middleware = None


async def setup(**kwargs) -> dict[str, Any]:
    """First-session setup: detect, validate, configure, and verify.

    Designed for Claude Code context: returns structured dict, never calls input().
    Callers (Claude Code) present options via AskUserQuestion based on the result.

    Returns dict with keys:
      - config: DeployConfig instance
      - issues: list of ConfigIssue (from validate_config)
      - report: RecoveryReport (from detect_missing_deps)
      - ready: bool -- True if system is ready to use

    Kwargs are forwarded to DeployConfig constructor for programmatic override.
    """
    from agent_browser.deploy_config import (
        detect_environment,
        generate_config,
        load_deploy_config,
        validate_config,
    )

    # 1. Detect environment
    env = detect_environment()

    # 2. Load existing config or create from kwargs
    cfg = load_deploy_config()

    # Apply explicit overrides
    for k, v in kwargs.items():
        if hasattr(cfg, k) and v is not None:
            setattr(cfg, k, v)

    # Fill auto-detected fields
    if not cfg.os:
        cfg.os = env.get("os", "")
    if not cfg.arch:
        cfg.arch = env.get("arch", "")

    # 3. Validate
    issues = validate_config(cfg, env_check=True)

    # 4. Check runtime deps
    report = await detect_missing_deps()

    # 5. Write config (atomic)
    config_path = generate_config(cfg)

    # 6. Determine readiness
    errors = [i for i in issues if i.severity == "error"]
    ready = len(errors) == 0 and report.ready

    logger.info(
        f"Setup complete: ready={ready}, "
        f"issues={len(issues)} ({len(errors)} errors), "
        f"missing_deps={len(report.missing_deps)}"
    )

    return {
        "config": cfg,
        "issues": issues,
        "report": report,
        "ready": ready,
        "config_path": str(config_path),
        "environment": env,
    }


# ── Internal utilities ──

def _validate_ref(ref: str):
    if not _REF_PATTERN.match(ref):
        raise ValueError(f"Invalid ref: {ref}. Expected @e<digits>")


async def _get_page(session_id: str):
    mw = await _ensure_middleware()
    return await mw.get_page(session_id)


async def _ref_op(session_id: str, ref: str, js_body: str):
    """Execute JS via data-ab-ref attribute (unified validation + query + error handling)."""
    _validate_ref(ref)
    page = await _get_page(session_id)
    safe_ref = json.dumps(ref)
    result = await page.evaluate(
        f"""(() => {{
            const el = document.querySelector('[data-ab-ref="' + {safe_ref} + '"]');
            if (!el) return {{error: 'not found'}};
            {js_body}
            return {{status: 'ok'}};
        }})()"""
    )
    if result and result.get("error"):
        raise ValueError(f"Element {ref} not found. DOM may have changed.")


# ── Facade API ──

async def create_session(cdp_url=None, mode=None, api_url=None, **kwargs) -> str:
    cfg = {}
    if mode:
        cfg["calling_mode"] = mode
    if api_url:
        cfg["api_url"] = api_url
    if cdp_url:
        cfg["cdp_url"] = cdp_url
    cfg.update(kwargs)
    mw = await _ensure_middleware(load_config(**cfg) if cfg else None)
    sid = uuid.uuid4().hex
    await mw.create_session(sid)
    return sid


async def delete_session(session_id: str):
    mw = await _ensure_middleware()
    await mw.delete_session(session_id)


async def open_page(session_id: str, url: str):
    from agent_browser.pipeline.steps import _validate_url
    url = _validate_url(url)
    page = await _get_page(session_id)
    await page.goto(url)
    mw = await _ensure_middleware()
    await mw.cache_snapshot_after_open(session_id)


async def snapshot(session_id: str, interactive_only: bool = False):
    mw = await _ensure_middleware()
    return await mw.snapshot(session_id, interactive_only)


async def click(session_id: str, ref: str):
    await _ref_op(session_id, ref, "el.click();")


async def fill(session_id: str, ref: str, text: str):
    v = json.dumps(text)
    await _ref_op(session_id, ref,
        f"el.focus(); el.value = {v}; el.dispatchEvent(new Event('input', {{bubbles: true}}));")


async def scroll(session_id: str, direction: str = "down", amount: int = 500):
    page = await _get_page(session_id)
    await page.mouse_wheel(0, amount if direction == "down" else -amount)


async def evaluate(session_id: str, expression: str):
    """Execute JavaScript in the page context and return the result."""
    page = await _get_page(session_id)
    return await page.evaluate(expression)


async def select_option(session_id: str, ref: str, value: str):
    v = json.dumps(value)
    await _ref_op(session_id, ref,
        f"el.value = {v}; el.dispatchEvent(new Event('change', {{bubbles: true}}));")


async def hover(session_id: str, ref: str):
    _validate_ref(ref)
    page = await _get_page(session_id)
    safe_ref = json.dumps(ref)
    box = await page.evaluate(
        f"""(() => {{
            const el = document.querySelector('[data-ab-ref="' + {safe_ref} + '"]');
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return {{x: r.x + r.width/2, y: r.y + r.height/2}};
        }})()"""
    )
    if not box:
        raise ValueError(f"Element {ref} not found. DOM may have changed.")
    await page.mouse_move(box["x"], box["y"])


async def press_key(session_id: str, key: str):
    page = await _get_page(session_id)
    await page.keyboard_press(key)


async def wait_for_selector(session_id: str, selector: str, timeout: int = 10000):
    page = await _get_page(session_id)
    await page.wait_for_selector(selector, timeout=timeout)


async def go_back(session_id: str):
    page = await _get_page(session_id)
    await page.go_back()


async def run_task(
    session_id: str, task: str,
    intelligence: str = "agent",
    llm_config: dict = None,
    max_steps: int = 6,
    total_timeout: float = 300.0,
) -> dict:
    mw = await _ensure_middleware()
    return await mw.run_task(
        session_id, task,
        intelligence=intelligence, llm_config=llm_config,
        max_steps=max_steps, total_timeout=total_timeout,
    )


async def debug_pipeline(
    session_id: str,
    site: str,
    command: str,
    args: dict = None,
    breakpoints: list = None,
    cdp_url: str = "http://127.0.0.1:19222",
    **kwargs,
) -> Any:
    """Debug mode: single-step execute adapter pipeline with breakpoint support.

    Args:
        session_id: Browser session ID
        site: Site name (e.g., "boss")
        command: Command name (e.g., "search")
        args: Adapter parameters
        breakpoints: Breakpoint step index list (e.g., [2, 5] means pause after steps 2 and 5)
        cdp_url: CDP connection address

    Returns:
        Breakpoint state dict or final data (compatible with execute_pipeline)

    Example::

        result = await debug_pipeline(session_id, "boss", "search",
                                        {"query": "Python"}, breakpoints=[2])
        # Pause after navigate, return current page data
    """
    from agent_browser.adapters.loader import get_adapter
    from agent_browser.pipeline.debugger import debug_pipeline as _debug

    adapter = get_adapter(site, command)
    if not adapter:
        raise ValueError(f"Adapter not found: {site}/{command}")

    merged_args = {**(args or {}), "_adapter_name": f"{site}/{command}"}
    pipeline = adapter.get("pipeline", [])
    stealth = adapter.get("stealth", {})

    return await _debug(
        steps=pipeline,
        session_id=session_id,
        args=merged_args,
        breakpoints=breakpoints,
        stealth_config=stealth,
    )
