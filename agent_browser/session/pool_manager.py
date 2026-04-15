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
import json
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
    K8sBrowserInstance,
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
        store=None,
    ):
        self.sessions: dict[str, UserSession] = {}
        self.max_concurrent = max_concurrent
        self.idle_timeout = idle_timeout

        # Shared state store (K8s ConfigMap or in-memory)
        if store is not None:
            self.store = store
        else:
            from agent_browser.state.store import create_state_store
            self.store = create_state_store()

        # In docker mode, detect if local CDP is already running → auto-downgrade to local mode
        # Skip auto-downgrade in Kubernetes (KUBERNETES_SERVICE_HOST is auto-injected)
        effective_mode = browser_mode
        if browser_mode == "docker" and not os.getenv("KUBERNETES_SERVICE_HOST"):
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
        from agent_browser.stealth.profiles import profile_from_env
        self._stealth = StealthEnhancer(profile=profile_from_env())
        self._backend = None  # Lazy LocalCDPBackend for operation delegation

        self._monitor_task = None
        self._health_check_task = None
        self._create_lock = asyncio.Lock()
        # CDP connection cache: session_id -> (playwright, browser) — shared by Docker and K8s modes
        self._cdp_connections: dict[str, tuple] = {}
        # Track which sessions have had JS stealth patches injected
        self._stealth_injected: set[str] = set()

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
        # Clean up leaked allocated_pods from ConfigMap (e.g. after crash/restart)
        self._cleanup_task = asyncio.create_task(self._cleanup_leaked_allocations())

    async def create_session(
        self,
        user_id: str,
        profile_config: dict | None = None,
        browser_type: str = "chromium",
        owner_key: str = "",
    ) -> str:
        """Create a new session."""
        # Check global quota via store (atomic across replicas)
        async with self._create_lock:
            acquired = await self.store.try_acquire_session_slot(self.max_concurrent)
            if not acquired:
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
            await self.store.decr_session_count()
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
        # Persist session metadata for cross-replica recovery
        if hasattr(self.store, 'save_session_meta'):
            try:
                await self.store.save_session_meta(
                    session_id, user_id, profile_dir
                )
            except Exception:
                logger.debug("save_session_meta failed (non-critical)")
        logger.info(f"Session created: {session_id}, vnc_token: {user_session.vnc_token}")
        return session_id, self._build_browser_node_info(browser_instance)

    def _build_browser_node_info(self, instance) -> dict | None:
        """Build browser node public access info.

        For K8sBrowserInstance: uses pod DNS + public host from env.
        For DockerBrowserInstance: uses instance attributes.
        For local mode inside Docker (all-in-one): constructs noVNC URL from env vars.
        """
        if isinstance(instance, K8sBrowserInstance):
            public_host = os.getenv("BROWSER_PUBLIC_HOST", "")
            info = {"instance_id": instance.instance_id, "pod_name": instance.pod_name}
            if instance.novnc_url:
                info["novnc_url"] = instance.novnc_url
            if public_host:
                # Build public noVNC URL via gateway domain
                base = public_host
                if ":" not in base:
                    gateway_port = os.getenv("BROWSER_GATEWAY_PORT", "")
                    if gateway_port:
                        base = f"{base}:{gateway_port}"
                path_prefix = os.getenv("BROWSER_NOVNC_PATH_PREFIX", "")
                if path_prefix:
                    path_prefix = path_prefix.replace("{pod_name}", instance.pod_name)
                info["public_host"] = public_host
                info["novnc_url"] = f"http://{base}{path_prefix}/vnc.html"
            return info

        if isinstance(instance, DockerBrowserInstance):
            info = {"instance_id": instance.instance_id}
            if instance.public_host:
                info["public_host"] = instance.public_host
            if instance.public_cdp_port:
                info["public_cdp_port"] = instance.public_cdp_port
            if instance.public_novnc_port:
                info["public_novnc_port"] = instance.public_novnc_port
            if instance.novnc_url:
                info["novnc_url"] = instance.novnc_url
            return info

        # all-in-one Docker: local browser + noVNC via entrypoint
        public_host = os.getenv("BROWSER_PUBLIC_HOST", "")
        novnc_port = os.getenv("NOVNC_PORT", "6080")
        if public_host:
            novnc_url = f"http://{public_host}:{novnc_port}/vnc.html"
            return {
                "instance_id": getattr(instance, "instance_id", None),
                "public_host": public_host,
                "public_novnc_port": int(novnc_port),
                "novnc_url": novnc_url,
            }
        return None

    async def submit_task(
        self,
        session_id: str,
        task: str,
        llm_config: dict,
        max_steps: int = 50,
        agent_config: dict | None = None,
        intelligence: str = "agent",
    ) -> str:
        """Submit a task to the specified session."""
        session = self.sessions.get(session_id)
        if not session:
            session = await self._recover_session(session_id)
        if not session:
            raise SessionNotFoundError(f"Session not found: {session_id}")

        session.mark_activity()

        # Create LLM
        llm = self._create_llm(llm_config)

        # Create fallback LLM if configured
        fallback_llm = None
        if agent_config and agent_config.get("fallback_llm_model"):
            fallback_llm_config = dict(llm_config)
            fallback_llm_config["model"] = agent_config["fallback_llm_model"]
            fallback_llm = self._create_llm(fallback_llm_config)

        # Build Agent kwargs from agent_config
        agent_kwargs = self._build_agent_kwargs(agent_config)

        # LLM mode: return tool list without starting Agent
        if intelligence != "agent":
            task_id = f"task_{uuid4().hex[:8]}"
            session.tasks[task_id] = {
                "status": "ready",
                "task": task,
                "mode": "llm",
                "tools": ["snapshot", "click", "fill", "scroll", "go_back", "hover", "press_key"],
                "created_at": time.time(),
            }
            return task_id

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
            **agent_kwargs,
        )

        # Register stealth actions (human-like delays + Bezier mouse + human typing)
        try:
            from agent_browser.stealth.actions import register_stealth_actions
            register_stealth_actions(agent.controller, self._stealth)
        except Exception as e:
            logger.warning("Failed to register stealth actions for Agent: %s", e)

        task_id = f"task_{uuid4().hex[:8]}"

        # Record task
        session.tasks[task_id] = {
            "status": "running",
            "task": task,
            "llm_config": llm_config,
            "agent_config": agent_config,
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

    @staticmethod
    def _build_agent_kwargs(agent_config: dict | None) -> dict:
        """Convert agent_config dict to Agent() keyword arguments.

        Filters out None values so browser-use defaults apply.
        Only includes fields that are actual Agent.__init__ parameters.
        """
        if not agent_config:
            # Default conservative config matching historical behavior
            return {
                "max_actions_per_step": 5,
                "use_vision": False,
            }

        # Fields that map directly to Agent.__init__ params
        _AGENT_PARAM_KEYS = {
            "enable_planning", "planning_replan_on_stall", "planning_exploration_limit",
            "use_judge", "use_thinking", "message_compaction",
            "max_failures", "final_response_after_failure",
            "loop_detection_enabled", "loop_detection_window",
            "llm_timeout", "step_timeout",
            "use_vision", "vision_detail_level", "flash_mode",
            "override_system_message", "extend_system_message",
            "extraction_schema", "generate_gif", "save_conversation_path",
            "calculate_cost", "skill_ids", "sensitive_data",
        }

        kwargs = {}
        for key in _AGENT_PARAM_KEYS:
            if key in agent_config and agent_config[key] is not None:
                kwargs[key] = agent_config[key]

        # Always set defaults for fields that historically had explicit values
        kwargs.setdefault("max_actions_per_step", 5)
        kwargs.setdefault("use_vision", False)

        return kwargs

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
        agent_config = task_info.get("agent_config")
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

                        # Recreate BrowserSession and Agent (with original agent_config)
                        new_bs = BrowserSession(
                            browser_profile=BrowserProfile(
                                cdp_url=cdp_url,
                                is_local=True,
                                headless=False,
                                highlight_elements=True,
                            ),
                        )
                        agent_kwargs = self._build_agent_kwargs(agent_config)
                        new_agent = Agent(
                            task=task_description,
                            llm=self._create_llm(llm_config),
                            browser_session=new_bs,
                            **agent_kwargs,
                        )
                        try:
                            from agent_browser.stealth.actions import register_stealth_actions
                            register_stealth_actions(new_agent.controller, self._stealth)
                        except Exception:
                            pass
                        current_agent = new_agent
                        current_bs = new_bs

            finally:
                # Close the last BrowserSession
                with contextlib.suppress(Exception):
                    await current_bs.close()

    def _create_llm(self, llm_config: dict):
        """Create LLM instance (using browser-use's ChatOpenAI wrapper).

        Supports both OpenAI and Anthropic-compatible APIs via base_url.
        Reads ANTHROPIC_BASE_URL / OPENAI_BASE_URL from environment.
        """
        from browser_use.llm import ChatOpenAI

        model = llm_config.get("model", "glm-5-turbo")
        api_key = os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_BASE_URL")

        # If model looks like an Anthropic model, use Anthropic credentials
        if any(model.startswith(p) for p in ("claude-", "anthropic")):
            api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
            base_url = base_url or os.getenv("ANTHROPIC_BASE_URL")

        return ChatOpenAI(
            model=model,
            api_key=api_key,
            base_url=base_url,
            temperature=0.1,
            add_schema_to_system_prompt=True,
            dont_force_structured_output=True,
        )

    async def get_task_status(self, session_id: str, task_id: str) -> dict:
        """Get task status."""
        session = self.sessions.get(session_id)
        if not session:
            session = await self._recover_session(session_id)
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
            session = await self._recover_session(session_id)
        if not session:
            raise SessionNotFoundError(f"Session not found: {session_id}")

        # Build VNC URL from session token (same logic as API create_session)
        vnc_token = session.vnc_token
        vnc_base = os.environ.get("VNC_BASE_URL", "")
        vnc_url = f"{vnc_base}/vnc/{vnc_token}/vnc.html?autoconnect=1&resize=scale" if vnc_base and vnc_token else None

        return {
            "session_id": session.session_id,
            "user_id": session.user_id,
            "created_at": session.created_at,
            "last_activity": session.last_activity,
            "idle_time": time.time() - session.last_activity,
            "vnc_url": vnc_url,
            "vnc_token": vnc_token,
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
        """Close a session.

        Handles both local sessions (created on this replica) and remote
        sessions (created on another replica) by always attempting
        shared-store cleanup (pod release + counter decrement).
        """
        # Unregister from backend delegation (before popping session)
        if self._backend is not None:
            self._backend.unregister_session(session_id)
            self._stealth_injected.discard(session_id)

        session = self.sessions.pop(session_id, None)

        if session:
            logger.info(f"Closing session {session_id}")
            # Close CDP connections (Docker and K8s modes)
            conn = self._cdp_connections.pop(session_id, None)
            if conn:
                pw, browser = conn
                with contextlib.suppress(Exception):
                    await browser.close()
                with contextlib.suppress(Exception):
                    await pw.stop()
            # Release browser instance (local pool + shared store)
            await self.browser_pool.release(session_id)
        else:
            logger.warning(
                "Session %s not found locally (may be on another replica), "
                "attempting shared-store cleanup only",
                session_id,
            )
            # Session was created on another replica — release pod directly
            # via shared store (browser_pool.release won't find it locally)
            try:
                await self.store.release_pod(session_id)
                logger.info("Released pod for remote session %s from shared store", session_id)
            except Exception as e:
                logger.warning("Failed to release pod for remote session %s: %s", session_id, e)

        # Always decrement global session counter (even for remote sessions)
        try:
            await self.store.decr_session_count()
        except Exception as e:
            logger.warning("Failed to decrement session counter: %s", e)

        # Clean up session metadata
        if hasattr(self.store, 'remove_session_meta'):
            try:
                await self.store.remove_session_meta(session_id)
            except Exception:
                pass

        logger.info(f"Session closed: {session_id}")

    async def _cleanup_leaked_allocations(self):
        """Clean up allocated_pods entries that don't correspond to any active session.

        This runs once at startup to handle leaked state after API pod crashes
        or restarts where close_session() was never called.
        """
        try:
            allocated = await self.store.get_allocated_pods()
            if not allocated:
                return
            # Any allocated_pods entry whose session_id is not in self.sessions is leaked
            leaked = [
                sid for sid in allocated
                if sid not in self.sessions
            ]
            if leaked:
                logger.warning(
                    "Cleaning up %d leaked pod allocation(s): %s",
                    len(leaked), leaked,
                )
                for sid in leaked:
                    try:
                        await self.store.release_pod(sid)
                    except Exception as e:
                        logger.warning("Failed to release leaked pod for %s: %s", sid, e)
                # Fix session counter: decrement for each leaked session
                for _ in leaked:
                    try:
                        await self.store.decr_session_count()
                    except Exception:
                        pass
                logger.info("Leaked allocations cleaned up (counter fixed)")

            # Also clean orphaned key bindings (key -> session that no longer exists)
            try:
                from agent_browser.state.store import KEY_ALLOCATIONS
                allocations = await self.store.hgetall(KEY_ALLOCATIONS)
                for api_key, sid in allocations.items():
                    if sid not in self.sessions:
                        await self.store.release_key(api_key)
                        logger.info(
                            "Cleaned orphaned key binding: %s -> %s",
                            api_key[:8], sid[:8],
                        )
            except Exception as e:
                logger.warning("Failed to clean orphaned key bindings: %s", e)
        except Exception as e:
            logger.warning("Leaked allocation cleanup failed: %s", e)

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
        """Runtime health check + mixed recycling.

        - Detects crashed Docker/K8s browser instances and auto-recovers
        - Restarts idle K8s pods that exceed BROWSER_IDLE_RESTART_MINUTES threshold
        """
        from agent_browser.models import DockerBrowserInstance, K8sBrowserInstance

        idle_restart_threshold = int(
            os.getenv("BROWSER_IDLE_RESTART_MINUTES", "30")
        ) * 60  # Convert to seconds
        cleanup_interval = int(os.getenv("LEAKED_CLEANUP_INTERVAL_SECONDS", "300"))
        last_cleanup = time.time()

        while True:
            await asyncio.sleep(30)  # Check every 30 seconds
            now = time.time()

            # Periodic leaked allocation cleanup (every 5 min by default)
            if now - last_cleanup > cleanup_interval:
                last_cleanup = now
                try:
                    allocated = await self.store.get_allocated_pods()
                    leaked = [
                        sid for sid in allocated
                        if sid not in self.sessions
                    ]
                    if leaked:
                        logger.warning(
                            "Periodic cleanup: %d leaked allocation(s): %s",
                            len(leaked), leaked,
                        )
                        for sid in leaked:
                            try:
                                await self.store.release_pod(sid)
                            except Exception as e:
                                logger.warning("Failed to release leaked pod %s: %s", sid, e)
                        for _ in leaked:
                            try:
                                await self.store.decr_session_count()
                            except Exception:
                                pass
                        logger.info("Periodic cleanup done (counter fixed)")

                    # Also clean orphaned key bindings
                    try:
                        from agent_browser.state.store import KEY_ALLOCATIONS
                        allocations = await self.store.hgetall(KEY_ALLOCATIONS)
                        for api_key, sid in allocations.items():
                            if sid not in self.sessions:
                                await self.store.release_key(api_key)
                                logger.info(
                                    "Periodic: cleaned orphaned key binding: %s -> %s",
                                    api_key[:8], sid[:8],
                                )
                    except Exception as e:
                        logger.warning("Periodic key binding cleanup failed: %s", e)
                except Exception as e:
                    logger.warning("Periodic cleanup failed: %s", e)

            for session_id, session in list(self.sessions.items()):
                instance = session.browser_instance

                if isinstance(instance, DockerBrowserInstance):
                    # Docker container health check
                    try:
                        instance.container.reload()
                        status = instance.container.status
                    except Exception as e:
                        logger.warning(f"Cannot inspect container for {session_id}: {e}")
                        status = "unknown"

                    if status not in ("running",):
                        logger.error(f"Container for session {session_id} is {status}, recovering...")
                        try:
                            await self.close_session(session_id)
                        except Exception as e:
                            logger.warning(f"Failed to close dead session {session_id}: {e}")

                elif isinstance(instance, K8sBrowserInstance):
                    # K8s pod health check via CDP connectivity
                    try:
                        import aiohttp

                        if not hasattr(self, '_health_cs') or self._health_cs is None or self._health_cs.closed:
                            self._health_cs = aiohttp.ClientSession()
                        async with self._health_cs.get(
                            f"{instance.cdp_url}/json/version",
                            timeout=aiohttp.ClientTimeout(total=3),
                        ) as resp:
                            if resp.status != 200:
                                raise Exception(f"CDP returned {resp.status}")
                    except Exception as e:
                        logger.error(f"K8s pod {instance.pod_name} CDP unhealthy for {session_id}: {e}")
                        try:
                            await self.close_session(session_id)
                        except Exception as close_err:
                            logger.warning(f"Failed to close dead K8s session {session_id}: {close_err}")

            # Mixed recycling: idle pod restart is handled by K8sBrowserNodeManager's warm pool loop

    async def shutdown(self):
        """Shutdown all sessions."""
        logger.info("Shutting down SessionPoolManager...")

        # Cancel background tasks
        for task in (self._monitor_task, self._health_check_task, getattr(self, '_cleanup_task', None)):
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

    async def _recover_session(self, session_id: str) -> UserSession | None:
        """Recover a session created on another replica using shared store data.

        Looks up the session's pod allocation in the ConfigMap, reconstructs
        a K8sBrowserInstance, and stores it locally so subsequent requests on
        this replica can serve it.
        """
        from agent_browser.models import K8sBrowserInstance

        try:
            allocated = await self.store.get_allocated_pods()
            pod_name = allocated.get(session_id)
            if not pod_name:
                return None

            # Resolve pod IP from K8s API
            if self.browser_pool.mode != "k8s" or not self.browser_pool._k8s_manager:
                return None

            k8s_manager = self.browser_pool._k8s_manager
            # Fast path: check local registry first, fall back to full reconciliation
            existing = await k8s_manager.get_pod_info(pod_name)
            if not existing:
                await k8s_manager._reconcile_existing_pods()
            pod_ip = await k8s_manager._get_pod_ip(pod_name)

            cdp_url = f"http://{pod_ip}:80/cdp"
            instance = K8sBrowserInstance(
                instance_id=pod_name,
                cdp_url=cdp_url,
                cdp_port=19222,
                session_id=session_id,
                pod_name=pod_name,
                novnc_url=f"http://{pod_ip}:80",
            )

            # Recover metadata from shared store if available
            meta_user_id = "recovered"
            meta_profile_dir = ""
            meta_created_at = time.time()
            if hasattr(self.store, 'get_session_meta'):
                try:
                    meta = await self.store.get_session_meta(session_id)
                    if meta:
                        meta_user_id = meta.get("user_id", "recovered")
                        meta_profile_dir = meta.get("profile_dir", "")
                        meta_created_at = meta.get("created_at", time.time())
                except Exception:
                    pass

            session = UserSession(
                session_id=session_id,
                user_id=meta_user_id,
                browser_instance=instance,
                profile_dir=meta_profile_dir,
                created_at=meta_created_at,
                last_activity=time.time(),
            )
            self.sessions[session_id] = session
            logger.info("Recovered session %s from shared store (pod %s)", session_id, pod_name)
            return session

        except Exception as e:
            logger.warning("Session recovery failed for %s: %s", session_id, e)
            return None

    async def _get_page(self, session_id: str) -> Page:
        """Get the Playwright Page object for a session (supports Local, Docker, and K8s instances).

        For K8s/Docker mode, if the session is not found locally (created on another
        replica), attempts to recover it from the shared store and reconnect via CDP.
        """
        session = self.sessions.get(session_id)
        if not session:
            # Try to recover session from shared store (multi-replica support)
            session = await self._recover_session(session_id)
            if not session:
                raise SessionNotFoundError(f"Session not found: {session_id}")

        instance = session.browser_instance

        from agent_browser.models import K8sBrowserInstance
        if isinstance(instance, DockerBrowserInstance):
            return await self._get_docker_page(session_id, instance)

        if isinstance(instance, K8sBrowserInstance):
            return await self._get_k8s_page(session_id, instance)

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
        if session_id in self._cdp_connections:
            pw, browser = self._cdp_connections[session_id]
            try:
                contexts = browser.contexts
                if contexts and contexts[0].pages:
                    return contexts[0].pages[0]
            except Exception:
                # Connection broken, clean up and reconnect
                old_pw, old_browser = self._cdp_connections.pop(session_id, (None, None))
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
                self._cdp_connections[session_id] = (pw, browser)

                contexts = browser.contexts
                if contexts and contexts[0].pages:
                    return contexts[0].pages[0]
                context = contexts[0] if contexts else await browser.new_context()
                return await context.new_page()
            except Exception as e:
                last_error = e
                logger.warning(f"CDP connect attempt {attempt + 1}/3 failed: {e}")
                # Clean up failed connection
                if session_id in self._cdp_connections:
                    _, failed_browser = self._cdp_connections.pop(session_id, (None, None))
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

    async def _get_k8s_page(self, session_id: str, instance: K8sBrowserInstance) -> Page:
        """Get Page from K8s browser pod via CDP (with retry).

        Similar to _get_docker_page but targets K8s pod DNS addresses.
        Reuses the same _cdp_connections cache for CDP connection reuse.
        """
        # Reuse existing CDP connection
        if session_id in self._cdp_connections:
            pw, browser = self._cdp_connections[session_id]
            try:
                contexts = browser.contexts
                if contexts and contexts[0].pages:
                    return contexts[0].pages[0]
            except Exception:
                old_pw, old_browser = self._cdp_connections.pop(session_id, (None, None))
                if old_browser:
                    with contextlib.suppress(Exception):
                        await old_browser.close()
                if old_pw:
                    with contextlib.suppress(Exception):
                        await old_pw.stop()

        # Establish new CDP connection (K8s pods may need extra time after allocation)
        last_error = None
        for attempt in range(3):
            try:
                pw = await async_playwright().start()
                browser = await pw.chromium.connect_over_cdp(instance.cdp_url)
                self._cdp_connections[session_id] = (pw, browser)

                contexts = browser.contexts
                if contexts and contexts[0].pages:
                    return contexts[0].pages[0]
                context = contexts[0] if contexts else await browser.new_context()
                return await context.new_page()
            except Exception as e:
                last_error = e
                logger.warning(f"K8s CDP connect attempt {attempt + 1}/3 failed: {e}")
                if session_id in self._cdp_connections:
                    _, failed_browser = self._cdp_connections.pop(session_id, (None, None))
                    try:
                        if failed_browser:
                            await failed_browser.close()
                    except Exception:
                        pass
                    with contextlib.suppress(Exception):
                        await pw.stop()
                if attempt < 2:
                    await asyncio.sleep(3 * (attempt + 1))

        raise ConnectionError(f"Failed to connect to K8s CDP at {instance.cdp_url} after 3 attempts: {last_error}")

    # ── Backend delegation infrastructure ───────────────────────

    def _get_backend(self):
        """Get or lazily create a LocalCDPBackend instance (logic delegate only).

        The backend is used purely for operation delegation -- it does NOT
        manage browser connections (pool_manager handles that via _get_page).
        """
        if self._backend is None:
            from agent_browser.browser.local import LocalCDPBackend, LocalSession

            backend = LocalCDPBackend.__new__(LocalCDPBackend)
            backend._sessions = {}
            self._backend = backend
        return self._backend

    async def _ensure_backend_session(self, session_id: str) -> None:
        """Lazily register a session in the LocalCDPBackend on first delegation.

        Called by delegated methods before invoking backend operations.
        Uses page.context (Playwright built-in) to resolve BrowserContext
        for tab operations -- works for Local, Docker, and K8s modes.

        Also injects JS stealth patches + timing noise to ensure API-path
        pages have the same anti-detection baseline as CLI-path pages.
        """
        backend = self._get_backend()
        if session_id in backend._sessions:
            return
        page = await self._get_page(session_id)
        await self._inject_stealth_if_needed(session_id, page)
        await backend.register_session(session_id, page, page.context)

    async def _inject_stealth_if_needed(self, session_id: str, page) -> None:
        """Inject JS stealth patches + timing noise once per session.

        Safe to call multiple times -- skips if already injected.
        Called by _ensure_backend_session (delegated path) and by
        direct interactive methods (navigate/click/fill/scroll) via
        their pre_action helper.
        """
        if session_id in self._stealth_injected:
            return
        self._stealth_injected.add(session_id)
        try:
            from agent_browser.stealth.patches import inject_stealth_patches
            await inject_stealth_patches(page)
        except Exception as e:
            logger.warning("Stealth JS patches failed for %s: %s", session_id[:8], e)
        try:
            from agent_browser.stealth.enhancer import StealthEnhancer as _SE
            await _SE.inject_timing_noise(page)
        except Exception as e:
            logger.warning("Stealth timing noise failed for %s: %s", session_id[:8], e)

    async def navigate(self, session_id: str, request: NavigateRequest) -> dict:
        """Page navigation."""
        page = await self._get_page(session_id)
        await self._inject_stealth_if_needed(session_id, page)

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

    async def snapshot(self, session_id: str, interactive_only: bool = True,
                       iframe_selector: str | None = None) -> SnapshotResponse:
        """Get DOM snapshot.

        Args:
            interactive_only: Only include interactive elements (default True).
            iframe_selector: CSS selector for iframes to also capture elements from.
                When provided, elements inside matching iframes are included with
                viewport-relative bounding_box coordinates. Fully backward compatible
                (default None = original behavior, no iframe traversal).
        """
        page = await self._get_page(session_id)

        if iframe_selector:
            # Enhanced script with iframe penetration
            safe_sel = json.dumps(iframe_selector)
            elements_script = f"""
            () => {{
                const selectors = 'button, a, input, textarea, select, [role="button"], [onclick]';
                const allElements = [];
                let refIndex = 0;

                // Top-level document elements
                document.querySelectorAll(selectors).forEach(el => {{
                    if (el.offsetParent === null && el.getClientRects().length === 0) return;

                    const ref = '@e' + refIndex;
                    el.setAttribute('data-ab-ref', ref);
                    refIndex++;

                    const rect = el.getBoundingClientRect();
                    allElements.push({{
                        ref: ref,
                        tag: el.tagName.toLowerCase(),
                        text: (el.textContent || el.value || el.placeholder || '').substring(0, 100).trim(),
                        role: el.getAttribute('role') || el.tagName.toLowerCase(),
                        type: el.type || null,
                        placeholder: el.placeholder || null,
                        href: el.href || null,
                        is_visible: rect.width > 0 && rect.height > 0,
                        is_enabled: !el.disabled,
                        bounding_box: {{x: rect.x, y: rect.y, width: rect.width, height: rect.height}}
                    }});
                }});

                // Iframe penetration: traverse inside matching iframes
                document.querySelectorAll({safe_sel}).forEach(iframe => {{
                    try {{
                        const doc = iframe.contentDocument;
                        if (!doc) return;
                        const iframeRect = iframe.getBoundingClientRect();
                        const iframeName = iframe.getAttribute('name') || iframe.id || '';

                        doc.querySelectorAll(selectors).forEach(el => {{
                            if (el.offsetParent === null && el.getClientRects().length === 0) return;

                            const ref = '@e' + refIndex;
                            el.setAttribute('data-ab-ref', ref);
                            refIndex++;

                            const rect = el.getBoundingClientRect();
                            allElements.push({{
                                ref: ref,
                                tag: el.tagName.toLowerCase(),
                                text: (el.textContent || el.value || el.placeholder || '').substring(0, 100).trim(),
                                role: el.getAttribute('role') || el.tagName.toLowerCase(),
                                type: el.type || null,
                                placeholder: el.placeholder || null,
                                href: el.href || null,
                                is_visible: rect.width > 0 && rect.height > 0,
                                is_enabled: !el.disabled,
                                bounding_box: {{
                                    x: Math.round(iframeRect.x + rect.x),
                                    y: Math.round(iframeRect.y + rect.y),
                                    width: rect.width,
                                    height: rect.height
                                }},
                                iframe: iframeName
                            }});
                        }});
                    }} catch(e) {{
                        // Cross-origin iframe: silently skip
                    }}
                }});

                return {{
                    url: window.location.href,
                    title: document.title,
                    elements: allElements
                }};
            }}
            """
        else:
            # Original script (unchanged for backward compatibility)
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

        if request.x is not None and request.y is not None:
            # Coordinate-based click (for iframe content or arbitrary positions)
            await page.mouse.click(
                request.x, request.y,
                button=request.button,
                click_count=request.click_count,
                delay=request.delay,
            )
        elif request.ref:
            # Ref-based click (existing behavior)
            if not request.ref.startswith("@e"):
                raise ValueError(f"Invalid ref format: {request.ref}")

            # Find element via data-ab-ref attribute (stable, immune to DOM position changes)
            element = await page.query_selector(f'[data-ab-ref="{request.ref}"]')
            if not element:
                raise ValueError(f"Element {request.ref} not found. DOM may have changed since snapshot.")

            # Execute click
            await element.click(button=request.button, click_count=request.click_count, delay=request.delay)
        else:
            raise ValueError("Click requires either 'ref' or both 'x' and 'y' parameters")

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
        await self._stealth.pre_action("navigate")
        await page.go_back(wait_until=wait_until, timeout=timeout)

        session = self.sessions.get(session_id)
        if session:
            session.mark_activity()

        return {"status": "ok", "url": page.url}

    async def mouse_move(self, session_id: str, x: float, y: float) -> dict:
        """Move mouse."""
        page = await self._get_page(session_id)
        await self._stealth.pre_action("general")
        await page.mouse.move(x, y)

        session = self.sessions.get(session_id)
        if session:
            session.mark_activity()

        return {"status": "ok", "x": x, "y": y}

    async def keyboard_press(self, session_id: str, key: str) -> dict:
        """Press key."""
        page = await self._get_page(session_id)
        await self._stealth.pre_action("input")
        await page.keyboard.press(key)

        session = self.sessions.get(session_id)
        if session:
            session.mark_activity()

        return {"status": "ok", "key": key}

    # ── New Actions (delegated to LocalCDPBackend) ─────────────────

    async def search_page(
        self, session_id: str, pattern: str, **kwargs,
    ) -> dict:
        """Search page text content (supports regex, plain text)."""
        await self._ensure_backend_session(session_id)
        return await self._get_backend().search_page(session_id, pattern, **kwargs)

    async def find_elements(self, session_id: str, selector: str, **kwargs) -> dict:
        """Find elements by CSS selector with metadata."""
        await self._ensure_backend_session(session_id)
        return await self._get_backend().find_elements(session_id, selector, **kwargs)

    async def get_dropdown_options(self, session_id: str, ref: str) -> list[dict]:
        """Get dropdown options from a <select> element."""
        await self._ensure_backend_session(session_id)
        return await self._get_backend().get_dropdown_options(session_id, ref)

    async def select_dropdown_option(self, session_id: str, ref: str, option_text: str) -> None:
        """Select dropdown option by visible text."""
        await self._stealth.pre_action("input")
        await self._ensure_backend_session(session_id)
        return await self._get_backend().select_dropdown_option(session_id, ref, option_text)

    async def upload_file(self, session_id: str, ref: str, file_paths: list[str]) -> None:
        """Upload files to <input type=file> element."""
        await self._stealth.pre_action("input")
        await self._ensure_backend_session(session_id)
        return await self._get_backend().upload_file(session_id, ref, file_paths)

    async def screenshot(self, session_id: str, **kwargs) -> bytes:
        """Take screenshot (full page or element by ref)."""
        await self._ensure_backend_session(session_id)
        return await self._get_backend().screenshot(session_id, **kwargs)

    async def save_as_pdf(self, session_id: str, **kwargs) -> str:
        """Save current page as PDF. Returns file path."""
        await self._ensure_backend_session(session_id)
        return await self._get_backend().save_as_pdf(session_id, **kwargs)

    async def send_keys(self, session_id: str, keys: str) -> None:
        """Send complex key sequence (e.g., 'Meta+a', 'Shift+Home')."""
        await self._stealth.pre_action("input")
        await self._ensure_backend_session(session_id)
        await self._get_backend().send_keys(session_id, keys)

        session = self.sessions.get(session_id)
        if session:
            session.mark_activity()

    async def scroll_to_text(self, session_id: str, text: str, **kwargs) -> bool:
        """Scroll until text becomes visible. Returns True if found."""
        await self._stealth.pre_action("scroll")
        await self._ensure_backend_session(session_id)
        return await self._get_backend().scroll_to_text(session_id, text, **kwargs)

    async def switch_tab(self, session_id: str, index: int) -> None:
        """Switch to tab by index."""
        await self._stealth.pre_action("general")
        await self._ensure_backend_session(session_id)
        return await self._get_backend().switch_tab(session_id, index)

    async def open_tab(self, session_id: str, url: str | None = None) -> int:
        """Open new tab. Returns new tab index."""
        await self._stealth.pre_action("navigate")
        await self._ensure_backend_session(session_id)
        return await self._get_backend().open_tab(session_id, url=url)

    async def close_tab(self, session_id: str, index: int | None = None) -> None:
        """Close tab by index (or last tab if None)."""
        await self._stealth.pre_action("general")
        await self._ensure_backend_session(session_id)
        return await self._get_backend().close_tab(session_id, index=index)

    async def extract_content(self, session_id: str, **kwargs) -> str:
        """Extract content from page (text/html/links/images)."""
        await self._ensure_backend_session(session_id)
        return await self._get_backend().extract_content(session_id, **kwargs)

    async def get_tabs_info(self, session_id: str) -> list[dict]:
        """Get info about all open tabs."""
        await self._ensure_backend_session(session_id)
        return await self._get_backend().get_tabs_info(session_id)
