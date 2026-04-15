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

    async def create_session(
        self,
        user_id: str = "",
        *,
        viewport: dict | None = None,
        proxy: dict | None = None,
        user_agent: str | None = None,
        headless: bool | None = None,
        allowed_domains: list[str] | None = None,
        prohibited_domains: list[str] | None = None,
        enable_extensions: bool | None = None,
        demo_mode: bool | None = None,
        device_scale_factor: float | None = None,
    ) -> str:
        """Create a new browser session, reusing a cached session if still valid.

        Checks the local session cache first. If a cached session_id exists and
        is still alive on the server, returns it directly without creating a new
        one. Otherwise creates a new session and caches the result.

        Args:
            user_id: Optional user identifier for the session.
            viewport: Viewport size dict ``{width, height}``.
            proxy: Proxy config dict ``{server, username?, password?}``.
            user_agent: Custom User-Agent string.
            headless: Run browser in headless mode.
            allowed_domains: Only allow navigation to these domain patterns.
            prohibited_domains: Block navigation to these domain patterns.
            enable_extensions: Enable Chrome extensions.
            demo_mode: Demo mode (highlights elements, slows actions).
            device_scale_factor: Device scale factor (e.g. 2.0 for Retina).

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
        # Forward optional profile params to API
        for key, val in [
            ("viewport", viewport),
            ("proxy", proxy),
            ("user_agent", user_agent),
            ("headless", headless),
            ("allowed_domains", allowed_domains),
            ("prohibited_domains", prohibited_domains),
            ("enable_extensions", enable_extensions),
            ("demo_mode", demo_mode),
            ("device_scale_factor", device_scale_factor),
        ]:
            if val is not None:
                body[key] = val
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

    # ── New Actions (browser-use coverage) ─────────────────────────

    async def search_page(
        self,
        session_id: str,
        pattern: str,
        case_sensitive: bool = False,
        is_regex: bool = False,
        max_results: int = 10,
        context_chars: int = 100,
        css_scope: str | None = None,
    ) -> dict:
        """Search page text content using regex or plain text.

        Args:
            session_id: Session ID.
            pattern: Search pattern (regex or plain text).
            case_sensitive: Case-sensitive search (default False).
            is_regex: Treat pattern as regex (default False).
            max_results: Max matches to return (default 10).
            context_chars: Context characters around each match (default 100).
            css_scope: Limit search to this CSS subtree (default entire page).

        Returns:
            Dict with ``matches`` list and ``total`` count.
        """
        return await self._request("POST", f"/sessions/{session_id}/search", {
            "pattern": pattern,
            "case_sensitive": case_sensitive,
            "is_regex": is_regex,
            "max_results": max_results,
            "context_chars": context_chars,
            "css_scope": css_scope,
        })

    async def find_elements(
        self,
        session_id: str,
        selector: str,
        max_results: int = 50,
    ) -> dict:
        """Find elements matching a CSS selector with metadata.

        Args:
            session_id: Session ID.
            selector: CSS selector string.
            max_results: Max elements to return (default 50).

        Returns:
            Dict with ``elements`` list and ``total`` count.
        """
        return await self._request("POST", f"/sessions/{session_id}/find_elements", {
            "selector": selector,
            "max_results": max_results,
        })

    async def get_dropdown_options(self, session_id: str, ref: str) -> list[dict]:
        """Get options from a <select> element.

        Args:
            session_id: Session ID.
            ref: Element reference (``@eN``).

        Returns:
            List of ``{index, value, text, selected, disabled}`` dicts.
        """
        result = await self._request("POST", f"/sessions/{session_id}/dropdown/options", {"ref": ref})
        return result.get("options", [])

    async def select_dropdown_option(self, session_id: str, ref: str, option_text: str) -> None:
        """Select a dropdown option by visible text.

        Args:
            session_id: Session ID.
            ref: Element reference (``@eN``).
            option_text: Visible text of option to select.
        """
        await self._request("POST", f"/sessions/{session_id}/dropdown/select", {
            "ref": ref,
            "option_text": option_text,
        })

    async def upload_file(self, session_id: str, ref: str, file_paths: list[str]) -> None:
        """Upload files to an <input type=file> element.

        Args:
            session_id: Session ID.
            ref: Element reference (``@eN``).
            file_paths: List of absolute file paths.
        """
        await self._request("POST", f"/sessions/{session_id}/upload", {
            "ref": ref,
            "file_paths": file_paths,
        })

    async def screenshot(
        self,
        session_id: str,
        ref: str | None = None,
        full_page: bool = True,
        format: str = "png",
        quality: int | None = None,
    ) -> dict:
        """Take a screenshot of page or element.

        **IMPORTANT**: This method is expensive (transfers base64 image data).
        Only call it when the user **explicitly asks** to see the page
        ("截图", "截屏", "screenshot", "show me the page", "看看页面").
        For all automated observation in ReAct loops, use ``snapshot()`` instead.

        Args:
            session_id: Session ID.
            ref: Element reference for element screenshot (None = full page).
            full_page: Capture full page scroll (default True).
            format: Image format (``png`` or ``jpeg``, default ``png``).
            quality: JPEG quality 0-100 (only for jpeg format, default None).

        Returns:
            Dict with ``image`` (base64), ``format``, and ``size``.
        """
        body: dict[str, Any] = {"full_page": full_page, "format": format}
        if ref is not None:
            body["ref"] = ref
        if quality is not None:
            body["quality"] = quality
        return await self._request("POST", f"/sessions/{session_id}/screenshot", body)

    async def save_as_pdf(
        self,
        session_id: str,
        output_path: str | None = None,
        landscape: bool = False,
    ) -> dict:
        """Save current page as PDF.

        Args:
            session_id: Session ID.
            output_path: Output file path (auto-generated if None).
            landscape: Landscape orientation (default False).

        Returns:
            Dict with ``path`` to saved PDF.
        """
        body: dict[str, Any] = {"landscape": landscape}
        if output_path is not None:
            body["output_path"] = output_path
        return await self._request("POST", f"/sessions/{session_id}/pdf", body)

    async def send_keys(self, session_id: str, keys: str) -> None:
        """Send complex key sequence (e.g., 'Meta+a', 'Shift+Home').

        Args:
            session_id: Session ID.
            keys: Key sequence with optional modifiers.
        """
        await self._request("POST", f"/sessions/{session_id}/keys/send", {"keys": keys})

    async def scroll_to_text(self, session_id: str, text: str, max_scrolls: int = 10) -> bool:
        """Scroll until text becomes visible.

        Args:
            session_id: Session ID.
            text: Text to find.
            max_scrolls: Max scroll attempts (default 10).

        Returns:
            True if text was found and made visible.
        """
        result = await self._request("POST", f"/sessions/{session_id}/scroll/text", {
            "text": text,
            "max_scrolls": max_scrolls,
        })
        return result.get("found", False)

    async def switch_tab(self, session_id: str, index: int) -> None:
        """Switch to tab by index.

        Args:
            session_id: Session ID.
            index: Tab index (0-based).
        """
        await self._request("POST", f"/sessions/{session_id}/tabs/switch", {"index": index})

    async def open_tab(self, session_id: str, url: str | None = None) -> int:
        """Open new tab. Optionally navigate to URL.

        Args:
            session_id: Session ID.
            url: URL to navigate to (None = blank tab).

        Returns:
            Index of new tab.
        """
        result = await self._request("POST", f"/sessions/{session_id}/tabs/open", {
            "url": url,
        } if url else None)
        return result.get("index", 0)

    async def close_tab(self, session_id: str, index: int | None = None) -> None:
        """Close tab by index (closes last tab if index is None).

        Args:
            session_id: Session ID.
            index: Tab index (None = last tab).
        """
        body = {"index": index} if index is not None else {}
        await self._request("POST", f"/sessions/{session_id}/tabs/close", body)

    async def get_tabs_info(self, session_id: str) -> list[dict]:
        """Get info about all open tabs.

        Args:
            session_id: Session ID.

        Returns:
            List of ``{index, url, title}`` dicts.
        """
        result = await self._request("GET", f"/sessions/{session_id}/tabs")
        return result.get("tabs", [])

    async def extract_content(
        self,
        session_id: str,
        selector: str | None = None,
        extract_type: str = "text",
    ) -> str:
        """Extract content from page or element.

        Args:
            session_id: Session ID.
            selector: CSS scope (None = entire page).
            extract_type: ``text``, ``html``, ``links``, ``images`` (default ``text``).

        Returns:
            Extracted content string.
        """
        result = await self._request("POST", f"/sessions/{session_id}/extract", {
            "selector": selector,
            "extract_type": extract_type,
        })
        return result.get("content", "")

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
        agent_config: dict[str, Any] | None = None,
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
            agent_config: Agent mode configuration dict. Keys match ``AgentConfig`` fields:
                ``enable_planning``, ``use_judge``, ``use_thinking``,
                ``message_compaction``, ``max_failures``, ``llm_timeout``,
                ``step_timeout``, ``use_vision``, ``flash_mode``,
                ``override_system_message``, ``extend_system_message``,
                ``fallback_llm_model``, ``calculate_cost``, etc.

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
        if agent_config:
            submit_body["agent_config"] = agent_config
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
        """Get full session info including VNC URL.

        Args:
            session_id: Session ID.

        Returns:
            Dict with session details. Top-level fields include
            ``vnc_url`` (noVNC proxy URL) and ``vnc_token``.
            ``browser_node`` contains instance details (may also include
            ``novnc_url`` for K8s/Docker deployments).
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
