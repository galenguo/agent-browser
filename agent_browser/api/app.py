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

import logging
import os
import tempfile

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from agent_browser.models import (
    ClickRequest,
    EvaluateRequest,
    FillRequest,
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
    """Get or lazily create the session pool."""
    global _pool
    if _pool is None:
        _pool = SessionPoolManager()
    return _pool


# ── Auth dependency ──────────────────────────────────────────────────


async def _get_api_key(x_api_key: str | None = Header(None)) -> str | None:
    """Extract X-API-Key header. Returns None if absent (open mode)."""
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
async def list_sessions():
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
async def create_session(req: CreateSessionRequest):
    pool = get_pool()
    try:
        session_id = await pool.create_session(user_id=req.user_id)
        # create_session returns tuple (session_id, node_info); we only need the ID
        sid = session_id[0] if isinstance(session_id, tuple) else session_id
        return {"session_id": sid, "user_id": req.user_id}
    except ResourceExhaustedError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Profile storage error: {e}")
    except Exception as e:
        logger.exception("create_session failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/sessions/{session_id}")
async def get_session(session_id: str):
    pool = get_pool()
    try:
        return await pool.get_session_status(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    pool = get_pool()
    try:
        await pool.close_session(session_id)
        return {}
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


# ── Navigation ────────────────────────────────────────────────────────


@app.post("/sessions/{session_id}/navigate")
async def navigate(session_id: str, req: NavigateRequest):
    pool = get_pool()
    try:
        return await pool.navigate(session_id, req)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


@app.post("/sessions/{session_id}/back")
async def go_back(session_id: str, wait_until: str = "domcontentloaded", timeout: int = 10000):
    pool = get_pool()
    try:
        return await pool.go_back(session_id, wait_until=wait_until, timeout=timeout)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


@app.get("/sessions/{session_id}/url")
async def get_url(session_id: str):
    pool = get_pool()
    try:
        url = await pool.get_url(session_id)
        return {"url": url}
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


@app.get("/sessions/{session_id}/title")
async def get_title(session_id: str):
    pool = get_pool()
    try:
        title = await pool.get_title(session_id)
        return {"title": title}
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


# ── Interaction ──────────────────────────────────────────────────────


@app.post("/sessions/{session_id}/snapshot")
async def snapshot(session_id: str, interactive_only: bool = False):
    pool = get_pool()
    try:
        result = await pool.snapshot(session_id, interactive_only=interactive_only)
        return result.model_dump() if isinstance(result, SnapshotResponse) else result
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


@app.post("/sessions/{session_id}/click")
async def click(session_id: str, req: ClickRequest):
    pool = get_pool()
    try:
        return await pool.click(session_id, req)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


@app.post("/sessions/{session_id}/fill")
async def fill(session_id: str, req: FillRequest):
    pool = get_pool()
    try:
        return await pool.fill(session_id, req)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


@app.post("/sessions/{session_id}/scroll")
async def scroll(session_id: str, req: ScrollRequest):
    pool = get_pool()
    try:
        return await pool.scroll(session_id, req)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


@app.post("/sessions/{session_id}/evaluate")
async def evaluate(session_id: str, req: EvaluateRequest):
    pool = get_pool()
    try:
        result = await pool.evaluate(session_id, req)
        # pool.evaluate() may return a dict (e.g. {"status": "ok", "result": ...}) or a raw value
        if isinstance(result, dict):
            return result
        return {"result": result}
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


@app.post("/sessions/{session_id}/wait")
async def wait_for_selector(session_id: str, req: WaitRequest):
    pool = get_pool()
    try:
        return await pool.wait_for_selector(session_id, req)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


@app.post("/sessions/{session_id}/mouse/move")
async def mouse_move(session_id: str, req: MouseMoveRequest):
    pool = get_pool()
    try:
        return await pool.mouse_move(session_id, x=req.x, y=req.y)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


@app.post("/sessions/{session_id}/keyboard/press")
async def keyboard_press(session_id: str, req: KeyPressRequest):
    pool = get_pool()
    try:
        return await pool.keyboard_press(session_id, key=req.key)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


# ── Agent Tasks ───────────────────────────────────────────────────────


@app.post("/sessions/{session_id}/task")
async def submit_task(session_id: str, req: TaskSubmitRequest):
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
async def get_task_status(session_id: str, task_id: str):
    pool = get_pool()
    try:
        status = await pool.get_task_status(session_id, task_id)
        return {"task_id": task_id, **status}
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session/task {session_id}/{task_id} not found")


# ── Legacy compat endpoints ───────────────────────────────────────────


@app.post("/tasks")
async def legacy_create_task(req: TaskSubmitRequest):
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
async def legacy_get_task_status(task_id: str):
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
