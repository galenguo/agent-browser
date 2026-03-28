"""
FastAPI 多用户会话 API (v2)

新架构特性：
- 多用户隔离：每个用户独立 Session
- Session 管理：创建、查询、删除会话
- 任务提交：提交任务到指定会话
- 向后兼容：保留旧版 /tasks API（自动创建临时 Session）
- 灵活部署：支持本地/Docker 浏览器模式

API 端点：
  Session 管理：
    - POST   /sessions/create          → 创建新会话
    - GET    /sessions/{session_id}    → 查询会话状态
    - DELETE /sessions/{session_id}    → 删除会话
    - GET    /sessions                 → 列出所有会话

  任务管理：
    - POST   /sessions/{session_id}/task → 提交任务到指定会话
    - GET    /sessions/{session_id}/tasks/{task_id} → 查询任务状态

  向后兼容（旧版 API）：
    - POST   /tasks                    → 自动创建临时 Session
    - GET    /tasks/{task_id}          → 查询任务状态
"""

import os
import logging
from contextlib import asynccontextmanager
from typing import Optional, Literal

from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel

from session.pool_manager import SessionPoolManager
from models import ResourceExhaustedError, SessionNotFoundError

# 配置日志
from browser_use.logging_config import setup_logging

_log_storage = os.getenv('LOG_STORAGE', '/data/logs')
setup_logging(
    debug_log_file=f'{_log_storage}/debug.log',
    info_log_file=f'{_log_storage}/info.log',
    log_level=os.getenv('LOG_LEVEL', 'info')
)

logger = logging.getLogger(__name__)

# 全局 SessionPoolManager
_session_manager: Optional[SessionPoolManager] = None

# 临时 Session 映射（用于向后兼容旧版 API）
_legacy_task_to_session: dict[str, str] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global _session_manager

    # 读取配置
    max_concurrent = int(os.getenv('MAX_SESSIONS', '10'))
    idle_timeout = int(os.getenv('IDLE_TIMEOUT_SECONDS', '1800'))
    browser_mode = os.getenv('BROWSER_MODE', 'local')  # local | docker

    logger.info("🚀 Agent Browser API v2 starting...")
    logger.info(f"   Max sessions: {max_concurrent}")
    logger.info(f"   Idle timeout: {idle_timeout}s")
    logger.info(f"   Browser mode: {browser_mode}")

    # 初始化 SessionPoolManager
    _session_manager = SessionPoolManager(
        max_concurrent=max_concurrent,
        idle_timeout=idle_timeout,
        browser_mode=browser_mode,
    )
    _session_manager.start()  # 启动后台监控任务

    yield

    # 关闭时清理
    logger.info("🛑 Shutting down...")
    if _session_manager:
        await _session_manager.shutdown()
    logger.info("✅ Agent Browser API v2 stopped")


app = FastAPI(
    title="Agent Browser - Multi-User Sessions",
    description="多用户隔离的浏览器自动化服务（支持本地/Docker 部署）",
    version="2.0.0",
    lifespan=lifespan,
)


# ─────────────── 数据模型 ───────────────

class BrowserNodeInfo(BaseModel):
    """浏览器节点公网访问信息（分布式部署时返回）"""
    instance_id: str
    public_host: Optional[str] = None
    public_cdp_port: Optional[int] = None   # 仅 Mode B（本地API→Docker）有
    public_novnc_port: Optional[int] = None
    novnc_url: Optional[str] = None         # noVNC 可视化监控地址


class CreateSessionRequest(BaseModel):
    user_id: str
    profile_config: Optional[dict] = None
    browser_type: str = "chromium"  # "chromium" only (camoufox removed)


class CreateSessionResponse(BaseModel):
    session_id: str
    user_id: str
    status: str = "created"
    browser_node: Optional[BrowserNodeInfo] = None


class SubmitTaskRequest(BaseModel):
    task: str
    model: str = "glm-5-turbo"
    max_steps: int = 50


class SubmitTaskResponse(BaseModel):
    task_id: str
    session_id: str
    status: str = "running"


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    result: Optional[str] = None
    error: Optional[str] = None
    browser_node: Optional[BrowserNodeInfo] = None
    current_step: int = 0
    last_step_at: Optional[float] = None


class SessionStatusResponse(BaseModel):
    session_id: str
    user_id: str
    created_at: float
    last_activity: float
    idle_time: float
    tasks: dict
    browser_node: Optional[BrowserNodeInfo] = None


# ─────────────── 健康检查 ───────────────

@app.get("/health")
async def health():
    """健康检查"""
    if not _session_manager:
        return {"status": "initializing"}

    return {
        "status": "ok",
        "sessions": len(_session_manager.sessions),
        "max_sessions": _session_manager.max_concurrent,
        "browser_mode": _session_manager.browser_pool.mode,
    }


# ─────────────── Session 管理 API ───────────────

@app.post("/sessions/create", response_model=CreateSessionResponse)
async def create_session(request: CreateSessionRequest):
    """创建新会话"""
    if not _session_manager:
        raise HTTPException(status_code=503, detail="Service not ready")

    try:
        session_id, browser_node = await _session_manager.create_session(
            user_id=request.user_id,
            profile_config=request.profile_config,
            browser_type=request.browser_type,
        )

        return CreateSessionResponse(
            session_id=session_id,
            user_id=request.user_id,
            browser_node=browser_node,
        )

    except ResourceExhaustedError as e:
        raise HTTPException(status_code=429, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/sessions/{session_id}", response_model=SessionStatusResponse)
async def get_session_status(session_id: str):
    """查询会话状态"""
    if not _session_manager:
        raise HTTPException(status_code=503, detail="Service not ready")

    try:
        status = await _session_manager.get_session_status(session_id)
        return SessionStatusResponse(
            session_id=status["session_id"],
            user_id=status["user_id"],
            created_at=status["created_at"],
            last_activity=status["last_activity"],
            idle_time=status["idle_time"],
            tasks=status["tasks"],
            browser_node=status.get("browser_node"),
        )

    except SessionNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除会话"""
    if not _session_manager:
        raise HTTPException(status_code=503, detail="Service not ready")

    try:
        await _session_manager.close_session(session_id)
        return {"status": "deleted", "session_id": session_id}

    except SessionNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/sessions")
async def list_sessions():
    """列出所有会话"""
    if not _session_manager:
        raise HTTPException(status_code=503, detail="Service not ready")

    sessions = []
    for session_id, session in _session_manager.sessions.items():
        sessions.append({
            "session_id": session_id,
            "user_id": session.user_id,
            "created_at": session.created_at,
            "last_activity": session.last_activity,
            "task_count": len(session.tasks),
        })

    return {"sessions": sessions, "total": len(sessions)}


# ─────────────── 任务管理 API ───────────────

@app.post("/sessions/{session_id}/task", response_model=SubmitTaskResponse)
async def submit_task(session_id: str, request: SubmitTaskRequest):
    """提交任务到指定会话"""
    if not _session_manager:
        raise HTTPException(status_code=503, detail="Service not ready")

    try:
        # 构建 LLM 配置
        llm_config = {
            "model": request.model,
        }

        task_id = await _session_manager.submit_task(
            session_id=session_id,
            task=request.task,
            llm_config=llm_config,
            max_steps=request.max_steps,
        )

        return SubmitTaskResponse(
            task_id=task_id,
            session_id=session_id,
        )

    except SessionNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to submit task: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/sessions/{session_id}/tasks/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(session_id: str, task_id: str):
    """查询任务状态"""
    if not _session_manager:
        raise HTTPException(status_code=503, detail="Service not ready")

    try:
        task_info = await _session_manager.get_task_status(session_id, task_id)

        return TaskStatusResponse(
            task_id=task_id,
            status=task_info.get("status", "unknown"),
            result=task_info.get("result"),
            error=task_info.get("error"),
            browser_node=task_info.get("browser_node"),
            current_step=task_info.get("current_step", 0),
            last_step_at=task_info.get("last_step_at"),
        )

    except SessionNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ─────────────── 向后兼容 API（旧版）───────────────

@app.post("/tasks", response_model=SubmitTaskResponse)
async def create_task_legacy(
    task: str,
    model: str = "glm-5-turbo",
    max_steps: int = 50,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    """
    旧版 API：自动创建临时 Session

    向后兼容：保留旧版 /tasks API
    - 自动为每个任务创建临时 Session
    - 使用 X-API-Key 作为 user_id（如果提供）
    """
    if not _session_manager:
        raise HTTPException(status_code=503, detail="Service not ready")

    # 使用 API Key 或生成临时 user_id
    user_id = x_api_key or f"legacy_user_{os.urandom(4).hex()}"

    try:
        # 创建临时 Session
        session_id, _browser_node = await _session_manager.create_session(user_id=user_id)

        # 提交任务
        llm_config = {"model": model}
        task_id = await _session_manager.submit_task(
            session_id=session_id,
            task=task,
            llm_config=llm_config,
            max_steps=max_steps,
        )

        # 记录映射（用于查询）
        _legacy_task_to_session[task_id] = session_id

        logger.info(f"Legacy API: created session {session_id} for task {task_id}")

        return SubmitTaskResponse(
            task_id=task_id,
            session_id=session_id,
        )

    except ResourceExhaustedError as e:
        raise HTTPException(status_code=429, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create legacy task: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/tasks/{task_id}", response_model=TaskStatusResponse)
async def get_task_legacy(task_id: str):
    """旧版 API：查询任务状态"""
    if not _session_manager:
        raise HTTPException(status_code=503, detail="Service not ready")

    # 查找对应的 Session
    session_id = _legacy_task_to_session.get(task_id)
    if not session_id:
        raise HTTPException(status_code=404, detail="Task not found")

    try:
        task_info = await _session_manager.get_task_status(session_id, task_id)

        return TaskStatusResponse(
            task_id=task_id,
            status=task_info.get("status", "unknown"),
            result=task_info.get("result"),
            error=task_info.get("error"),
            browser_node=task_info.get("browser_node"),
            current_step=task_info.get("current_step", 0),
            last_step_at=task_info.get("last_step_at"),
        )

    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Task not found")
