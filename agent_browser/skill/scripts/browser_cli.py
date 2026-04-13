"""Skill entry point for Claude Code -- self-contained client Facade API.

Connects to agent-browser API server via HTTP.  Mode-agnostic: configuration
determines the target service endpoint.  Zero dependency on main.py.

Configuration priority::

    constructor params  >  skill/config.yaml  >  auto-detect  >  default

Config file lives inside the skill package (``agent_browser/skill/config.yaml``)
so it travels with the skill when installed by Claude Code / OpenClaw.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Defaults ────────────────────────────────────────────────────────

DEFAULT_API_URL = "http://localhost:8000"
DEFAULT_TIMEOUT = 120  # seconds

# Config file lives next to this script's parent (skill/ directory)
_SKILL_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = _SKILL_DIR / "config.yaml"
# Session cache file: persists session_id across conversations
SESSION_CACHE_PATH = _SKILL_DIR / ".session_cache.json"

# ── SkillBrowser ───────────────────────────────────────────────────


class SkillBrowser:
    """Mode-agnostic browser automation **client** for Claude Code.

    Always connects to a remote API server via HTTP.  Configuration is
    loaded automatically from constructor parameters, then from the bundled
    ``skill/config.yaml`` file (travels with the skill), falling back to
    auto-detection and finally defaults.

    Usage::

        sb = SkillBrowser()                        # auto-load config
        sid = await sb.create_session()
        snap = await sb.snapshot(sid)              # {url, title, elements}
        await sb.click(sid, "@e3")
        result = await sb.run_task(sid, "search AI")
        await sb.delete_session(sid)

    Explicit configuration::

        sb = SkillBrowser(
            api_url="http://api.agent-browser.local",
            api_key="key-alice-001",
        )
    """

    def __init__(
        self,
        api_url: str | None = None,
        api_key: str | None = None,
        timeout: int | None = None,
        **_kwargs: Any,
    ) -> None:
        self._api_url: str = DEFAULT_API_URL
        self._api_key: str = ""
        self._timeout: int = DEFAULT_TIMEOUT
        self._intelligence: str = "llm"
        self._http = None  # aiohttp.ClientSession (lazy)
        self._load_config(
            api_url=api_url,
            api_key=api_key,
            timeout=timeout,
        )

    # ── Configuration ─────────────────────────────────────────────

    def _load_config(
        self,
        api_url: str | None = None,
        api_key: str | None = None,
        timeout: int | None = None,
    ) -> None:
        """Load configuration: params > skill/config.yaml > auto-detect > default."""

        # 1. Constructor parameters (highest priority)
        if api_url is not None:
            self._api_url = api_url.rstrip("/")
        if api_key is not None:
            self._api_key = api_key
        if timeout is not None:
            self._timeout = timeout

        # 2. Bundled YAML config file (inside skill/ directory)
        if CONFIG_PATH.exists():
            try:
                import yaml

                with open(CONFIG_PATH) as f:
                    data = yaml.safe_load(f) or {}
            except Exception:
                data = {}
            else:
                svc = data.get("service", {})
                if isinstance(svc, dict):
                    if self._api_url == DEFAULT_API_URL and svc.get("url"):
                        self._api_url = str(svc["url"]).rstrip("/")
                    if not self._api_key and svc.get("api_key"):
                        self._api_key = str(svc["api_key"])
                    if svc.get("timeout") and self._timeout == DEFAULT_TIMEOUT:
                        try:
                            self._timeout = int(svc["timeout"])
                        except (ValueError, TypeError):
                            pass

            # Read intelligence mode from YAML
            intel = data.get("intelligence", "")
            if intel in ("llm", "agent"):
                self._intelligence = intel

        # 3. Auto-detect (only when URL is still the default)
        if self._api_url == DEFAULT_API_URL:
            detected = self._detect_api_url()
            if detected:
                self._api_url = detected

        logger.info(
            "SkillBrowser initialized: url=%s, key=%s, timeout=%ds, config=%s",
            self._api_url,
            ("set" if self._api_key else "none"),
            self._timeout,
            CONFIG_PATH,
        )

    @staticmethod
    def _detect_api_url() -> str | None:
        """Auto-detect API endpoint by probing localhost:8000/health."""
        try:
            import aiohttp

            async def _probe():
                async with aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=2),
                ) as s:
                    async with s.get(f"{DEFAULT_API_URL}/health") as r:
                        if r.status == 200:
                            return DEFAULT_API_URL
                        return None

            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(asyncio.run, _probe())
                    return future.result(timeout=3)
            else:
                return asyncio.run(_probe())
        except Exception:
            return None

    # ── HTTP Layer ─────────────────────────────────────────────────

    async def _ensure_http(self):
        """Lazily create aiohttp session."""
        if self._http is None or self._http.closed:
            import aiohttp

            self._http = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self._timeout),
            )

    async def _request(
        self,
        method: str,
        path: str,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send HTTP request to the API server."""
        await self._ensure_http()
        headers: dict[str, str] = {}
        if self._api_key:
            headers["X-API-Key"] = self._api_key

        url = f"{self._api_url}{path}"
        try:
            async with self._http.request(
                method,
                url,
                json=json_data,
                headers=headers,
            ) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    raise SkillBrowserError(
                        f"API error {resp.status}: {text}",
                        status_code=resp.status,
                        url=url,
                    )
                if resp.content_length == 0:
                    return {}
                return await resp.json()
        except SkillBrowserError:
            raise
        except Exception as e:
            err_type = type(e).__name__
            if "Connect" in err_type or "connect" in str(e).lower():
                raise SkillBrowserError(
                    f"Cannot connect to browser service at {self._api_url}. "
                    f"Please ensure the API server is running and accessible.",
                    status_code=0,
                    url=self._api_url,
                ) from e
            raise SkillBrowserError(
                f"Request failed: {e}",
                status_code=0,
                url=url,
            ) from e

    async def close(self):
        """Close HTTP session."""
        if self._http and not self._http.closed:
            await self._http.close()
            self._http = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()

    # ── Diagnose ────────────────────────────────────────────────────

    async def diagnose(self) -> dict[str, Any]:
        """Check environment and API service availability.

        Returns a structured report with ``ready`` boolean.
        """
        report: dict[str, Any] = {
            "ready": True,
            "checks": [],
            "api_url": self._api_url,
            "warnings": [],
            "errors": [],
        }

        # Check 1: API connectivity
        try:
            result = await self._request("GET", "/health")
            report["checks"].append({
                "name": "api_service",
                "status": "pass",
                "message": f"API reachable at {self._api_url}",
            })
        except SkillBrowserError as e:
            report["ready"] = False
            report["checks"].append({
                "name": "api_service",
                "status": "fail",
                "message": str(e),
            })
            report["errors"].append(
                f"Browser service not reachable at {self._api_url}. "
                f"Edit agent_browser/skill/config.yaml to set service.url, "
                f"or pass api_url to SkillBrowser()."
            )

        # Check 2: API key configured (warning only)
        if not self._api_key:
            report["checks"].append({
                "name": "api_auth",
                "status": "warn",
                "message": "No API key configured — server may require authentication",
            })
            report["warnings"].append(
                "Set api_key in agent_browser/skill/config.yaml "
                "or pass to SkillBrowser()"
            )
        else:
            report["checks"].append({
                "name": "api_auth",
                "status": "pass",
                "message": "API key configured",
            })

        # Check 3: LLM API key (for Agent mode, warning only)
        has_llm_key = bool(
            os.getenv("OPENAI_API_KEY")
            or os.getenv("ANTHROPIC_API_KEY")
            or os.getenv("GLM_API_KEY")
        )
        if has_llm_key:
            report["checks"].append({
                "name": "llm_api_key",
                "status": "pass",
                "message": "LLM API key found (Agent mode available)",
            })
        else:
            report["checks"].append({
                "name": "llm_api_key",
                "status": "warn",
                "message": "No LLM API key — Agent mode unavailable, ReAct mode works without it",
            })
            report["warnings"].append(
                "Set OPENAI_API_KEY / ANTHROPIC_API_KEY / GLM_API_KEY for Agent mode"
            )

        return report

    # ── Session Management ─────────────────────────────────────────

    def _load_cached_session(self) -> str | None:
        """Load persisted session_id from cache file (keyed by api_url + api_key)."""
        try:
            if SESSION_CACHE_PATH.exists():
                data = json.loads(SESSION_CACHE_PATH.read_text())
                cache_key = f"{self._api_url}:{self._api_key}"
                return data.get(cache_key)
        except Exception:
            pass
        return None

    def _save_cached_session(self, session_id: str) -> None:
        """Persist session_id to cache file."""
        try:
            data: dict = {}
            if SESSION_CACHE_PATH.exists():
                data = json.loads(SESSION_CACHE_PATH.read_text())
            cache_key = f"{self._api_url}:{self._api_key}"
            data[cache_key] = session_id
            SESSION_CACHE_PATH.write_text(json.dumps(data))
        except Exception:
            pass

    def _clear_cached_session(self) -> None:
        """Remove cached session_id for current api_url + api_key."""
        try:
            if SESSION_CACHE_PATH.exists():
                data = json.loads(SESSION_CACHE_PATH.read_text())
                cache_key = f"{self._api_url}:{self._api_key}"
                data.pop(cache_key, None)
                SESSION_CACHE_PATH.write_text(json.dumps(data))
        except Exception:
            pass

    async def create_session(self, user_id: str = "") -> str:
        """Create a new browser session, reusing a cached session if still valid.

        Checks the local session cache first. If a cached session_id exists and
        is still alive on the server, returns it directly without creating a new
        one. Otherwise creates a new session and caches the result.

        Args:
            user_id: Optional user identifier for the session.

        Returns:
            The session ID string.
        """
        # Try to reuse cached session
        cached_sid = self._load_cached_session()
        if cached_sid:
            try:
                await self._request("GET", f"/sessions/{cached_sid}")
                logger.info("Reusing cached session: %s", cached_sid)
                return cached_sid
            except SkillBrowserError:
                logger.info("Cached session expired, creating new one")
                self._clear_cached_session()

        import re
        import uuid

        body: dict[str, Any] = {"user_id": user_id or f"skill_{uuid.uuid4().hex[:8]}"}
        try:
            result = await self._request("POST", "/sessions/create", body)
        except SkillBrowserError as e:
            err_str = str(e)
            # 409: session already exists — verify alive, reuse or delete+wait+retry
            if "409" in err_str:
                m = re.search(r"key bound to ([A-Za-z0-9_]+)", err_str)
                candidate_sid = m.group(1) if m else None
                if candidate_sid:
                    try:
                        await self._request("GET", f"/sessions/{candidate_sid}")
                        self._save_cached_session(candidate_sid)
                        logger.info("Reusing existing session: %s", candidate_sid)
                        return candidate_sid
                    except SkillBrowserError:
                        logger.info("409 session %s is dead, deleting and retrying", candidate_sid)
                        try:
                            await self._request("DELETE", f"/sessions/{candidate_sid}")
                        except Exception:
                            pass
                        await asyncio.sleep(1)
                        result = await self._request("POST", "/sessions/create", body)
                        sid = result.get("session_id", result.get("id", ""))
                        if not sid:
                            raise SkillBrowserError(f"create_session returned no session_id: {result}")
                        self._save_cached_session(sid)
                        logger.info("Session created after 409 cleanup: %s", sid)
                        return sid
                # Fallback: list sessions and find by user_id
                try:
                    all_sessions = await self._request("GET", "/sessions")
                    for s in all_sessions.get("sessions", []):
                        if s.get("user_id") == body["user_id"]:
                            sid = s["session_id"]
                            self._save_cached_session(sid)
                            logger.info("Reusing existing session from list: %s", sid)
                            return sid
                except Exception:
                    pass
            # 503: pool exhausted — only clean up current user's sessions, then retry
            if "503" in err_str:
                target_uid = body["user_id"]
                logger.warning("Pool full, cleaning sessions for user=%s", target_uid)
                try:
                    all_sessions = await self._request("GET", "/sessions")
                    for s in all_sessions.get("sessions", []):
                        if s.get("user_id") == target_uid:
                            try:
                                await self._request("DELETE", f"/sessions/{s['session_id']}")
                                logger.info("Deleted session: %s", s["session_id"])
                            except Exception:
                                pass
                except Exception:
                    pass
                await asyncio.sleep(1)
                result = await self._request("POST", "/sessions/create", body)
            else:
                raise

        sid = result.get("session_id", result.get("id", ""))
        if not sid:
            raise SkillBrowserError(
                f"create_session returned no session_id: {result}"
            )
        self._save_cached_session(sid)
        logger.info("Session created: %s", sid)
        return sid

    async def delete_session(self, session_id: str) -> None:
        """Delete a session and release browser resources.

        Args:
            session_id: Session ID to delete.
        """
        self._clear_cached_session()
        try:
            await self._request("DELETE", f"/sessions/{session_id}")
            logger.info("Session deleted: %s", session_id)
        except SkillBrowserError as e:
            if e.status_code == 404:
                logger.warning("Session not found (may already be deleted): %s", session_id)
            else:
                raise

    # ── Navigation ──────────────────────────────────────────────────

    async def open_page(self, session_id: str, url: str) -> None:
        """Navigate the browser to *url*.

        Args:
            session_id: Session ID.
            url: Target URL.
        """
        await self._request(
            "POST",
            f"/sessions/{session_id}/navigate",
            {"url": url},
        )

    async def go_back(self, session_id: str) -> None:
        """Navigate back in browser history.

        Args:
            session_id: Session ID.
        """
        await self._request("POST", f"/sessions/{session_id}/back")

    # ── Observation (ReAct Core) ──────────────────────────────────────

    async def snapshot(
        self,
        session_id: str,
        interactive_only: bool = False,
        iframe_selector: str | None = None,
    ) -> dict[str, Any]:
        """Get page snapshot with @eN element references.

        Args:
            session_id: Session ID.
            interactive_only: If True, only include interactive elements.
            iframe_selector: CSS selector for iframes to penetrate (e.g. ``"iframe"``,
                ``"#my-frame"``). When set, elements inside matching iframes are
                included with viewport-absolute bounding_box coordinates and an
                ``iframe`` field identifying the frame. Cross-origin iframes are
                silently skipped.

        Returns:
            Dict with ``url``, ``title``, ``elements`` (list of
            ``{ref, text, role, bounding_box, iframe?}`` dicts).
        """
        params: dict[str, Any] = {"interactive_only": interactive_only}
        if iframe_selector is not None:
            params["iframe_selector"] = iframe_selector
        return await self._request(
            "POST",
            f"/sessions/{session_id}/snapshot",
            params,
        )

    # ── Interaction ─────────────────────────────────────────────────

    async def click(
        self,
        session_id: str,
        ref: str | None = None,
        x: float | None = None,
        y: float | None = None,
    ) -> None:
        """Click an element by @eN ref or viewport coordinates.

        Args:
            session_id: Session ID.
            ref: Element reference string (``@eN``).
            x: Viewport X coordinate (alternative to ref).
            y: Viewport Y coordinate (alternative to ref).
        """
        body: dict[str, Any] = {}
        if ref:
            body["ref"] = ref
        if x is not None and y is not None:
            body["x"] = x
            body["y"] = y
        if not body:
            raise ValueError("click requires either 'ref' or both 'x' and 'y'")
        await self._request("POST", f"/sessions/{session_id}/click", body)

    async def fill(
        self, session_id: str, ref: str, text: str
    ) -> None:
        """Fill an input element with text.

        Args:
            session_id: Session ID.
            ref: Element reference (``@eN``).
            text: Text to type into the element.
        """
        await self._request(
            "POST",
            f"/sessions/{session_id}/fill",
            {"ref": ref, "text": text},
        )

    async def scroll(
        self,
        session_id: str,
        direction: str = "down",
        amount: int = 500,
    ) -> None:
        """Scroll the page.

        Args:
            session_id: Session ID.
            direction: ``"down"`` or ``"up"``.
            amount: Pixels to scroll (default 500).
        """
        await self._request(
            "POST",
            f"/sessions/{session_id}/scroll",
            {"direction": direction, "amount": amount},
        )

    async def press_key(self, session_id: str, key: str) -> None:
        """Press a keyboard key.

        Args:
            session_id: Session ID.
            key: Key name (``"Enter"``, ``"Tab"``, ``"Escape"``, etc.).
        """
        await self._request(
            "POST",
            f"/sessions/{session_id}/keyboard/press",
            {"key": key},
        )

    async def wait_for_selector(
        self,
        session_id: str,
        selector: str,
        timeout: int = 10000,
    ) -> None:
        """Wait for a CSS selector to appear.

        Args:
            session_id: Session ID.
            selector: CSS selector string.
            timeout: Maximum wait time in milliseconds (default 10000).
        """
        await self._request(
            "POST",
            f"/sessions/{session_id}/wait",
            {"selector": selector, "timeout": timeout},
        )

    # ── JavaScript Execution ─────────────────────────────────────────

    async def evaluate(
        self, session_id: str, expression: str
    ) -> Any:
        """Execute JavaScript in the page context.

        Args:
            session_id: Session ID.
            expression: JavaScript expression to evaluate.

        Returns:
            The evaluation result.
        """
        result = await self._request(
            "POST",
            f"/sessions/{session_id}/evaluate",
            {"expression": expression},
        )
        return result.get("result")

    async def evaluate_with_retry(
        self,
        session_id: str,
        expression: str,
        retries: int = 3,
        delay: float = 1.0,
    ) -> Any:
        """Execute JavaScript with automatic retry on transient failures.

        Args:
            session_id: Session ID.
            expression: JavaScript expression to evaluate.
            retries: Maximum number of attempts.
            delay: Seconds to wait between retries.

        Returns:
            The evaluation result.
        """
        for attempt in range(retries):
            try:
                return await self.evaluate(session_id, expression)
            except SkillBrowserError:
                if attempt == retries - 1:
                    raise
                logger.warning(
                    "evaluate failed (attempt %d/%d), retrying in %.1fs",
                    attempt + 1, retries, delay,
                )
                await asyncio.sleep(delay)

    # ── Agent Mode ───────────────────────────────────────────────────

    async def run_task(
        self,
        session_id: str,
        task: str,
        intelligence: str | None = None,
        max_steps: int = 6,
        total_timeout: float = 300.0,
        poll_interval: float = 5.0,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        """Submit an Agent task and poll for completion.

        Args:
            session_id: Session ID.
            task: Natural language description of what to do.
            intelligence: ``"agent"`` or ``"llm"``. Defaults to config.yaml
                setting (``intelligence`` field), or ``"llm"`` if not configured.
            max_steps: Maximum agent steps per chunk (default 6).
            total_timeout: Max wall-clock seconds (default 300).
            poll_interval: Seconds between status polls (default 5).

        Returns:
            Result dict with ``status``, ``result``, ``steps``, etc.
        """
        # Use config default if not specified
        if intelligence is None:
            intelligence = self._intelligence

        # Submit task
        submit_body: dict[str, Any] = {
            "task": task,
            "intelligence": intelligence,
            "max_steps": max_steps,
        }
        result = await self._request(
            "POST",
            f"/sessions/{session_id}/task",
            submit_body,
        )
        task_id = result.get("task_id")
        if not task_id:
            return {
                "status": "failed",
                "error": "No task_id returned from server",
                "response": result,
            }

        # Poll for completion
        import time

        start = time.time()
        while time.time() - start < total_timeout:
            await asyncio.sleep(poll_interval)
            status = await self._request(
                "GET",
                f"/sessions/{session_id}/tasks/{task_id}",
            )
            state = status.get("status", "running")
            if state in ("completed", "failed", "stuck", "timeout"):
                return status

        return {
            "status": "timeout",
            "task_id": task_id,
            "message": f"Task did not complete within {total_timeout}s",
        }

    # ── Info ─────────────────────────────────────────────────────────

    @property
    def api_url(self) -> str:
        """The configured API endpoint URL."""
        return self._api_url

    async def get_session_info(self, session_id: str) -> dict[str, Any]:
        """Get full session info including noVNC URL.

        Args:
            session_id: Session ID.

        Returns:
            Dict with session details and ``browser_node`` containing
            ``novnc_url`` if available.
        """
        return await self._request("GET", f"/sessions/{session_id}")


# ── Error ───────────────────────────────────────────────────────────


class SkillBrowserError(Exception):
    """Structured error from SkillBrowser operations."""

    def __init__(
        self,
        message: str,
        status_code: int = 0,
        url: str = "",
    ):
        super().__init__(message)
        self.status_code = status_code
        self.url = url

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": str(self),
            "status_code": self.status_code,
            "url": self.url,
        }
