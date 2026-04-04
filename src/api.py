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

import hashlib
import hmac
import os
import re
import logging
from contextlib import asynccontextmanager
from typing import Optional, Literal

from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel

from session.pool_manager import SessionPoolManager
from models import (
    ResourceExhaustedError, SessionNotFoundError,
    # 原子操作请求模型
    NavigateRequest, ClickRequest, FillRequest, EvaluateRequest, ScrollRequest, WaitRequest,
    # 原子操作响应模型
    ElementInfo, SnapshotResponse,
)

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

# API Key 认证配置
_api_key = os.getenv('AGENT_BROWSER_API_KEY') or os.getenv('API_KEY')


def _validate_url(url: str) -> str:
    """验证 URL 安全性（防止 SSRF 和危险 scheme）"""
    url = url.strip()
    if not url:
        raise ValueError("Empty URL is not allowed")
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"URL must use http(s) scheme")
    lower = url.lower()
    for blocked in ("javascript:", "data:", "file:", "vbscript:", "blob:"):
        if lower.startswith(blocked):
            raise ValueError(f"Blocked URL scheme: {blocked}")
    # SSRF 防护：阻止私有/internal IP 段
    from urllib.parse import urlparse
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    blocked_prefixes = (
        "127.", "0.", "169.254.", "10.", "192.168.",
        "fc00:", "fe80:", "::1", "::ffff", "[::",
        "localhost", "metadata.google.internal",
    )
    for prefix in blocked_prefixes:
        if hostname == prefix or hostname.startswith(prefix):
            raise ValueError(f"SSRF blocked: {hostname}")
    return url


async def verify_api_key(x_api_key: Optional[str] = Header(None, alias="X-API-Key")):
    """验证 API Key（使用恒定时间比较防止时序攻击）"""
    if not _api_key:
        return None

    if not x_api_key:
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    # 恒定时间比较，防止时序攻击
    if not hmac.compare_digest(x_api_key, _api_key):
        raise HTTPException(
            status_code=401,
            detail="Authentication failed",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    return x_api_key


async def get_session_manager():
    """FastAPI 依赖：返回 SessionPoolManager 或 503"""
    if not _session_manager:
        raise HTTPException(status_code=503, detail="Service not ready")
    return _session_manager


async def verify_session_ownership(session_id: str, api_key: Optional[str] = None):
    """验证会话所有权（多租户安全）"""

    # 如果未配置 API Key，跳过所有权检查（单租户模式）
    if not _api_key:
        return

    session = _session_manager.sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    # 使用 API Key 作为 user_id 标识（简化实现）
    # 生产环境应维护 API Key → user_id 映射表
    if api_key and session.user_id != api_key:
        raise HTTPException(
            status_code=403,
            detail=f"Access denied: session {session_id} belongs to another user"
        )


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

    # 安全警告：未配置 API Key 时认证被完全跳过
    if not _api_key:
        logger.warning(
            "SECURITY: AGENT_BROWSER_API_KEY not set — authentication is DISABLED. "
            "All endpoints are publicly accessible. Set AGENT_BROWSER_API_KEY to enable auth."
        )

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
    browser_mode: Optional[str] = None  # "local" | "docker" — 覆盖服务端默认


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
async def create_session(request: CreateSessionRequest, api_key: str = Depends(verify_api_key)):
    """创建新会话"""
    if not _session_manager:
        raise HTTPException(status_code=503, detail="Service not ready")

    # 多租户安全：使用 API Key 作为 user_id（忽略请求中的 user_id）
    # 单租户模式（未配置 API Key）：使用请求中的 user_id
    effective_user_id = api_key if api_key else request.user_id

    try:
        if request.browser_mode and request.browser_mode != _session_manager.browser_pool.mode:
            logger.warning(
                f"Requested browser_mode={request.browser_mode!r} ignored; "
                f"server is running in {_session_manager.browser_pool.mode!r} mode"
            )
        session_id, browser_node = await _session_manager.create_session(
            user_id=effective_user_id,
            profile_config=request.profile_config,
            browser_type=request.browser_type,
        )

        return CreateSessionResponse(
            session_id=session_id,
            user_id=effective_user_id,
            browser_node=browser_node,
        )

    except ResourceExhaustedError as e:
        raise HTTPException(status_code=429, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create session: {e}")
        raise HTTPException(status_code=500, detail="Failed to create session")


@app.get("/sessions/{session_id}", response_model=SessionStatusResponse)
async def get_session_status(session_id: str, api_key: str = Depends(verify_api_key)):
    """查询会话状态"""
    if not _session_manager:
        raise HTTPException(status_code=503, detail="Service not ready")

    # 验证会话所有权
    await verify_session_ownership(session_id, api_key)

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

    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str, api_key: str = Depends(verify_api_key)):
    """删除会话"""
    if not _session_manager:
        raise HTTPException(status_code=503, detail="Service not ready")

    # 验证会话所有权
    await verify_session_ownership(session_id, api_key)

    try:
        await _session_manager.close_session(session_id)
        return {"status": "deleted", "session_id": session_id}

    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")


@app.get("/sessions")
async def list_sessions(api_key: str = Depends(verify_api_key)):
    """列出当前用户的会话（多租户隔离）"""
    if not _session_manager:
        raise HTTPException(status_code=503, detail="Service not ready")

    effective_user = api_key or "anonymous"
    sessions = []
    for session_id, session in _session_manager.sessions.items():
        # IDOR 防护：只返回当前用户自己的会话
        if _api_key and session.user_id != effective_user:
            continue
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
async def submit_task(session_id: str, request: SubmitTaskRequest, api_key: str = Depends(verify_api_key)):
    """提交任务到指定会话"""
    if not _session_manager:
        raise HTTPException(status_code=503, detail="Service not ready")

    # 验证会话所有权
    await verify_session_ownership(session_id, api_key)

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

    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except Exception as e:
        logger.error(f"Failed to submit task: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/sessions/{session_id}/tasks/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(session_id: str, task_id: str, api_key: str = Depends(verify_api_key)):
    """查询任务状态"""
    if not _session_manager:
        raise HTTPException(status_code=503, detail="Service not ready")

    # 验证会话所有权
    await verify_session_ownership(session_id, api_key)

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
        raise HTTPException(status_code=404, detail="Session not found")


# ─────────────── 原子操作 API ───────────────

class ClickRequestModel(BaseModel):
    """点击请求模型"""
    ref: str  # 元素引用，如 @e0, @e1
    button: str = "left"  # left | right | middle
    click_count: int = 1
    delay: Optional[int] = None  # 点击延迟 ms


class FillRequestModel(BaseModel):
    """填充请求模型"""
    ref: str  # 元素引用
    text: str
    clear_first: bool = True  # 是否先清空
    human_like: bool = False  # 是否模拟人类输入


class WaitRequestModel(BaseModel):
    """等待请求模型"""
    selector: Optional[str] = None  # CSS 选择器
    timeout: int = 10000  # ms
    state: str = "visible"  # visible | hidden | attached | detached


@app.post("/sessions/{session_id}/navigate")
async def navigate(session_id: str, request: NavigateRequest, api_key: str = Depends(verify_api_key)):
    """页面导航（URL 经过 SSRF 防护验证）"""
    if not _session_manager:
        raise HTTPException(status_code=503, detail="Service not ready")

    await verify_session_ownership(session_id, api_key)

    try:
        # URL 安全验证
        _validate_url(request.url)
        result = await _session_manager.navigate(session_id, request)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except Exception as e:
        logger.error(f"Failed to navigate: {e}")
        raise HTTPException(status_code=500, detail="Navigation failed")


@app.get("/sessions/{session_id}/snapshot", response_model=SnapshotResponse)
@app.post("/sessions/{session_id}/snapshot", response_model=SnapshotResponse)
async def get_snapshot(session_id: str, interactive_only: bool = True, api_key: str = Depends(verify_api_key)):
    """获取 DOM 快照（支持 GET 和 POST）"""
    if not _session_manager:
        raise HTTPException(status_code=503, detail="Service not ready")

    await verify_session_ownership(session_id, api_key)

    try:
        result = await _session_manager.snapshot(session_id, interactive_only)
        return result
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except Exception as e:
        logger.error(f"Failed to get snapshot: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/sessions/{session_id}/click")
async def click_element(session_id: str, request: ClickRequestModel, api_key: str = Depends(verify_api_key)):
    """点击元素"""
    if not _session_manager:
        raise HTTPException(status_code=503, detail="Service not ready")

    await verify_session_ownership(session_id, api_key)

    try:
        # 转换为 pool_manager 的 ClickRequest
        from models import ClickRequest
        click_req = ClickRequest(
            ref=request.ref,
            button=request.button,
            click_count=request.click_count,
            delay=request.delay
        )
        result = await _session_manager.click(session_id, click_req)
        return result
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except (IndexError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to click: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/sessions/{session_id}/fill")
async def fill_input(session_id: str, request: FillRequestModel, api_key: str = Depends(verify_api_key)):
    """填充输入框"""
    if not _session_manager:
        raise HTTPException(status_code=503, detail="Service not ready")

    await verify_session_ownership(session_id, api_key)

    try:
        # 转换为 pool_manager 的 FillRequest
        from models import FillRequest
        fill_req = FillRequest(
            ref=request.ref,
            text=request.text,
            clear_first=request.clear_first,
            human_like=request.human_like
        )
        result = await _session_manager.fill(session_id, fill_req)
        return result
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except (IndexError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to fill: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/sessions/{session_id}/evaluate")
async def evaluate_js(session_id: str, request: EvaluateRequest, api_key: str = Depends(verify_api_key)):
    """执行 JavaScript（受限模式：禁止写操作和危险 API）"""
    if not _session_manager:
        raise HTTPException(status_code=503, detail="Service not ready")

    await verify_session_ownership(session_id, api_key)

    # JS 安全检查：阻止危险操作
    js_code = getattr(request, 'expression', '') or getattr(request, 'code', '')
    _dangerous_js = (
        'fetch(', 'XMLHttpRequest', 'WebSocket', 'eval(', 'Function(',
        'document.write', 'document.cookie', 'localStorage',
        'sessionStorage', 'indexedDB', '.src=', 'location.assign',
        'location.replace', 'window.open', '<script',
        'import(', 'require(',
    )
    lowered = js_code.lower()
    for pat in _dangerous_js:
        if pat in lowered:
            logger.warning(f"Blocked dangerous JS in evaluate: {pat} found")
            raise HTTPException(
                status_code=400,
                detail="Evaluation contains blocked JavaScript API",
            )

    try:
        result = await _session_manager.evaluate(session_id, request)
        return result
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except Exception as e:
        logger.error(f"Failed to evaluate: {e}")
        raise HTTPException(status_code=500, detail="Evaluation failed")


@app.post("/sessions/{session_id}/scroll")
async def scroll_page(session_id: str, request: ScrollRequest, api_key: str = Depends(verify_api_key)):
    """滚动页面"""
    if not _session_manager:
        raise HTTPException(status_code=503, detail="Service not ready")

    await verify_session_ownership(session_id, api_key)

    try:
        result = await _session_manager.scroll(session_id, request)
        return result
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except Exception as e:
        logger.error(f"Failed to scroll: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/sessions/{session_id}/wait")
async def wait_for_selector(session_id: str, request: WaitRequestModel, api_key: str = Depends(verify_api_key)):
    """等待选择器"""
    if not _session_manager:
        raise HTTPException(status_code=503, detail="Service not ready")

    await verify_session_ownership(session_id, api_key)

    try:
        from models import WaitRequest
        wait_req = WaitRequest(
            selector=request.selector,
            timeout=request.timeout,
            state=request.state
        )
        result = await _session_manager.wait_for_selector(session_id, wait_req)
        return result
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except Exception as e:
        logger.error(f"Failed to wait: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/sessions/{session_id}/title")
async def get_title(session_id: str, api_key: str = Depends(verify_api_key)):
    """获取页面标题"""
    if not _session_manager:
        raise HTTPException(status_code=503, detail="Service not ready")

    await verify_session_ownership(session_id, api_key)

    try:
        title = await _session_manager.get_title(session_id)
        return {"title": title}
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except Exception as e:
        logger.error(f"Failed to get title: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/sessions/{session_id}/url")
async def get_url(session_id: str, api_key: str = Depends(verify_api_key)):
    """获取页面 URL"""
    if not _session_manager:
        raise HTTPException(status_code=503, detail="Service not ready")

    await verify_session_ownership(session_id, api_key)

    try:
        url = await _session_manager.get_url(session_id)
        return {"url": url}
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except Exception as e:
        logger.error(f"Failed to get url: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


class GoBackRequest(BaseModel):
    wait_until: str = "domcontentloaded"
    timeout: int = 10000


class MouseMoveRequest(BaseModel):
    x: float
    y: float


class KeyboardPressRequest(BaseModel):
    key: str


@app.post("/sessions/{session_id}/back")
async def go_back(session_id: str, request: GoBackRequest, api_key: str = Depends(verify_api_key)):
    """后退到上一页"""
    if not _session_manager:
        raise HTTPException(status_code=503, detail="Service not ready")

    await verify_session_ownership(session_id, api_key)

    try:
        result = await _session_manager.go_back(session_id, request.wait_until, request.timeout)
        return result
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except Exception as e:
        logger.error(f"Failed to go back: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/sessions/{session_id}/mouse/move")
async def mouse_move(session_id: str, request: MouseMoveRequest, api_key: str = Depends(verify_api_key)):
    """移动鼠标"""
    if not _session_manager:
        raise HTTPException(status_code=503, detail="Service not ready")

    await verify_session_ownership(session_id, api_key)

    try:
        result = await _session_manager.mouse_move(session_id, request.x, request.y)
        return result
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except Exception as e:
        logger.error(f"Failed to move mouse: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/sessions/{session_id}/keyboard/press")
async def keyboard_press(session_id: str, request: KeyboardPressRequest, api_key: str = Depends(verify_api_key)):
    """按键"""
    if not _session_manager:
        raise HTTPException(status_code=503, detail="Service not ready")

    await verify_session_ownership(session_id, api_key)

    try:
        result = await _session_manager.keyboard_press(session_id, request.key)
        return result
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except Exception as e:
        logger.error(f"Failed to press key: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ─────────────── 向后兼容 API（旧版）───────────────

@app.post("/tasks", response_model=SubmitTaskResponse)
async def create_task_legacy(
    task: str,
    model: str = "glm-5-turbo",
    max_steps: int = 50,
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    api_key: str = Depends(verify_api_key),
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
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/tasks/{task_id}", response_model=TaskStatusResponse)
async def get_task_legacy(task_id: str, api_key: str = Depends(verify_api_key)):
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
