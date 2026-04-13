"""FastAPI server -- HTTP REST API for agent-browser.

Maps REST endpoints to SessionPoolManager business logic.
All browser operations go through this layer when running in API mode.

Run:
    uvicorn agent_browser.api:app --port 8000

Endpoints:
    GET  /health                          -- Server health + pool stats
    GET  /sessions                        -- List all sessions
    POST /sessions/create                 -- Create session
    GET  /sessions/{id}                   -- Get session status
    DELETE /sessions/{id}                   -- Delete session
    POST /sessions/{id}/navigate           -- Navigate to URL
    GET  /sessions/{id}/url                -- Current URL
    GET  /sessions/{id}/title              -- Page title
    POST /sessions/{id}/snapshot            -- DOM snapshot
    POST /sessions/{id}/click               -- Click element
    POST /sessions/{id}/fill                -- Fill input
    POST /sessions/{id}/scroll              -- Scroll page
    POST /sessions/{id}/evaluate            -- Execute JS
    POST /sessions/{id}/back                -- Go back
    POST /sessions/{id}/mouse/move         -- Move mouse
    POST /sessions/{id}/keyboard/press     -- Press key
    POST /sessions/{id}/task                -- Submit agent task
    GET  /sessions/{id}/tasks/{task_id}   -- Task status
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Request, Depends
from fastapi.responses import Response
from pydantic import BaseModel

from agent_browser.models import (
    ClickRequest,
    EvaluateRequest,
    FillRequest,
    K8sBrowserInstance,
    NavigateRequest,
    ResourceExhaustedError,
    ScrollRequest,
    SessionNotFoundError,
    SnapshotResponse,
    WaitRequest,
)
from agent_browser.session.pool_manager import SessionPoolManager

logger = logging.getLogger(__name__)

# Ensure profile storage path is writable (defaults to /data which may not exist)
if not os.environ.get("PROFILE_STORAGE"):
    os.environ["PROFILE_STORAGE"] = os.path.join(tempfile.gettempdir(), "agent-browser-profiles")

app = FastAPI(
    title="Agent Browser API",
    version="0.1.0",
    description="Anti-detection browser automation REST API",
)

# ── Module-level singleton: SessionPoolManager ──────────────

_pool: SessionPoolManager | None = None


def get_pool() -> SessionPoolManager:
    """Get or lazily create the session pool.

    Reads configuration from environment variables (set by K8s ConfigMap/Deployment,
    Docker Compose, or manual export). Falls back to sensible defaults.
    """
    global _pool
    if _pool is None:
        _pool = SessionPoolManager(
            max_concurrent=int(os.getenv("MAX_SESSIONS", "10")),
            idle_timeout=int(os.getenv("IDLE_TIMEOUT_SECONDS", "1800")),
            browser_mode=os.getenv("BROWSER_MODE", "local"),  # "local" | "docker" | "k8s"
        )
    return _pool


# ── Auth dependency ──────────────────────────────────────────────────

API_KEY = os.getenv("API_KEY", "")


class KeyManager:
    """Multi-API-Key authentication and 1-key-1-browser allocation.

    Supports two modes:
    - Multi-key: API_KEYS env var (JSON array or comma-separated) defines valid keys
    - Single-key (fallback): API_KEY env var for backward compatibility
    - Open mode: neither set → no authentication required

    Manages three-way mapping: api_key → session_id → pod_name.
    State backed by StateStore (K8s ConfigMap+CAS in distributed mode,
    in-memory dicts otherwise).
    """

    def __init__(self, store=None):
        raw = os.getenv("API_KEYS", "[]")
        try:
            self.valid_keys: list[str] = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            self.valid_keys = [k.strip() for k in raw.split(",") if k.strip()]
        self._fallback_key = os.getenv("API_KEY", "")

        # State store (K8s ConfigMap or in-memory)
        from agent_browser.state.store import create_state_store
        self.store = store or create_state_store()

    @property
    def is_multi_key(self) -> bool:
        return len(self.valid_keys) > 0

    def validate(self, key: str) -> bool:
        """Check if a key is valid."""
        if self.is_multi_key:
            return key in self.valid_keys
        # Fallback: single key mode
        return not self._fallback_key or key == self._fallback_key

    async def allocate(self, key: str, session_id: str, pod_name: str | None = None):
        """Bind a key to a session (and optionally a pod).

        Raises 409 if the key is already bound to a different session.
        Atomic via CAS when using K8sSharedState.
        """
        await self.store.allocate_key(key, session_id, pod_name or "")

    async def release(self, key: str):
        """Release a key and mark its associated pod as idle."""
        await self.store.release_key(key)

    async def get_pod_for_key(self, key: str) -> str | None:
        return await self.store.get_pod_for_key(key)

    async def get_key_for_session(self, session_id: str) -> str | None:
        return await self.store.get_key_for_session(session_id)

    async def get_all_pod_idle_since(self) -> dict[str, float]:
        """Get all pod idle timestamps (for health check loop)."""
        return await self.store.get_all_pod_idle_since()


# Module-level singleton
_key_manager: KeyManager | None = None


def get_key_manager() -> KeyManager:
    global _key_manager
    if _key_manager is None:
        _key_manager = KeyManager()
    return _key_manager


async def api_key_auth(x_api_key: str | None = Header(None)) -> str:
    """API Key authentication dependency (multi-key + single-key support).

    Validates X-API-Key against KeyManager's valid key list.
    - Multi-key mode: key must be in API_KEYS list
    - Single-key mode: key must match API_KEY env var
    - Open mode: no keys configured → no auth required
    """
    km = get_key_manager()
    if not x_api_key:
        # No key provided
        if km.is_multi_key or km._fallback_key:
            raise HTTPException(status_code=403, detail="Missing API Key")
        return ""  # Fully open mode

    if not km.validate(x_api_key):
        raise HTTPException(status_code=403, detail="Invalid API Key")

    return x_api_key


# ── Request/Response models not in models.py ────────────────────────────


class CreateSessionRequest(BaseModel):
    user_id: str
    browser_mode: str = "local"


class TaskSubmitRequest(BaseModel):
    task: str
    model: str = "glm-5-turbo"
    max_steps: int = 10


class MouseMoveRequest(BaseModel):
    x: float
    y: float


class KeyPressRequest(BaseModel):
    key: str


# ── Lifespan ──────────────────────────────────────────────────────────


@app.on_event("startup")
async def _startup():
    global _pool
    logger.info("Starting Agent Browser API server...")
    pool = get_pool()
    pool.start()

    # Initialize state store (triggers K8s ConfigMap connection if in cluster)
    km = get_key_manager()
    try:
        await km.store.read_cache()
        logger.info("State store initialized: %s", type(km.store).__name__)
    except Exception as e:
        logger.warning(
            "State store init failed (%s), falling back to InMemoryStateStore: %s",
            type(e).__name__, e,
        )
        from agent_browser.state.store import InMemoryStateStore
        km.store = InMemoryStateStore()

    # Wire KeyManager into pool for mixed recycling health checks
    pool._key_manager = km
    # Share store reference with pool for session counter
    if hasattr(pool, 'store'):
        pool.store = km.store
    _pool = pool
    logger.info(f"API server ready (max_concurrent={pool.max_concurrent}, mode={pool.browser_pool.mode})")


@app.on_event("shutdown")
async def _shutdown():
    global _pool
    if _pool:
        logger.info("Shutting down API server...")
        await _pool.shutdown()
        _pool = None


# ── Health ─────────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    """Health check endpoint (public, no auth required)."""
    pool = get_pool()
    km = get_key_manager()
    return {
        "status": "ok",
        "sessions": len(pool.sessions),
        "max_concurrent": pool.max_concurrent,
        "browser_mode": pool.browser_pool.mode,
        "auth_mode": "multi-key" if km.is_multi_key else ("single-key" if km._fallback_key else "open"),
        "valid_keys": len(km.valid_keys) if km.is_multi_key else (1 if km._fallback_key else 0),
    }


# ── Auth endpoint (for ForwardAuth middleware / browser proxy) ────────


@app.get("/auth")
async def auth_endpoint(request: Request):
    """Validate API Key, return 200/403.

    Used by external systems (Traefik ForwardAuth, monitoring, etc.)
    to verify API Key without invoking business logic.
    Supports multi-key mode via KeyManager.
    """
    km = get_key_manager()
    key = request.headers.get("X-API-Key", "")
    if km.validate(key):
        return Response(status_code=200)
    return Response(status_code=403)


# ── Browser reverse proxy ───────────────────────────────────────────


@app.api_route("/browser-proxy/{session_id}/{path:path}", methods=["GET", "POST", "HEAD", "PUT", "DELETE", "OPTIONS", "PATCH"])
async def browser_proxy(session_id: str, path: str, request: Request,
                        key: str = Depends(api_key_auth)):
    """Reverse proxy to browser pod's noVNC.

    Routes requests from b.agent-browser.local (via Traefik)
    to the actual browser pod. Validates that the key owns this session.
    """
    import httpx
    from urllib.parse import urljoin

    km = get_key_manager()

    # Verify this key is authorized for the requested session
    bound_session = await km.get_key_for_session(session_id)
    # The key used must be the one bound to this session
    if bound_session != key:
        raise HTTPException(
            status_code=403,
            detail="Key not authorized for this session",
        )

    pool = get_pool()
    session = pool.sessions.get(session_id)
    instance = session.browser_instance if session else None
    if not instance:
        raise HTTPException(
            status_code=404,
            detail=f"Session {session_id} not found or has no browser instance",
        )

    # Determine target URL based on instance type
    if isinstance(instance, K8sBrowserInstance):
        target_base = instance.novnc_url or f"http://{instance.pod_name}.agent-browser-browser:6080"
    else:
        container_ip = getattr(instance, "container_ip", None)
        if not container_ip:
            raise HTTPException(
                status_code=502,
                detail=f"Browser instance for session {session_id} has no reachable address",
            )
        target_base = f"http://{container_ip}:6080"

    target_url = urljoin(target_base, f"/{path}")

    # Build forward headers (strip hop-by-hop headers)
    exclude_headers = {"host", "content-length", "transfer-encoding", "connection"}
    forward_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in exclude_headers
    }

    body = await request.body()

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        try:
            resp = await client.request(
                method=request.method,
                url=target_url,
                headers=forward_headers,
                content=body,
            )
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                media_type=resp.headers.get("content-type"),
                headers={
                    "X-Proxy-By": "agent-browser-api",
                },
            )
        except httpx.ConnectError:
            raise HTTPException(
                status_code=502,
                detail=f"Cannot connect to browser at {target_base}",
            )


# ── Session CRUD ───────────────────────────────────────────────────────


@app.get("/sessions")
async def list_sessions(_: str = Depends(api_key_auth)):
    pool = get_pool()
    sessions = []
    for sid, s in pool.sessions.items():
        sessions.append(
            {
                "session_id": sid,
                "user_id": s.user_id,
                "created_at": s.created_at,
                "last_activity": s.last_activity,
            }
        )
    return {"sessions": sessions, "total": len(sessions)}


@app.post("/sessions/create")
async def create_session(req: CreateSessionRequest,
                        key: str = Depends(api_key_auth)):
    pool = get_pool()
    km = get_key_manager()
    try:
        result = await pool.create_session(user_id=req.user_id)
        # create_session returns tuple (session_id, node_info)
        sid = result[0] if isinstance(result, tuple) else result
        node_info = result[1] if isinstance(result, tuple) and len(result) > 1 else None

        # Bind key → session → pod
        pod_name = None
        session = pool.sessions.get(sid)
        instance = session.browser_instance if session else None
        if instance:
            if hasattr(instance, 'pod_name'):
                pod_name = instance.pod_name
            elif hasattr(instance, 'container_name'):
                pod_name = instance.container_name

        try:
            await km.allocate(key, sid, pod_name)
        except Exception:
            # Rollback: session was created but key binding failed
            logger.warning("km.allocate failed for session %s, rolling back", sid)
            with contextlib.suppress(Exception):
                await pool.close_session(sid)
            raise

        resp = {"session_id": sid, "user_id": req.user_id}
        if node_info:
            if node_info.get("novnc_url"):
                resp["novnc_url"] = node_info["novnc_url"]
            if node_info.get("public_novnc_port"):
                resp["public_novnc_port"] = node_info["public_novnc_port"]
        if pod_name:
            resp["pod_name"] = pod_name
        return resp
    except HTTPException:
        raise  # Re-raise 409 conflict etc.
    except ResourceExhaustedError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Profile storage error: {e}")
    except Exception as e:
        logger.exception("create_session failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/sessions/{session_id}")
async def get_session(session_id: str,
                     _: str = Depends(api_key_auth)):
    pool = get_pool()
    try:
        return await pool.get_session_status(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str,
                        key: str = Depends(api_key_auth)):
    pool = get_pool()
    km = get_key_manager()
    try:
        await pool.close_session(session_id)
        # Release key binding
        await km.release(key)
        return {}
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


# ── Navigation ────────────────────────────────────────────────────────


@app.post("/sessions/{session_id}/navigate")
async def navigate(session_id: str, req: NavigateRequest,
                  _: str = Depends(api_key_auth)):
    pool = get_pool()
    try:
        return await pool.navigate(session_id, req)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    except Exception as e:
        logger.warning("Navigate failed for session %s: %s: %s", session_id, type(e).__name__, e)
        raise HTTPException(status_code=502, detail={
            "error": "navigation_failed",
            "type": type(e).__name__,
            "message": str(e),
            "hint": "Page may already be at the target URL, or the browser is unresponsive."
        })


@app.post("/sessions/{session_id}/back")
async def go_back(session_id: str, wait_until: str = "domcontentloaded", timeout: int = 10000,
                _: str = Depends(api_key_auth)):
    pool = get_pool()
    try:
        return await pool.go_back(session_id, wait_until=wait_until, timeout=timeout)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


@app.get("/sessions/{session_id}/url")
async def get_url(session_id: str,
                 _: str = Depends(api_key_auth)):
    pool = get_pool()
    try:
        url = await pool.get_url(session_id)
        return {"url": url}
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


@app.get("/sessions/{session_id}/title")
async def get_title(session_id: str,
                   _: str = Depends(api_key_auth)):
    pool = get_pool()
    try:
        title = await pool.get_title(session_id)
        return {"title": title}
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


# ── Interaction ──────────────────────────────────────────────────────


@app.post("/sessions/{session_id}/snapshot")
async def snapshot(session_id: str, interactive_only: bool = False,
                   iframe_selector: str | None = None,
                   _: str = Depends(api_key_auth)):
    pool = get_pool()
    try:
        result = await pool.snapshot(
            session_id, interactive_only=interactive_only,
            iframe_selector=iframe_selector,
        )
        return result.model_dump() if isinstance(result, SnapshotResponse) else result
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


@app.post("/sessions/{session_id}/click")
async def click(session_id: str, req: ClickRequest,
               _: str = Depends(api_key_auth)):
    pool = get_pool()
    try:
        return await pool.click(session_id, req)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/sessions/{session_id}/fill")
async def fill(session_id: str, req: FillRequest,
              _: str = Depends(api_key_auth)):
    pool = get_pool()
    try:
        return await pool.fill(session_id, req)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


@app.post("/sessions/{session_id}/scroll")
async def scroll(session_id: str, req: ScrollRequest,
                _: str = Depends(api_key_auth)):
    pool = get_pool()
    try:
        return await pool.scroll(session_id, req)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


@app.post("/sessions/{session_id}/evaluate")
async def evaluate(session_id: str, req: EvaluateRequest,
                  _: str = Depends(api_key_auth)):
    pool = get_pool()
    try:
        result = await pool.evaluate(session_id, req)
        # pool.evaluate() may return a dict (e.g. {"status": "ok", "result": ...}) or a raw value
        if isinstance(result, dict):
            return result
        return {"result": result}
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    except Exception as e:
        logger.warning("Evaluate failed for session %s: %s: %s", session_id, type(e).__name__, e)
        raise HTTPException(
            status_code=400,
            detail={
                "error": "evaluation_failed",
                "type": type(e).__name__,
                "message": str(e),
                "hint": "Check JavaScript expression for syntax errors. "
                       "Common issues: unescaped quotes, invalid regex flags, "
                       "or expressions that don't return a value.",
            },
        )


@app.post("/sessions/{session_id}/wait")
async def wait_for_selector(session_id: str, req: WaitRequest,
                          _: str = Depends(api_key_auth)):
    pool = get_pool()
    try:
        return await pool.wait_for_selector(session_id, req)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


@app.post("/sessions/{session_id}/mouse/move")
async def mouse_move(session_id: str, req: MouseMoveRequest,
                    _: str = Depends(api_key_auth)):
    pool = get_pool()
    try:
        return await pool.mouse_move(session_id, x=req.x, y=req.y)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


@app.post("/sessions/{session_id}/keyboard/press")
async def keyboard_press(session_id: str, req: KeyPressRequest,
                        _: str = Depends(api_key_auth)):
    pool = get_pool()
    try:
        return await pool.keyboard_press(session_id, key=req.key)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


# ── Agent Tasks ───────────────────────────────────────────────────────


@app.post("/sessions/{session_id}/task")
async def submit_task(session_id: str, req: TaskSubmitRequest,
                     _: str = Depends(api_key_auth)):
    pool = get_pool()
    try:
        llm_config = {
            "model": req.model,
            # Pass through any extra fields for LLM factory
        }
        task_id = await pool.submit_task(
            session_id=session_id,
            task=req.task,
            llm_config=llm_config,
            max_steps=req.max_steps,
        )
        return {"task_id": task_id, "session_id": session_id}
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    except ResourceExhaustedError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.exception("submit_task failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/sessions/{session_id}/tasks/{task_id}")
async def get_task_status(session_id: str, task_id: str,
                         _: str = Depends(api_key_auth)):
    pool = get_pool()
    try:
        status = await pool.get_task_status(session_id, task_id)
        return {"task_id": task_id, **status}
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session/task {session_id}/{task_id} not found")


# ── Legacy compat endpoints ───────────────────────────────────────────


@app.post("/tasks")
async def legacy_create_task(req: TaskSubmitRequest,
                             _: str = Depends(api_key_auth)):
    """Legacy endpoint: creates an implicit session, submits task."""
    pool = get_pool()
    try:
        session_id = await pool.create_session(user_id="legacy_api")
        sid = session_id[0] if isinstance(session_id, tuple) else session_id
        llm_config = {"model": req.model}
        task_id = await pool.submit_task(
            session_id=sid,
            task=req.task,
            llm_config=llm_config,
            max_steps=req.max_steps,
        )
        return {"task_id": task_id, "session_id": sid}
    except ResourceExhaustedError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.exception("legacy create_task failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/tasks/{task_id}")
async def legacy_get_task_status(task_id: str,
                                 _: str = Depends(api_key_auth)):
    """Legacy endpoint: find task by ID across all sessions."""
    pool = get_pool()
    # Search all sessions for this task_id
    for sid, session in pool.sessions.items():
        if task_id in session.tasks:
            info = session.tasks[task_id]
            return {
                "task_id": task_id,
                "session_id": sid,
                **info,
            }
    raise HTTPException(status_code=404, detail=f"Task {task_id} not found in any session")
