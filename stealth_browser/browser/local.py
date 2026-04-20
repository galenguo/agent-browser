"""Local CDP backend -- wraps BrowserController + BrowserDaemon for direct CDP access."""

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from playwright.async_api import Browser, Page, Playwright, async_playwright

from stealth_browser.config import SkillConfig
from stealth_browser.utils.refs_generator import generate_refs

from . import BrowserBackend, BrowserPageHandle

logger = logging.getLogger(__name__)


class PlaywrightPageHandle(BrowserPageHandle):
    """Thin wrapper around Playwright Page implementing BrowserPageHandle interface.

    Delegates ~95% to the underlying Playwright Page object.
    """

    def __init__(self, page: Page):
        self._page = page
        self._listeners: dict[str, list] = {}

    @property
    def raw_page(self) -> Page:
        """Expose raw Playwright Page (for scenarios needing Playwright-specific features)."""
        return self._page

    async def goto(self, url: str, wait_until: str = "domcontentloaded", timeout: int = 8000) -> None:
        await self._page.goto(url, wait_until=wait_until, timeout=timeout)

    async def go_back(self, wait_until: str = "domcontentloaded", timeout: int = 10000) -> None:
        await self._page.go_back(wait_until=wait_until, timeout=timeout)

    async def evaluate(self, expression: str) -> Any:
        return await self._page.evaluate(expression)

    async def wait_for_selector(self, selector: str, timeout: int = 10000) -> None:
        await self._page.wait_for_selector(selector, timeout=timeout)

    async def mouse_wheel(self, delta_x: int, delta_y: int) -> None:
        await self._page.mouse.wheel(delta_x, delta_y)

    async def mouse_move(self, x: float, y: float) -> None:
        await self._page.mouse.move(x, y)

    async def keyboard_press(self, key: str) -> None:
        await self._page.keyboard.press(key)

    async def title(self) -> str:
        return await self._page.title()

    async def url(self) -> str:
        return self._page.url

    async def on(self, event: str, handler: Callable) -> None:
        self._page.on(event, handler)
        if event not in self._listeners:
            self._listeners[event] = []
        self._listeners[event].append(handler)

    def remove_listener(self, event: str, handler: Callable) -> None:
        self._page.remove_listener(event, handler)
        if event in self._listeners:
            self._listeners[event] = [h for h in self._listeners[event] if h != handler]

    async def close(self) -> None:
        with contextlib.suppress(Exception):
            await self._page.close()


@dataclass
class LocalSession:
    """Local session data container."""

    page_handle: PlaywrightPageHandle
    browser_context: Any  # BrowserContext
    dom_indices: list[int]
    snapshot_cache: dict | None = None


class LocalCDPBackend(BrowserBackend):
    """Local CDP backend -- the sole core implementation for browser operations.

    - Connects to local CloakBrowser via Playwright connect_over_cdp
    - Uses BrowserDaemon for persistent connections when daemon_enabled
    - Integrates StealthEnhancer for anti-detection enhancements
    - Supports LLM mode (atomic operations) and Agent mode (browser-use Agent)
    """

    def __init__(self, config: SkillConfig):
        self._config = config
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._sessions: dict[str, LocalSession] = {}
        self._stealth = None
        self._daemon = None
        self._browser_process = None  # Auto-launched browser subprocess

        # Daemon persistence (optional)
        if config.daemon_enabled:
            try:
                from stealth_browser.browser.daemon import BrowserDaemon

                self._daemon = BrowserDaemon.get(config)
                logger.info("BrowserDaemon enabled")
            except Exception as e:
                logger.debug(f"BrowserDaemon not available: {e}")

        # Lazy init StealthEnhancer
        if config.stealth_enabled:
            try:
                from stealth_browser.stealth.enhancer import StealthEnhancer
                from stealth_browser.stealth.profiles import profile_from_env

                self._stealth = StealthEnhancer(profile=profile_from_env())
            except ImportError:
                logger.debug("StealthEnhancer not available")

    async def _is_cdp_reachable(self) -> bool:
        """Check whether the CDP endpoint is reachable."""
        import aiohttp

        cdp_url = self._config.cdp_url
        # Convert to HTTP URL for health check
        if cdp_url.startswith("ws://"):
            health_url = "http://" + cdp_url[5:] + "/json/version"
        else:
            health_url = cdp_url.replace("http://", "http://") + "/json/version"

        try:
            async with (
                aiohttp.ClientSession() as session,
                session.get(health_url, timeout=aiohttp.ClientTimeout(total=2)) as resp,
            ):
                return resp.status == 200
        except Exception:
            return False

    @staticmethod
    async def ensure_cloakbrowser_installed() -> bool:
        """Check if CloakBrowser is installed; auto-download if missing.

        Returns True if already installed or installation succeeded.
        """
        try:
            import cloakbrowser

            logger.debug(f"CloakBrowser found: {getattr(cloakbrowser, '__version__', 'unknown')}")
            return True
        except ImportError:
            pass

        logger.info("CloakBrowser not installed, attempting auto-install...")
        import sys

        try:
            result = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "pip",
                "install",
                "cloakbrowser==0.3.18",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _stdout, stderr = await result.communicate(timeout=120)

            if result.returncode != 0:
                logger.error(f"pip install cloakbrowser failed (rc={result.returncode}):")
                if stderr:
                    logger.error(stderr.decode().strip()[-500:])
                return False

            logger.info("CloakBrowser installed successfully")
            return True

        except Exception as e:
            logger.error(f"Auto-install CloakBrowser failed: {e}")
            return False

    async def _launch_browser(self) -> None:
        """Auto-launch CloakBrowser as a subprocess."""
        import sys

        logger.info("Auto-starting CloakBrowser...")

        # Launch CloakBrowser subprocess
        try:
            self._browser_process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "cloakbrowser.launch",
                "--port",
                "19222",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            logger.info(f"CloakBrowser process started (PID: {self._browser_process.pid})")
        except Exception as e:
            logger.error(f"Failed to launch CloakBrowser: {e}")
            raise

        # Wait for CDP endpoint to become available (up to 30 seconds)
        for _attempt in range(30):
            await asyncio.sleep(1)
            if await self._is_cdp_reachable():
                logger.info("CloakBrowser CDP endpoint ready")
                return

        # Timeout -- clean up subprocess
        if self._browser_process:
            self._browser_process.kill()
            await self._browser_process.wait()
            self._browser_process = None
        raise TimeoutError("CloakBrowser failed to start within 30 seconds")

    async def connect(self) -> None:
        """Connect to CDP endpoint (with retry + auto-launch of browser)."""
        # Daemon path: use BrowserDaemon persistent connection
        if self._daemon:
            await self._daemon.ensure_connected()
            self._browser = self._daemon.browser
            return

        # Non-daemon path: direct connection
        if self._browser:
            try:
                _ = self._browser.contexts  # Liveness check
                return
            except Exception:
                self._browser = None

        # Auto-launch browser if CDP is unreachable
        if not await self._is_cdp_reachable():
            # Ensure CloakBrowser is installed first (Phase 1.5: auto-download)
            if not await self.ensure_cloakbrowser_installed():
                raise RuntimeError(
                    "CloakBrowser not installed and auto-install failed. Run: pip install cloakbrowser==0.3.18"
                )
            await self._launch_browser()

        if not self._playwright:
            self._playwright = await async_playwright().start()

        cdp_url = self._config.cdp_url
        # Playwright connect_over_cdp needs HTTP URL
        if cdp_url.startswith("ws://"):
            cdp_url = "http://" + cdp_url[5:]

        retries = 3
        for attempt in range(retries):
            try:
                self._browser = await self._playwright.chromium.connect_over_cdp(cdp_url)
                logger.info(f"Connected to CDP: {cdp_url}")
                return
            except Exception:
                if attempt < retries - 1:
                    await asyncio.sleep(0.3 * (attempt + 1))
                else:
                    raise

    async def disconnect(self) -> None:
        """Disconnect browser connection (clean up subprocess)."""
        # Close all sessions first
        for sid in list(self._sessions.keys()):
            await self.delete_session(sid)

        if self._daemon:
            await self._daemon.disconnect()
            self._browser = None
            return

        # Clean up browser subprocess (if auto-started)
        if self._browser_process:
            try:
                logger.info(f"Terminating auto-started browser process (PID: {self._browser_process.pid})")
                self._browser_process.terminate()
                await asyncio.wait_for(self._browser_process.wait(), timeout=5)
            except TimeoutError:
                logger.warning("Browser process did not terminate gracefully, killing...")
                self._browser_process.kill()
                await self._browser_process.wait()
            except Exception as e:
                logger.debug(f"Error terminating browser process: {e}")
            finally:
                self._browser_process = None

        if self._browser:
            with contextlib.suppress(Exception):
                await self._browser.close()
            self._browser = None

        if self._playwright:
            with contextlib.suppress(Exception):
                await self._playwright.stop()
            self._playwright = None

    async def is_connected(self) -> bool:
        if self._daemon:
            return self._daemon.is_connected
        if not self._browser:
            return False
        try:
            _ = self._browser.contexts
            return True
        except Exception:
            return False

    async def create_session(self, session_id: str) -> PlaywrightPageHandle:
        """Create a browser session."""
        await self.connect()

        # Daemon path: use daemon's context management
        if self._daemon:
            context, page = await self._daemon.create_context(session_id)
            if self._stealth:
                from stealth_browser.stealth.enhancer import StealthEnhancer
                from stealth_browser.stealth.patches import inject_stealth_patches

                await inject_stealth_patches(page)  # JS property-level stealth patches
                await StealthEnhancer.inject_timing_noise(page)  # Timing noise injection
            page_handle = PlaywrightPageHandle(page)
            self._sessions[session_id] = LocalSession(
                page_handle=page_handle,
                browser_context=context,
                dom_indices=[],
            )
            logger.info(f"Session created (daemon): {session_id}")
            return page_handle

        # Non-daemon path
        context = await self._browser.new_context(ignore_https_errors=True)
        page = await context.new_page()

        # Inject stealth enhancements
        if self._stealth:
            from stealth_browser.stealth.enhancer import StealthEnhancer
            from stealth_browser.stealth.patches import inject_stealth_patches

            await inject_stealth_patches(page)  # JS property-level stealth patches
            await StealthEnhancer.inject_timing_noise(page)  # Timing noise injection

        page_handle = PlaywrightPageHandle(page)
        self._sessions[session_id] = LocalSession(
            page_handle=page_handle,
            browser_context=context,
            dom_indices=[],
        )

        logger.info(f"Session created: {session_id}")
        return page_handle

    async def delete_session(self, session_id: str) -> None:
        """Delete a browser session."""
        session = self._sessions.pop(session_id, None)
        if not session:
            return

        # Daemon path: let daemon manage context lifecycle
        if self._daemon:
            await self._daemon.destroy_context(session_id)
            logger.info(f"Session deleted (daemon): {session_id}")
            return

        # Non-daemon path
        with contextlib.suppress(Exception):
            await session.page_handle.close()
        with contextlib.suppress(Exception):
            await session.browser_context.close()
        logger.info(f"Session deleted: {session_id}")

    async def register_session(
        self,
        session_id: str,
        page: "Page",
        browser_context: Any | None = None,
    ) -> None:
        """Register externally-managed session (from SessionPoolManager).

        Wraps the given Playwright Page in a LocalSession, enabling
        pool_manager to delegate operations to this backend.
        Lifecycle (connect/close) is managed by the external caller.
        """
        page_handle = PlaywrightPageHandle(page)
        self._sessions[session_id] = LocalSession(
            page_handle=page_handle,
            browser_context=browser_context or page.context,
            dom_indices=[],
        )
        logger.info(f"External session registered: {session_id}")

    def unregister_session(self, session_id: str) -> None:
        """Unregister an externally-managed session without closing the page.

        Lifecycle is managed by the external caller (pool_manager).
        """
        self._sessions.pop(session_id, None)

    async def get_page(self, session_id: str) -> PlaywrightPageHandle:
        """Get the page handle for a session."""
        if session_id not in self._sessions:
            raise ValueError(f"Session {session_id} not found")
        return self._sessions[session_id].page_handle

    # -- Snapshot / refs methods (compatible with existing controller.py) --

    async def snapshot(self, session_id: str, interactive_only: bool = False) -> dict:
        """Get page snapshot (backward-compatible API)."""
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        # Use cache when possible
        if session.snapshot_cache and not interactive_only:
            result = session.snapshot_cache
            session.snapshot_cache = None
            return result

        page = session.page_handle.raw_page
        elements, dom_indices, page_info = await generate_refs(page, interactive_only)
        session.dom_indices = dom_indices

        return {
            "url": page_info["href"],
            "title": page_info["title"],
            "elements": elements,
        }

    async def cache_snapshot_after_open(self, session_id: str) -> None:
        """Pre-compute snapshot cache after open_page."""
        session = self._sessions.get(session_id)
        if not session:
            return

        try:
            page = session.page_handle.raw_page
            elements, dom_indices, page_info = await generate_refs(page, False)
            session.dom_indices = dom_indices
            session.snapshot_cache = {
                "url": page_info["href"],
                "title": page_info["title"],
                "elements": elements,
            }
        except Exception:
            session.snapshot_cache = None

    def get_dom_indices(self, session_id: str) -> list[int]:
        """Get DOM indices for a session."""
        session = self._sessions.get(session_id)
        return session.dom_indices if session else []

    async def stealth_delay(self, action_type: str = "general") -> None:
        """Apply stealth delay before an action."""
        if self._stealth:
            await self._stealth.pre_action(action_type)

    async def stealth_mouse_move(self, session_id: str) -> None:
        """Apply stealth mouse movement."""
        if self._stealth:
            session = self._sessions.get(session_id)
            if session:
                await self._stealth.random_mouse_move(session.page_handle.raw_page)

    async def run_task(
        self,
        session_id: str,
        task: str,
        intelligence: str = "agent",
        llm_config: dict | None = None,
        max_steps: int = 6,
        total_timeout: float = 300.0,
        **kwargs,
    ) -> dict:
        """Execute Agent-mode task (local CDP).

        Uses browser-use Agent via existing CDP URL to autonomously complete tasks.
        Each chunk runs at most max_steps steps, up to MAX_CHUNKS chunks.
        total_timeout: overall timeout in seconds (default 300s / 5 min), prevents infinite blocking.
        """
        if intelligence != "agent":
            return {
                "status": "ready",
                "mode": "llm",
                "session_id": session_id,
                "tools": ["snapshot", "click", "fill", "scroll", "go_back", "hover", "press_key"],
            }

        try:
            from browser_use import Agent
            from browser_use.browser.profile import BrowserProfile
            from browser_use.browser.session import BrowserSession as BUSession
        except ImportError:
            return {
                "status": "failed",
                "error": "browser-use not installed. Run: pip install browser-use==0.12.2",
            }

        if session_id not in self._sessions:
            return {"status": "failed", "error": f"Session {session_id} not found"}

        # LLM instance
        llm = self._create_llm(llm_config)

        # browser-use creates its own connection via CDP URL (needs independent BrowserSession)
        cdp_url = self._config.cdp_url
        browser_profile = BrowserProfile(
            cdp_url=cdp_url,
            is_local=True,
            headless=False,
            highlight_elements=True,
            minimum_wait_page_load_time=0.5,
            wait_for_network_idle_page_load_time=1.0,
        )

        all_results = []
        stuck_count = 0
        total_steps = 0
        MAX_CHUNKS = 2

        try:
            browser_session = BUSession(browser_profile=browser_profile)

            async def _run_chunks():
                """Internal: execute agent task in chunks (controllable by total_timeout)."""
                nonlocal browser_session

                # Inject stealth actions (override browser-use default navigate/input/click)
                controller = None
                if self._stealth:
                    try:
                        from browser_use.tools.service import Tools

                        from stealth_browser.stealth.actions import register_stealth_actions

                        controller = Tools(browser_session)
                        register_stealth_actions(controller, self._stealth)
                        logger.info("Stealth actions registered for agent mode")
                    except Exception as e:
                        logger.warning(f"Failed to register stealth actions: {e} (using default actions)")

                last_result_text = ""
                total_steps = 0
                for chunk_num in range(1, MAX_CHUNKS + 1):
                    if chunk_num == 1:
                        current_task = f"{task}\nAfter completion output TASK_COMPLETE: <result summary>"
                    else:
                        current_task = (
                            f"Task: {task}\n"
                            f"Completed so far: {last_result_text}\n"
                            f"Please continue. After completion output TASK_COMPLETE: <result summary>"
                        )

                    agent_kwargs = {
                        "task": current_task,
                        "llm": llm,
                        "browser_session": browser_session,
                        "max_actions_per_step": 5,
                        "use_vision": False,
                    }
                    if controller:
                        agent_kwargs["controller"] = controller

                    agent = Agent(**agent_kwargs)

                    try:
                        result = await agent.run(max_steps=max_steps)
                        total_steps += max_steps
                    except Exception as e:
                        logger.error(f"Agent chunk {chunk_num} failed: {e}")
                        return {"status": "failed", "error": str(e), "steps": total_steps}

                    result_text = str(result) if result else ""
                    all_results.append(result_text)

                    if "TASK_COMPLETE" in result_text:
                        final = result_text.split("TASK_COMPLETE:")[-1].strip()
                        return {"status": "completed", "result": final, "steps": total_steps, "chunks": chunk_num}

                    if not result_text or result_text == last_result_text:
                        stuck_count += 1
                    else:
                        stuck_count = 0

                    if stuck_count >= 2:
                        return {
                            "status": "stuck",
                            "result": result_text or last_result_text,
                            "steps": total_steps,
                            "chunks": chunk_num,
                        }

                    last_result_text = result_text

                return {
                    "status": "completed" if all_results else "failed",
                    "result": last_result_text,
                    "steps": total_steps,
                    "chunks": MAX_CHUNKS,
                }

            # Timeout control
            if total_timeout > 0:
                try:
                    return await asyncio.wait_for(_run_chunks(), timeout=total_timeout)
                except TimeoutError:
                    return {
                        "status": "timeout",
                        "error": f"Task exceeded {total_timeout}s limit",
                        "steps": total_steps,
                    }
            else:
                return await _run_chunks()
        finally:
            with contextlib.suppress(Exception):
                await browser_session.close()

    # ── New Actions (browser-use coverage) ──────────────────────

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

        Returns matches with context, element path, and character position.
        """
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
        page = session.page_handle.raw_page

        js_body = self._build_search_js(pattern, case_sensitive, is_regex, max_results, context_chars, css_scope)
        return await page.evaluate(js_body)

    @staticmethod
    def _build_search_js(pattern, case_sensitive, is_regex, max_results, context_chars, css_scope):
        """Build JS for page text search."""
        import json

        safe_pattern = json.dumps(pattern)
        scope_selector = json.dumps(css_scope or "")
        flags = "g" if case_sensitive else "gi"
        regex_flag = "true" if is_regex else "false"
        return f"""(() => {{
            const CSS_SCOPE = {scope_selector};
            const PATTERN = {safe_pattern};
            const CASE_SENSITIVE = {'true' if case_sensitive else 'false'};
            const IS_REGEX = {regex_flag};
            const MAX_RESULTS = {max_results};
            const CONTEXT_CHARS = {context_chars};
            const FLAGS = {json.dumps(flags)};
            try {{
                var scope = CSS_SCOPE ? document.querySelector(CSS_SCOPE) : document.body;
                if (!scope) return {{error: 'CSS scope not found: ' + CSS_SCOPE, matches: [], total: 0}};
                var walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT);
                var fullText = '';
                var nodeOffsets = [];
                while (walker.nextNode()) {{
                    var node = walker.currentNode;
                    if (node.textContent && node.textContent.trim()) {{
                        nodeOffsets.push({{offset: fullText.length, length: node.textContent.length, node: node}});
                        fullText += node.textContent;
                    }}
                }}
                var re;
                try {{ re = new RegExp(PATTERN, FLAGS); }} catch(e) {{ return {{error: 'Invalid regex', matches: [], total: 0}}; }}
                var matches = [], totalFound = 0;
                var match;
                while ((match = re.exec(fullText)) !== null) {{
                    totalFound++;
                    if (matches.length < MAX_RESULTS) {{
                        var start = Math.max(0, match.index - CONTEXT_CHARS);
                        var end = Math.min(fullText.length, match.index + match[0].length + CONTEXT_CHARS);
                        var context = fullText.slice(start, end);
                        var elPath = '';
                        for (var i = 0; i < nodeOffsets.length; i++) {{
                            if (nodeOffsets[i].offset <= match.index && nodeOffsets[i].offset + nodeOffsets[i].length > match.index) {{
                                var el = nodeOffsets[i].node.parentElement;
                                var parts = [];
                                while (el && el !== document && el !== document.body) {{
                                    var tag = el.tagName ? el.tagName.toLowerCase() : '';
                                    if (!tag) break;
                                    if (el.id) tag += '#' + el.id;
                                    else if (el.className && typeof el.className === 'string') tag += '.' + el.className.trim().split(/\\s+/).slice(0,2).join('.');
                                    parts.unshift(tag); el = el.parentElement;
                                }}
                                elPath = parts.join(' > ');
                                break;
                            }}
                        }}
                        matches.push({{match_text: match[0], context: (start > 0 ? '...' : '') + context + (end < fullText.length ? '...' : ''), element_path: elPath, char_position: match.index}});
                    }}
                    if (match[0].length === 0) re.lastIndex++;
                }}
                return {{matches: matches, total: totalFound, has_more: totalFound > MAX_RESULTS}};
            }} catch(e) {{ return {{error: e.message, matches: [], total: 0}}; }}
        }})()"""

    async def find_elements(
        self,
        session_id: str,
        selector: str,
        max_results: int = 50,
        return_attributes: list[str] | None = None,
    ) -> dict:
        """Find elements matching a CSS selector with metadata."""
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
        page = session.page_handle.raw_page

        attrs_json = json.dumps(return_attributes or []) if return_attributes else "[]"
        safe_selector = json.dumps(selector)

        result = await page.evaluate(f"""(() => {{
            try {{
                var elements = document.querySelectorAll({safe_selector});
                var total = elements.length;
                var limit = Math.min(total, {max_results});
                var results = [];
                var attrs = JSON.parse('{attrs_json}');
                for (var i = 0; i < limit; i++) {{
                    var el = elements[i];
                    var info = {{index: i, tag: el.tagName.toLowerCase(), text: el.textContent?.trim()?.substring(0, 200) || ''}};
                    if (el.id) info.id = el.id;
                    if (el.className && typeof el.className === 'string') info.class_name = el.className.trim().split(/\\s+/)[0];
                    var rect = el.getBoundingClientRect();
                    info.bounding_box = {{x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height)}};
                    info.visible = rect.width > 0 && rect.height > 0;
                    for (var a of attrs) {{ if (el.getAttribute(a) !== null) info[a] = el.getAttribute(a); }}
                    results.push(info);
                }}
                return {{elements: results, total: total, has_more: total > {max_results}}};
            }} catch(e) {{ return {{error: e.message, elements: [], total: 0}}; }}
        }})()""")
        return result

    async def get_dropdown_options(self, session_id: str, ref: str) -> list[dict]:
        """Get options from a <select> element by ref."""
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
        page = session.page_handle.raw_page
        safe_ref = json.dumps(ref)

        options = await page.evaluate(f"""(() => {{
            const el = document.querySelector('[data-ab-ref="' + {safe_ref} + '"]');
            if (!el || el.tagName !== 'SELECT') return {{error: 'Element not found or not a <select>'}};
            return Array.from(el.options).map((opt, i) => ({{
                index: i, value: opt.value, text: opt.text.trim(), selected: opt.selected, disabled: opt.disabled
            }}));
        }})()""")
        return options

    async def select_dropdown_option(self, session_id: str, ref: str, option_text: str) -> None:
        """Select a dropdown option by visible text."""
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
        page = session.page_handle.raw_page
        safe_ref = json.dumps(ref)
        safe_text = json.dumps(option_text)

        await page.evaluate(f"""(() => {{
            const el = document.querySelector('[data-ab-ref="' + {safe_ref} + '"]');
            if (!el || el.tagName !== 'SELECT') throw new Error('Not a select element');
            const opts = Array.from(el.options);
            const target = opts.find(o => o.text.trim() === {safe_text});
            if (!target) throw new Error('Option not found: ' + {safe_text});
            el.value = target.value;
            el.dispatchEvent(new Event('change', {{bubbles: true}}));
            el.dispatchEvent(new Event('input', {{bubbles: true}}));
        }})()""")

    async def upload_file(self, session_id: str, ref: str, file_paths: list[str]) -> None:
        """Upload files to an <input type=file> element."""
        import json

        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
        page = session.page_handle.raw_page
        safe_ref = json.dumps(ref)

        # Find the input element via its data-ab-ref
        input_element = await page.evaluate(f"""(() => {{
            const el = document.querySelector('[data-ab-ref="' + {safe_ref} + '"]');
            if (!el) return null;
            return el.tagName === 'INPUT' && el.type === 'file' ? true : false;
        }})()""")
        if not input_element:
            raise ValueError(f"Element {ref} is not a file input")

        # Use Playwright's set_input_files with the file chooser approach
        file_input = await page.query_selector(f'[data-ab-ref="{ref}"]')
        if file_input:
            await file_input.set_input_files(file_paths)
            logger.info(f"Uploaded {len(file_paths)} files to {ref}")

    async def screenshot(
        self,
        session_id: str,
        ref: str | None = None,
        full_page: bool = True,
        format: str = "png",
        quality: int | None = None,
    ) -> bytes:
        """Take a screenshot. Returns image bytes."""
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
        page = session.page_handle.raw_page

        kwargs: dict[str, Any] = {"full_page": full_page, "type": format}
        if quality and format.lower() == "jpeg":
            kwargs["quality"] = quality

        if ref:
            # Element-specific screenshot
            safe_ref = json.dumps(ref)
            element = await page.query_selector(f'[data-ab-ref="{ref}"]')
            if element:
                return await element.screenshot(**kwargs)
            raise ValueError(f"Element {ref} not found for screenshot")

        return await page.screenshot(**kwargs)

    async def save_as_pdf(
        self,
        session_id: str,
        output_path: str | None = None,
        landscape: bool = False,
        format: str = "A4",
        print_background: bool = True,
        margin_top: str = "1cm",
        margin_bottom: str = "1cm",
        margin_left: str = "1cm",
        margin_right: str = "1cm",
    ) -> str:
        """Save current page as PDF. Returns file path."""
        import tempfile

        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
        page = session.page_handle.raw_page

        out_path = output_path or str(tempfile.mktemp(suffix=".pdf", prefix="ab-pdf-"))
        pdf_kwargs = {
            "path": out_path,
            "landscape": landscape,
            "format": format,
            "print_background": print_background,
            "margin": {
                "top": margin_top,
                "bottom": margin_bottom,
                "left": margin_left,
                "right": margin_right,
            },
        }
        await page.pdf(**pdf_kwargs)
        logger.info(f"PDF saved to {out_path}")
        return out_path

    async def send_keys(self, session_id: str, keys: str) -> None:
        """Send a complex key sequence (e.g., 'Meta+a', 'Shift+Home')."""
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
        page = session.page_handle.raw_page
        await page.keyboard.press(keys)

    async def scroll_to_text(self, session_id: str, text: str, max_scrolls: int = 10, scroll_amount: int = 500) -> bool:
        """Scroll until text becomes visible. Returns True if found."""
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
        page = session.page_handle.raw_page
        safe_text = json.dumps(text)

        found = await page.evaluate(f"""(() => {{
            const TARGET_TEXT = {safe_text};
            const MAX_SCROLLS = {max_scrolls};
            const SCROLL_AMOUNT = {scroll_amount};
            function isVisible(el) {{
                const r = el.getBoundingClientRect();
                return r.top >= 0 && r.bottom <= window.innerHeight && r.width > 0;
            }}
            // Check if already visible
            var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
            while (walker.nextNode()) {{
                if (walker.currentNode.textContent.includes(TARGET_TEXT)) {{
                    var parent = walker.currentNode.parentElement;
                    if (parent && isVisible(parent)) return true;
                }}
            }}
            // Scroll and check
            for (var i = 0; i < MAX_SCROLLS; i++) {{
                window.scrollBy(0, SCROLL_AMOUNT);
                var w2 = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                while (w2.nextNode()) {{
                    if (w2.currentNode.textContent.includes(TARGET_TEXT)) {{
                        var p = w2.currentNode.parentElement;
                        if (p && isVisible(p)) return true;
                    }}
                }}
            }}
            return false;
        }})()""")
        return bool(found)

    async def switch_tab(self, session_id: str, index: int) -> None:
        """Switch to tab by index."""
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
        context = session.browser_context
        pages = context.pages
        if index < 0 or index >= len(pages):
            raise IndexError(f"Tab index {index} out of range (0-{len(pages)-1})")
        await pages[index].bring_to_front()

    async def open_tab(self, session_id: str, url: str | None = None) -> int:
        """Open new tab. Returns new tab index."""
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
        context = session.browser_context
        new_page = await context.new_page()
        if url:
            await new_page.goto(url, wait_until="domcontentloaded")
        # Return index of new page
        pages = context.pages
        return pages.index(new_page)

    async def close_tab(self, session_id: str, index: int | None = None) -> None:
        """Close tab by index (or current tab if None)."""
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
        context = session.browser_context
        pages = context.pages
        if len(pages) <= 1:
            raise ValueError("Cannot close last remaining tab")
        if index is None:
            index = len(pages) - 1
        if index < 0 or index >= len(pages):
            raise IndexError(f"Tab index {index} out of range (0-{len(pages)-1})")
        await pages[index].close()

    async def extract_content(
        self,
        session_id: str,
        selector: str | None = None,
        extract_type: str = "text",
        max_length: int | None = None,
    ) -> str:
        """Extract content from page or element."""
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
        page = session.page_handle.raw_page

        if extract_type == "text":
            base = f"(document.querySelector({json.dumps(selector)}) || document.body)" if selector else "document.body"
            js = f"{base}.textContent?.trim()?.substring(0, {max_length or 100000}) || ''"
            return await page.evaluate(js)
        elif extract_type == "html":
            base = f"document.querySelector({json.dumps(selector)})" if selector else "document.documentElement"
            js = f"{base}?.outerHTML?.substring(0, {max_length or 500000}) || ''"
            return await page.evaluate(js)
        elif extract_type == "links":
            links = await page.evaluate("""() => {
                return Array.from(document.querySelectorAll('a[href]')).map(a => ({
                    text: a.textContent?.trim()?.substring(0, 200) || '',
                    href: a.href,
                    title: a.title || ''
                })).filter(l => l.href);
            }""")
            return json.dumps(links[:100] if max_length else links)
        elif extract_type == "images":
            images = await page.evaluate("""() => {
                return Array.from(document.querySelectorAll('img[src]')).map(img => ({
                    src: img.src, alt: img.alt || '', width: img.naturalWidth, height: img.naturalHeight
                }));
            }""")
            return json.dumps(images[:100] if max_length else images)
        else:
            # Default: text extraction
            return await page.evaluate("(document.body?.textContent || '').trim()")

    async def get_tabs_info(self, session_id: str) -> list[dict]:
        """Get info about all open tabs."""
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
        context = session.browser_context
        tabs = []
        for i, p in enumerate(context.pages):
            tabs.append({
                "index": i,
                "url": p.url,
                "title": await p.title(),
            })
        return tabs

    def _create_llm(self, llm_config: dict | None = None):
        """Create a browser-use compatible LLM instance."""
        import os

        if not llm_config:
            provider = os.getenv("STEALTH_BROWSER_LLM_PROVIDER", "openai")
            llm_config = {"provider": provider}

        provider = llm_config.get("provider", "openai")
        model_name = llm_config.get("model", "gpt-4o" if provider == "openai" else "claude-3-5-sonnet-20241022")
        api_key = llm_config.get("api_key")
        base_url = llm_config.get("base_url")
        temperature = llm_config.get("temperature", 0.1)
        max_tokens = llm_config.get("max_tokens", 4096)

        if provider == "anthropic":
            from browser_use.llm.anthropic.chat import ChatAnthropic

            return ChatAnthropic(
                model=model_name,
                api_key=api_key,
                base_url=base_url,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        from browser_use.llm.openai.chat import ChatOpenAI

        return ChatOpenAI(
            model=model_name,
            api_key=api_key,
            base_url=base_url,
            temperature=temperature,
            max_completion_tokens=max_tokens,
        )
