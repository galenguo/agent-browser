"""智能模式路由 — 委托给 backend.run_task()"""
from typing import Optional, Dict


async def run_task(
    session_id: str,
    task: str,
    intelligence: str = "agent",
    llm_config: Optional[Dict] = None,
    max_steps: int = 6,
    **kwargs,
) -> Dict:
    """
    统一任务入口。委托给当前 backend 的 run_task 实现。

    - LocalCDPBackend.run_task(): 本地 browser-use Agent（直连 CDP）
    - RemoteAPIBackend.run_task(): HTTP 轮询远程 FastAPI
    """
    from ..main import _backend
    if _backend is None:
        return {"status": "failed", "error": "Backend not initialized. Call create_session() first."}
    return await _backend.run_task(
        session_id, task, intelligence=intelligence, llm_config=llm_config, max_steps=max_steps, **kwargs
    )
