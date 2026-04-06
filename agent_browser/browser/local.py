"""Local CDP backend -- wraps BrowserController + BrowserDaemon for direct CDP access."""

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from playwright.async_api import Browser, Page, Playwright, async_playwright

from agent_browser.config import SkillConfig
from agent_browser.utils.refs_generator import generate_refs

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
                from agent_browser.browser.daemon import BrowserDaemon
                self._daemon = BrowserDaemon.get(config)
                logger.info("BrowserDaemon enabled")
            except Exception as e:
                logger.debug(f"BrowserDaemon not available: {e}")

        # Lazy init StealthEnhancer
        if config.stealth_enabled:
            try:
                from agent_browser.stealth.enhancer import StealthEnhancer
                self._stealth = StealthEnhancer()
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
            async with aiohttp.ClientSession() as session:
                async with session.get(health_url, timeout=aiohttp.ClientTimeout(total=2)) as resp:
                    return resp.status == 200
        except Exception:
            return False

    @staticmethod
    async def ensure_cloakbrowser_installed() -> bool:
        """Check if CloakBrowser is installed; auto-download if missing.

        Returns True if already installed or installation succeeded.
        """
        try:
            import cloakbrowser  # noqa: F401
            logger.debug(f"CloakBrowser found: {getattr(cloakbrowser, '__version__', 'unknown')}")
            return True
        except ImportError:
            pass

        logger.info("CloakBrowser not installed, attempting auto-install...")
        import sys

        try:
            result = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "pip", "install",
                "cloakbrowser==0.3.18",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await result.communicate(timeout=120)

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
                sys.executable, "-m", "cloakbrowser.launch",
                "--port", "19222",
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
                    "CloakBrowser not installed and auto-install failed. "
                    "Run: pip install cloakbrowser==0.3.18"
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
                from agent_browser.stealth.enhancer import StealthEnhancer
                from agent_browser.stealth.patches import inject_stealth_patches
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
        context = await self._browser.new_context()
        page = await context.new_page()

        # Inject stealth enhancements
        if self._stealth:
            from agent_browser.stealth.enhancer import StealthEnhancer
            from agent_browser.stealth.patches import inject_stealth_patches
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

                        from agent_browser.stealth.actions import register_stealth_actions

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

                    agent_kwargs = dict(
                        task=current_task,
                        llm=llm,
                        browser_session=browser_session,
                        max_actions_per_step=5,
                        use_vision=False,
                    )
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

    def _create_llm(self, llm_config: dict | None = None):
        """Create a browser-use compatible LLM instance."""
        import os
        if not llm_config:
            provider = os.getenv("AGENT_BROWSER_LLM_PROVIDER", "openai")
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
                model=model_name, api_key=api_key, base_url=base_url,
                temperature=temperature, max_tokens=max_tokens,
            )
        else:
            from browser_use.llm.openai.chat import ChatOpenAI
            return ChatOpenAI(
                model=model_name, api_key=api_key, base_url=base_url,
                temperature=temperature, max_completion_tokens=max_tokens,
            )
