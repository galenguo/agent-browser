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

import asyncio
import contextlib
import logging
import os
import tempfile

import aiohttp
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from agent_browser.api.auth import load_keys, require_api_key
from agent_browser.models import (
    ClickRequest,
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
    """Get or lazily create the session pool."""
    global _pool
    if _pool is None:
        browser_mode = os.environ.get("BROWSER_MODE", "local")
        max_concurrent = int(os.environ.get("MAX_SESSIONS", "10"))
        idle_timeout = int(os.environ.get("IDLE_TIMEOUT_SECONDS", "1800"))
        _pool = SessionPoolManager(
            max_concurrent=max_concurrent,
            idle_timeout=idle_timeout,
            browser_mode=browser_mode,
        )
    return _pool


# ── Auth dependency ──────────────────────────────────────────────────
# require_api_key is imported from agent_browser.api.auth


def _get_owned_session(pool, session_id: str, api_key: str) -> UserSession:
    """Get a session and verify the requesting key owns it."""
    session = pool.sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    if session.owner_key and session.owner_key != api_key:
        raise HTTPException(status_code=403, detail="Access denied: session belongs to another key")
    return session


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
    load_keys()
    # Parse POD_NAME (downward API) → POD_INDEX + VNC_BASE_URL
    pod_name = os.environ.get("POD_NAME", "")
    if pod_name:
        parts = pod_name.rsplit("-", 1)
        if len(parts) == 2 and parts[1].isdigit():
            os.environ.setdefault("POD_INDEX", parts[1])
    os.environ.setdefault("VNC_BASE_URL", "https://agent-browser-vnc.vpc-dale.gimcyun.com")
    logger.info("Starting Agent Browser API server...")
    pool = get_pool()
    pool.start()
    _pool = pool
    logger.info(f"API server ready (max_concurrent={pool.max_concurrent})")


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
    pool = get_pool()
    return {
        "status": "ok",
        "sessions": len(pool.sessions),
        "max_concurrent": pool.max_concurrent,
        "browser_mode": pool.browser_pool.mode,
    }


# ── Session CRUD ───────────────────────────────────────────────────────


@app.get("/sessions")
async def list_sessions(api_key: str = Depends(require_api_key)):
    pool = get_pool()
    sessions = []
    for sid, s in pool.sessions.items():
        if not s or s.owner_key != api_key:
            continue
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
async def create_session(req: CreateSessionRequest, api_key: str = Depends(require_api_key)):
    pool = get_pool()
    try:
        session_id = await pool.create_session(user_id=req.user_id, owner_key=api_key)
        # create_session returns tuple (session_id, node_info); we only need the ID
        sid = session_id[0] if isinstance(session_id, tuple) else session_id
        # Build VNC URL from session token
        session = pool.sessions.get(sid)
        vnc_token = session.vnc_token if session else ""
        vnc_base = os.environ.get("VNC_BASE_URL", "")
        vnc_url = f"{vnc_base}/vnc/{vnc_token}/" if vnc_base and vnc_token else None
        return {"session_id": sid, "user_id": req.user_id, "vnc_url": vnc_url, "vnc_token": vnc_token}
    except ResourceExhaustedError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Profile storage error: {e}")
    except Exception as e:
        logger.exception("create_session failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/sessions/{session_id}")
async def get_session(session_id: str, api_key: str = Depends(require_api_key)):
    pool = get_pool()
    _get_owned_session(pool, session_id, api_key)
    try:
        return await pool.get_session_status(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str, api_key: str = Depends(require_api_key)):
    pool = get_pool()
    _get_owned_session(pool, session_id, api_key)
    try:
        await pool.close_session(session_id)
        return {}
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


# ── Navigation ────────────────────────────────────────────────────────


@app.post("/sessions/{session_id}/navigate")
async def navigate(session_id: str, req: NavigateRequest, api_key: str = Depends(require_api_key)):
    pool = get_pool()
    _get_owned_session(pool, session_id, api_key)
    try:
        return await pool.navigate(session_id, req)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


@app.post("/sessions/{session_id}/back")
async def go_back(session_id: str, wait_until: str = "domcontentloaded", timeout: int = 10000, api_key: str = Depends(require_api_key)):
    pool = get_pool()
    _get_owned_session(pool, session_id, api_key)
    try:
        return await pool.go_back(session_id, wait_until=wait_until, timeout=timeout)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


@app.get("/sessions/{session_id}/url")
async def get_url(session_id: str, api_key: str = Depends(require_api_key)):
    pool = get_pool()
    _get_owned_session(pool, session_id, api_key)
    try:
        url = await pool.get_url(session_id)
        return {"url": url}
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


@app.get("/sessions/{session_id}/title")
async def get_title(session_id: str, api_key: str = Depends(require_api_key)):
    pool = get_pool()
    _get_owned_session(pool, session_id, api_key)
    try:
        title = await pool.get_title(session_id)
        return {"title": title}
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


# ── Interaction ──────────────────────────────────────────────────────


@app.post("/sessions/{session_id}/snapshot")
async def snapshot(session_id: str, interactive_only: bool = False, api_key: str = Depends(require_api_key)):
    pool = get_pool()
    _get_owned_session(pool, session_id, api_key)
    try:
        result = await pool.snapshot(session_id, interactive_only=interactive_only)
        return result.model_dump() if isinstance(result, SnapshotResponse) else result
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


@app.post("/sessions/{session_id}/click")
async def click(session_id: str, req: ClickRequest, api_key: str = Depends(require_api_key)):
    pool = get_pool()
    _get_owned_session(pool, session_id, api_key)
    try:
        return await pool.click(session_id, req)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


@app.post("/sessions/{session_id}/fill")
async def fill(session_id: str, req: FillRequest, api_key: str = Depends(require_api_key)):
    pool = get_pool()
    _get_owned_session(pool, session_id, api_key)
    try:
        return await pool.fill(session_id, req)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


@app.post("/sessions/{session_id}/scroll")
async def scroll(session_id: str, req: ScrollRequest, api_key: str = Depends(require_api_key)):
    pool = get_pool()
    _get_owned_session(pool, session_id, api_key)
    try:
        return await pool.scroll(session_id, req)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


@app.post("/sessions/{session_id}/evaluate")
async def evaluate(session_id: str, req: EvaluateRequest, api_key: str = Depends(require_api_key)):
    pool = get_pool()
    _get_owned_session(pool, session_id, api_key)
    try:
        result = await pool.evaluate(session_id, req)
        if isinstance(result, dict):
            return result
        return {"result": result}
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


@app.post("/sessions/{session_id}/wait")
async def wait_for_selector(session_id: str, req: WaitRequest, api_key: str = Depends(require_api_key)):
    pool = get_pool()
    _get_owned_session(pool, session_id, api_key)
    try:
        return await pool.wait_for_selector(session_id, req)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


@app.post("/sessions/{session_id}/mouse/move")
async def mouse_move(session_id: str, req: MouseMoveRequest, api_key: str = Depends(require_api_key)):
    pool = get_pool()
    _get_owned_session(pool, session_id, api_key)
    try:
        return await pool.mouse_move(session_id, x=req.x, y=req.y)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


@app.post("/sessions/{session_id}/keyboard/press")
async def keyboard_press(session_id: str, req: KeyPressRequest, api_key: str = Depends(require_api_key)):
    pool = get_pool()
    _get_owned_session(pool, session_id, api_key)
    try:
        return await pool.keyboard_press(session_id, key=req.key)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


# ── VNC Proxy ─────────────────────────────────────────────────────────


def _get_vnc_target(vnc_token: str) -> str:
    """Resolve noVNC proxy target from VNC token.

    Dynamic k8s mode: look up session by token → get pod_name → headless DNS.
    All-in-one / local mode: localhost:6080.
    """
    pool = get_pool()
    browser_mode = os.environ.get("BROWSER_MODE", "local")

    if browser_mode == "k8s":
        from agent_browser.models import K8sBrowserInstance

        br_svc = os.environ.get(
            "BROWSER_HEADLESS_SVC",
            "agent-browser-br-headless.agent-browser.svc.cluster.local",
        )
        # Find session by VNC token and extract pod_name
        for session in pool.sessions.values():
            if session and session.vnc_token == vnc_token:
                instance = session.browser_instance
                if isinstance(instance, K8sBrowserInstance) and instance.pod_name:
                    ns = os.environ.get("BR_NAMESPACE", "agent-browser")
                    return f"http://{instance.pod_name}.agent-browser-br-headless.{ns}.svc.cluster.local:6080"
        # Token not found or no pod_name — fallback (shouldn't happen in normal operation)
        logger.warning(f"VNC token {vnc_token[:8]}... not matched to any k8s session")
        return "http://localhost:6080"

    # All-in-one mode: VNC is on this pod
    return "http://localhost:6080"


@app.get("/vnc/{vnc_token}/{path:path}")
async def vnc_proxy_http(vnc_token: str, path: str, request: Request):
    """Proxy noVNC static assets with token validation."""
    if len(vnc_token) != 32:
        raise HTTPException(status_code=403, detail="Invalid VNC token")
    target = _get_vnc_target(vnc_token)
    target_url = f"{target}/{path}"
    async with aiohttp.ClientSession() as client:
        async with client.get(target_url, params=dict(request.query_params)) as resp:
            content = await resp.read()
            return Response(content=content, media_type=resp.content_type)


@app.websocket("/vnc/{vnc_token}/websockify")
async def vnc_proxy_ws(websocket: WebSocket, vnc_token: str):
    """Bidirectional WebSocket proxy for noVNC websockify with token validation."""
    if len(vnc_token) != 32:
        await websocket.close(code=4403)
        return
    await websocket.accept()
    target = _get_vnc_target(vnc_token)
    ws_url = target.replace("http://", "ws://") + "/websockify"
    try:
        async with aiohttp.ClientSession() as client:
            async with client.ws_connect(ws_url) as ws_backend:

                async def forward_to_backend():
                    try:
                        async for msg in websocket.iter_bytes():
                            await ws_backend.send_bytes(msg)
                    except Exception:
                        pass

                async def forward_to_client():
                    try:
                        async for msg in ws_backend:
                            if msg.type == aiohttp.WSMsgType.BINARY:
                                await websocket.send_bytes(msg.data)
                            elif msg.type == aiohttp.WSMsgType.TEXT:
                                await websocket.send_text(msg.data)
                            elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                                break
                    except Exception:
                        pass

                await asyncio.gather(forward_to_backend(), forward_to_client())
    except Exception as e:
        logger.warning(f"VNC WebSocket proxy error for token {vnc_token[:8]}...: {e}")
    finally:
        with contextlib.suppress(Exception):
            await websocket.close()


# ── Agent Tasks ───────────────────────────────────────────────────────


@app.post("/sessions/{session_id}/task")
async def submit_task(session_id: str, req: TaskSubmitRequest, api_key: str = Depends(require_api_key)):
    pool = get_pool()
    _get_owned_session(pool, session_id, api_key)
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
async def get_task_status(session_id: str, task_id: str, api_key: str = Depends(require_api_key)):
    pool = get_pool()
    _get_owned_session(pool, session_id, api_key)
    try:
        status = await pool.get_task_status(session_id, task_id)
        return {"task_id": task_id, **status}
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session/task {session_id}/{task_id} not found")


# ── Legacy compat endpoints ───────────────────────────────────────────


@app.post("/tasks")
async def legacy_create_task(req: TaskSubmitRequest, api_key: str = Depends(require_api_key)):
    """Legacy endpoint: creates an implicit session, submits task."""
    pool = get_pool()
    try:
        session_id = await pool.create_session(user_id="legacy_api", owner_key=api_key)
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
async def legacy_get_task_status(task_id: str, api_key: str = Depends(require_api_key)):
    """Legacy endpoint: find task by ID across sessions owned by this key."""
    pool = get_pool()
    for sid, session in pool.sessions.items():
        if not session or session.owner_key != api_key:
            continue
        if task_id in session.tasks:
            info = session.tasks[task_id]
            return {
                "task_id": task_id,
                "session_id": sid,
                **info,
            }
    raise HTTPException(status_code=404, detail=f"Task {task_id} not found in any session")
