"""
Session Pool Manager

Multi-user isolation core:
- Each user creates an independent Session
- Session isolation: independent profile, cookies, fingerprint
- Resource limits: max concurrency, timeout reclamation
- Load balancing: distribute across browser instances
- Atomic operations: navigate, snapshot, click, fill, evaluate JS, etc.
"""

import asyncio
import contextlib
import logging
import os
import time
from typing import Literal
from uuid import uuid4

from browser_use import Agent, BrowserProfile, BrowserSession
from playwright.async_api import Page, async_playwright

from agent_browser.browser.instance_pool import BrowserInstancePool
from agent_browser.models import (
    ClickRequest,
    DockerBrowserInstance,
    ElementInfo,
    EvaluateRequest,
    FillRequest,
    NavigateRequest,
    ResourceExhaustedError,
    ScrollRequest,
    SessionNotFoundError,
    SnapshotResponse,
    UserSession,
    WaitRequest,
)
from agent_browser.stealth.enhancer import StealthEnhancer

logger = logging.getLogger(__name__)


class SessionPoolManager:
    """Session pool manager — multi-user isolation core."""

    def __init__(
        self,
        max_concurrent: int = 10,
        idle_timeout: int = 1800,
        browser_mode: Literal["local", "docker", "k8s"] = "local",
    ):
        self.sessions: dict[str, UserSession] = {}
        self.max_concurrent = max_concurrent
        self.idle_timeout = idle_timeout

        # In docker mode, detect if local CDP is already running → auto-downgrade to local mode
        # k8s mode is never downgraded (browser pods are always remote)
        effective_mode = browser_mode
        if browser_mode == "docker":
            try:
                import socket

                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                result = sock.connect_ex(("127.0.0.1", 19222))
                sock.close()
                if result == 0:
                    effective_mode = "local"
                    logger.info("Local CDP detected on :19222, overriding browser_mode docker -> local")
            except Exception:
                pass

        self.browser_pool = BrowserInstancePool(mode=effective_mode)
        self._stealth = StealthEnhancer()

        self._monitor_task = None
        self._health_check_task = None
        self._create_lock = asyncio.Lock()
        # Docker mode CDP connection cache: session_id -> (playwright, browser)
        self._docker_connections: dict[str, tuple] = {}

        logger.info(
            f"SessionPoolManager initialized: "
            f"max_concurrent={max_concurrent}, "
            f"idle_timeout={idle_timeout}s, "
            f"browser_mode={browser_mode}"
        )

    def start(self):
        """Start background tasks (must be called within event loop)."""
        self._monitor_task = asyncio.create_task(self._idle_monitor())
        self._health_check_task = asyncio.create_task(self._health_check_loop())
        if self.browser_pool.mode == "k8s" and self.browser_pool._k8s_manager:
            self.browser_pool._k8s_manager.start()

    async def create_session(
        self,
        user_id: str,
        profile_config: dict | None = None,
        browser_type: str = "chromium",
        owner_key: str = "",
    ) -> str:
        """Create a new session."""
        # Check quota and reserve session_id under lock to prevent concurrent over-allocation
        async with self._create_lock:
            if len(self.sessions) >= self.max_concurrent:
                raise ResourceExhaustedError(f"Max concurrent sessions reached ({self.max_concurrent})")
            session_id = f"{user_id}_{uuid4().hex[:8]}"
            # Reserve slot upfront to prevent concurrent requests from bypassing quota check
            self.sessions[session_id] = None  # type: ignore[assignment]

        # Create independent Profile directory
        profile_base = os.getenv("PROFILE_STORAGE", "/data/profiles")
        profile_dir = os.path.join(profile_base, session_id)
        os.makedirs(profile_dir, mode=0o700, exist_ok=True)

        logger.info(f"Creating session {session_id} for user {user_id} (browser={browser_type})")

        # Allocate browser instance (auto-rollback on failure)
        try:
            browser_instance = await self.browser_pool.allocate(
                session_id=session_id,
                profile_dir=profile_dir,
                browser_type=browser_type,
            )
        except Exception:
            logger.error(f"Failed to allocate browser for session {session_id}, cleaning up")
            self.sessions.pop(session_id, None)
            await self.browser_pool.release(session_id)
            raise

        # VNC token: pure random 32-char hex — routing uses session→pod_name memory lookup
        vnc_token = uuid4().hex
        user_session = UserSession(
            session_id=session_id,
            user_id=user_id,
            browser_instance=browser_instance,
            profile_dir=profile_dir,
            created_at=time.time(),
            last_activity=time.time(),
            vnc_token=vnc_token,
            owner_key=owner_key,
        )

        self.sessions[session_id] = user_session
        logger.info(f"Session created: {session_id}, vnc_token: {user_session.vnc_token}")
        return session_id, self._build_browser_node_info(browser_instance)

    def _build_browser_node_info(self, instance) -> dict | None:
        """Build browser node public access info (DockerBrowserInstance returns VNC info)."""
        if not isinstance(instance, DockerBrowserInstance):
            return None
        # Return VNC info if novnc_url is available (always generated when BROWSER_PUBLIC_HOST is set)
        info = {
            "instance_id": instance.instance_id,
        }
        if instance.public_host:
            info["public_host"] = instance.public_host
        if instance.public_cdp_port:
            info["public_cdp_port"] = instance.public_cdp_port
        if instance.public_novnc_port:
            info["public_novnc_port"] = instance.public_novnc_port
        if instance.novnc_url:
            info["novnc_url"] = instance.novnc_url
        return info

    async def submit_task(
        self,
        session_id: str,
        task: str,
        llm_config: dict,
        max_steps: int = 50,
    ) -> str:
        """Submit a task to the specified session."""
        session = self.sessions.get(session_id)
        if not session:
            raise SessionNotFoundError(f"Session not found: {session_id}")

        session.mark_activity()

        # Create LLM
        llm = self._create_llm(llm_config)

        # Rebuild BrowserSession per task (avoid state corruption after previous task cleanup)
        browser_session = BrowserSession(
            browser_profile=BrowserProfile(
                cdp_url=session.browser_instance.cdp_url,
                is_local=True,
                headless=False,
                highlight_elements=True,
            ),
        )

        # Use browser-use Agent (CDP protocol)
        agent = Agent(
            task=task,
            llm=llm,
            browser_session=browser_session,
            max_actions_per_step=5,
            use_vision=False,
        )

        task_id = f"task_{uuid4().hex[:8]}"

        # Record task
        session.tasks[task_id] = {
            "status": "running",
            "task": task,
            "llm_config": llm_config,
            "result": None,
            "error": None,
            "created_at": time.time(),
            "current_step": 0,
            "last_step_at": None,
        }

        # Execute task asynchronously (pass browser_session for cleanup in finally)
        asyncio.create_task(self._run_agent(session_id, task_id, agent, browser_session, max_steps))

        logger.info(f"Task {task_id} submitted to session {session_id}")
        return task_id

    async def _run_agent(
        self,
        session_id: str,
        task_id: str,
        agent: Agent,
        browser_session: BrowserSession,
        max_steps: int,
    ):
        """Run an Agent task (serial lock ensures same session doesn't run concurrently, CDP failures auto-retry)."""
        session = self.sessions.get(session_id)
        if not session:
            logger.error(f"Session {session_id} not found when running task {task_id}")
            return

        # Get original task description and LLM config from task record
        task_info = session.tasks.get(task_id, {})
        task_description = task_info.get("task", "")
        llm_config = task_info.get("llm_config", {})
        cdp_url = session.browser_instance.cdp_url

        async with session.task_lock:
            MAX_CDP_RETRIES = 3
            current_agent = agent
            current_bs = browser_session

            try:
                for attempt in range(MAX_CDP_RETRIES):
                    try:
                        # Docker containers may have unstable CDP endpoints shortly after startup
                        if attempt == 0 and isinstance(session.browser_instance, DockerBrowserInstance):
                            await asyncio.sleep(2)

                        logger.info(f"Running agent for task {task_id} (max_steps={max_steps}, attempt={attempt + 1})")

                        result = await current_agent.run(max_steps=max_steps)

                        # Extract final result text
                        final_text = str(result)
                        if hasattr(result, "all_results"):
                            for r in reversed(result.all_results):
                                if r.extracted_content and r.is_done:
                                    final_text = r.extracted_content
                                    break

                        session.tasks[task_id]["status"] = "completed"
                        session.tasks[task_id]["result"] = final_text
                        session.mark_activity()

                        logger.info(f"Task {task_id} completed")
                        return  # Success

                    except Exception as e:
                        error_str = str(e).lower()
                        error_type = type(e).__name__.lower()

                        # Check if it's a CDP connection error (retryable)
                        # Also check error message and exception name (httpx.ReadError str(e) may be empty)
                        cdp_keywords = [
                            "read error",
                            "econnreset",
                            "cdp",
                            "websocket",
                            "connect_over_cdp",
                            "readerror",
                            "connection",
                            "browserstartevent",
                            "timed out",
                            "timeout",
                        ]
                        is_cdp_error = any(kw in error_str for kw in cdp_keywords) or any(
                            kw in error_type for kw in ["readerror", "timeout", "connection"]
                        )

                        # Close failed browser session
                        with contextlib.suppress(Exception):
                            await current_bs.close()

                        if not is_cdp_error or attempt >= MAX_CDP_RETRIES - 1:
                            # Non-CDP error or retries exhausted
                            logger.error(f"Task {task_id} failed: {e}")
                            session.tasks[task_id]["status"] = "failed"
                            session.tasks[task_id]["error"] = str(e)
                            return

                        # CDP connection error, wait then retry
                        wait_time = 5 * (attempt + 1)
                        logger.warning(
                            f"[{task_id}] CDP connection error (attempt {attempt + 1}/{MAX_CDP_RETRIES}): {e}. "
                            f"Retrying in {wait_time}s..."
                        )
                        await asyncio.sleep(wait_time)

                        # Recreate BrowserSession and Agent
                        new_bs = BrowserSession(
                            browser_profile=BrowserProfile(
                                cdp_url=cdp_url,
                                is_local=True,
                                headless=False,
                                highlight_elements=True,
                            ),
                        )
                        new_agent = Agent(
                            task=task_description,
                            llm=self._create_llm(llm_config),
                            browser_session=new_bs,
                            max_actions_per_step=5,
                            use_vision=False,
                        )
                        current_agent = new_agent
                        current_bs = new_bs

            finally:
                # Close the last BrowserSession
                with contextlib.suppress(Exception):
                    await current_bs.close()

    def _create_llm(self, llm_config: dict):
        """Create LLM instance (using browser-use's ChatOpenAI wrapper)."""
        from browser_use.llm import ChatOpenAI

        return ChatOpenAI(
            model=llm_config.get("model", "glm-5-turbo"),
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL"),
            temperature=0.1,
            add_schema_to_system_prompt=True,
            dont_force_structured_output=True,
        )

    async def get_task_status(self, session_id: str, task_id: str) -> dict:
        """Get task status."""
        session = self.sessions.get(session_id)
        if not session:
            raise SessionNotFoundError(f"Session not found: {session_id}")

        task_info = session.tasks.get(task_id)
        if not task_info:
            return {"status": "not_found"}

        result = dict(task_info)
        result["browser_node"] = self._build_browser_node_info(session.browser_instance)
        return result

    async def get_session_status(self, session_id: str) -> dict:
        """Get session status."""
        session = self.sessions.get(session_id)
        if not session:
            raise SessionNotFoundError(f"Session not found: {session_id}")

        return {
            "session_id": session.session_id,
            "user_id": session.user_id,
            "created_at": session.created_at,
            "last_activity": session.last_activity,
            "idle_time": time.time() - session.last_activity,
            "tasks": {
                task_id: {
                    "status": task_info["status"],
                    "task": task_info["task"],
                    "created_at": task_info["created_at"],
                }
                for task_id, task_info in session.tasks.items()
            },
            "browser_node": self._build_browser_node_info(session.browser_instance),
        }

    async def close_session(self, session_id: str):
        """Close a session."""
        session = self.sessions.pop(session_id, None)
        if not session:
            logger.warning(f"Session not found: {session_id}")
            return

        logger.info(f"Closing session {session_id}")

        # Close Docker CDP connection
        conn = self._docker_connections.pop(session_id, None)
        if conn:
            pw, browser = conn
            with contextlib.suppress(Exception):
                await browser.close()
            with contextlib.suppress(Exception):
                await pw.stop()

        # Release browser instance
        await self.browser_pool.release(session_id)

        logger.info(f"Session closed: {session_id}")

    async def _idle_monitor(self):
        """Idle monitor: auto-close sessions that exceed idle timeout (skip sessions with active tasks)."""
        while True:
            await asyncio.sleep(60)  # Check every minute

            idle_sessions = []
            for session_id, session in list(self.sessions.items()):
                if session.is_idle(self.idle_timeout):
                    # Check if there's a running task (task_lock held)
                    if session.task_lock.locked():
                        logger.debug(
                            f"Session {session_id} idle for {self.idle_timeout}s, "
                            f"but has active task running, skipping..."
                        )
                        continue
                    idle_sessions.append(session_id)

            for session_id in idle_sessions:
                logger.info(f"Session {session_id} idle for {self.idle_timeout}s, closing...")
                await self.close_session(session_id)

    async def _health_check_loop(self):
        """Runtime health check: detect crashed Docker containers and auto-recover."""
        from agent_browser.models import DockerBrowserInstance

        while True:
            await asyncio.sleep(30)  # Check every 30 seconds

            for session_id, session in list(self.sessions.items()):
                instance = session.browser_instance

                if not isinstance(instance, DockerBrowserInstance):
                    continue

                try:
                    instance.container.reload()
                    status = instance.container.status
                except Exception as e:
                    logger.warning(f"Cannot inspect container for {session_id}: {e}")
                    status = "unknown"

                if status not in ("running",):
                    logger.error(f"Container for session {session_id} is {status}, recovering...")
                    # Clean up dead session, release resources
                    try:
                        await self.close_session(session_id)
                    except Exception as e:
                        logger.warning(f"Failed to close dead session {session_id}: {e}")

                    # TODO Phase 2: Auto-rebuild session (need to remember original user_id and profile_config)

    async def shutdown(self):
        """Shutdown all sessions."""
        logger.info("Shutting down SessionPoolManager...")

        # Cancel background tasks
        for task in (self._monitor_task, self._health_check_task):
            if task:
                task.cancel()

        # Shutdown k8s manager
        if self.browser_pool.mode == "k8s" and self.browser_pool._k8s_manager:
            await self.browser_pool._k8s_manager.shutdown()

        # Close all sessions
        session_ids = list(self.sessions.keys())
        for session_id in session_ids:
            await self.close_session(session_id)

        logger.info("SessionPoolManager shutdown complete")

    # ============ Atomic operation methods ============

    async def _get_page(self, session_id: str) -> Page:
        """Get the Playwright Page object for a session (supports Local, Docker, and K8s instances)."""
        session = self.sessions.get(session_id)
        if not session:
            raise SessionNotFoundError(f"Session not found: {session_id}")

        instance = session.browser_instance

        from agent_browser.models import K8sBrowserInstance
        if isinstance(instance, (DockerBrowserInstance, K8sBrowserInstance)):
            return await self._get_docker_page(session_id, instance)

        # LocalBrowserInstance: use existing Playwright objects directly
        browser = instance.browser
        if not browser:
            raise SessionNotFoundError(f"Browser not connected for session {session_id}")

        # Compatible with Browser and BrowserContext (persistent context returns BrowserContext)
        # Note: patchright and playwright have different types, can't cross isinstance check
        if hasattr(browser, "pages") and not hasattr(browser, "contexts"):
            # persistent context / BrowserContext: use pages directly
            pages = browser.pages
            if pages:
                return pages[0]
            return await browser.new_page()
        # Normal Browser: get via contexts
        contexts = browser.contexts
        if contexts:
            context = contexts[0]
        else:
            context = await browser.new_context()
        pages = context.pages
        if pages:
            return pages[0]
        return await context.new_page()

    async def _get_docker_page(self, session_id: str, instance: DockerBrowserInstance) -> Page:
        """Get Page from Docker container via CDP (with retry)."""
        # Reuse existing CDP connection
        if session_id in self._docker_connections:
            pw, browser = self._docker_connections[session_id]
            try:
                contexts = browser.contexts
                if contexts and contexts[0].pages:
                    return contexts[0].pages[0]
            except Exception:
                # Connection broken, clean up and reconnect
                old_pw, old_browser = self._docker_connections.pop(session_id, (None, None))
                if old_browser:
                    with contextlib.suppress(Exception):
                        await old_browser.close()
                if old_pw:
                    with contextlib.suppress(Exception):
                        await old_pw.stop()

        # Establish new CDP connection (with retry, Docker containers may need extra time)
        last_error = None
        for attempt in range(3):
            try:
                pw = await async_playwright().start()
                browser = await pw.chromium.connect_over_cdp(instance.cdp_url)
                self._docker_connections[session_id] = (pw, browser)

                contexts = browser.contexts
                if contexts and contexts[0].pages:
                    return contexts[0].pages[0]
                context = contexts[0] if contexts else await browser.new_context()
                return await context.new_page()
            except Exception as e:
                last_error = e
                logger.warning(f"CDP connect attempt {attempt + 1}/3 failed: {e}")
                # Clean up failed connection
                if session_id in self._docker_connections:
                    _, failed_browser = self._docker_connections.pop(session_id, (None, None))
                    try:
                        if failed_browser:
                            await failed_browser.close()
                    except Exception:
                        pass
                    with contextlib.suppress(Exception):
                        await pw.stop()
                if attempt < 2:
                    await asyncio.sleep(3 * (attempt + 1))  # 3s, 6s backoff

        raise ConnectionError(f"Failed to connect to Docker CDP at {instance.cdp_url} after 3 attempts: {last_error}")

    async def navigate(self, session_id: str, request: NavigateRequest) -> dict:
        """Page navigation."""
        page = await self._get_page(session_id)

        await self._stealth.pre_action("navigate")

        try:
            await page.goto(request.url, wait_until=request.wait_until, timeout=request.timeout)
        except Exception as e:
            error_str = str(e).lower()
            # Mark session as abnormal on CDP disconnection so health_check can clean up
            if any(kw in error_str for kw in ["disconnected", "connection", "read error", "econnreset"]):
                logger.error(f"CDP connection lost during navigate for session {session_id}: {e}")
                # For Docker instances: proactively clean dead sessions
                session = self.sessions.get(session_id)
                if session and isinstance(session.browser_instance, DockerBrowserInstance):
                    logger.warning(f"Auto-cleaning dead Docker session {session_id}")
                    asyncio.create_task(self.close_session(session_id))
            raise

        session = self.sessions.get(session_id)
        if session:
            session.mark_activity()

        return {"status": "ok", "url": page.url, "title": await page.title()}

    async def snapshot(self, session_id: str, interactive_only: bool = True) -> SnapshotResponse:
        """Get DOM snapshot."""
        page = await self._get_page(session_id)

        # Inject data-ab-ref attribute and return element list, ensure ref is bound to DOM (prevent position drift issues)
        elements_script = """
        () => {
            const selectors = 'button, a, input, textarea, select, [role="button"], [onclick]';
            const allElements = [];
            let refIndex = 0;

            document.querySelectorAll(selectors).forEach(el => {
                if (el.offsetParent === null && el.getClientRects().length === 0) return;

                const ref = '@e' + refIndex;
                el.setAttribute('data-ab-ref', ref);
                refIndex++;

                const rect = el.getBoundingClientRect();
                allElements.push({
                    ref: ref,
                    tag: el.tagName.toLowerCase(),
                    text: (el.textContent || el.value || el.placeholder || '').substring(0, 100).trim(),
                    role: el.getAttribute('role') || el.tagName.toLowerCase(),
                    type: el.type || null,
                    placeholder: el.placeholder || null,
                    href: el.href || null,
                    is_visible: rect.width > 0 && rect.height > 0,
                    is_enabled: !el.disabled,
                    bounding_box: {x: rect.x, y: rect.y, width: rect.width, height: rect.height}
                });
            });

            return {
                url: window.location.href,
                title: document.title,
                elements: allElements
            };
        }
        """

        result = await page.evaluate(elements_script)

        session = self.sessions.get(session_id)
        if session:
            session.mark_activity()

        return SnapshotResponse(
            url=result["url"], title=result["title"], elements=[ElementInfo(**el) for el in result["elements"]]
        )

    async def click(self, session_id: str, request: ClickRequest) -> dict:
        """Click element."""
        page = await self._get_page(session_id)

        await self._stealth.pre_action("click")
        await self._stealth.random_mouse_move(page)

        # Validate ref format
        if not request.ref.startswith("@e"):
            raise ValueError(f"Invalid ref format: {request.ref}")

        # Find element via data-ab-ref attribute (stable, immune to DOM position changes)
        element = await page.query_selector(f'[data-ab-ref="{request.ref}"]')
        if not element:
            raise ValueError(f"Element {request.ref} not found. DOM may have changed since snapshot.")

        # Execute click
        await element.click(button=request.button, click_count=request.click_count, delay=request.delay)

        session = self.sessions.get(session_id)
        if session:
            session.mark_activity()

        return {"status": "ok", "ref": request.ref}

    async def fill(self, session_id: str, request: FillRequest) -> dict:
        """Fill input field."""
        page = await self._get_page(session_id)

        await self._stealth.pre_action("input")

        # Validate ref format
        if not request.ref.startswith("@e"):
            raise ValueError(f"Invalid ref format: {request.ref}")

        # Find element via data-ab-ref attribute
        element = await page.query_selector(f'[data-ab-ref="{request.ref}"]')
        if not element:
            raise ValueError(f"Element {request.ref} not found. DOM may have changed since snapshot.")

        # Clear and fill
        if request.clear_first:
            await element.fill("")
        await element.fill(request.text)

        session = self.sessions.get(session_id)
        if session:
            session.mark_activity()

        return {"status": "ok", "ref": request.ref, "text": request.text}

    async def evaluate(self, session_id: str, request: EvaluateRequest) -> dict:
        """Execute JavaScript."""
        page = await self._get_page(session_id)

        result = await page.evaluate(request.expression)

        session = self.sessions.get(session_id)
        if session:
            session.mark_activity()

        return {"status": "ok", "result": result}

    async def scroll(self, session_id: str, request: ScrollRequest) -> dict:
        """Scroll page."""
        page = await self._get_page(session_id)

        await self._stealth.pre_action("scroll")

        delta_y = request.amount if request.direction == "down" else -request.amount

        await page.mouse.wheel(0, delta_y)

        session = self.sessions.get(session_id)
        if session:
            session.mark_activity()

        return {"status": "ok", "direction": request.direction, "amount": request.amount}

    async def wait_for_selector(self, session_id: str, request: WaitRequest) -> dict:
        """Wait for selector."""
        page = await self._get_page(session_id)

        await page.wait_for_selector(request.selector, timeout=request.timeout, state=request.state)

        session = self.sessions.get(session_id)
        if session:
            session.mark_activity()

        return {"status": "ok", "selector": request.selector}

    async def get_title(self, session_id: str) -> str:
        """Get page title."""
        page = await self._get_page(session_id)
        return await page.title()

    async def get_url(self, session_id: str) -> str:
        """Get page URL."""
        page = await self._get_page(session_id)
        return page.url

    async def go_back(self, session_id: str, wait_until: str = "domcontentloaded", timeout: int = 10000) -> dict:
        """Go back to previous page."""
        page = await self._get_page(session_id)
        await page.go_back(wait_until=wait_until, timeout=timeout)

        session = self.sessions.get(session_id)
        if session:
            session.mark_activity()

        return {"status": "ok", "url": page.url}

    async def mouse_move(self, session_id: str, x: float, y: float) -> dict:
        """Move mouse."""
        page = await self._get_page(session_id)
        await page.mouse.move(x, y)

        session = self.sessions.get(session_id)
        if session:
            session.mark_activity()

        return {"status": "ok", "x": x, "y": y}

    async def keyboard_press(self, session_id: str, key: str) -> dict:
        """Press key."""
        page = await self._get_page(session_id)
        await page.keyboard.press(key)

        session = self.sessions.get(session_id)
        if session:
            session.mark_activity()

        return {"status": "ok", "key": key}
