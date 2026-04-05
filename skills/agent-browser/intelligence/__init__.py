"""智能模式路由 — 委托给 StealthMiddleware.run_task()"""
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
    统一任务入口。通过 StealthMiddleware 委托给后端。

    自动获得 total_timeout 超时保护和隐匿包装。
    """
    from ..main import _ensure_middleware
    mw = await _ensure_middleware()
    return await mw.run_task(
        session_id, task,
        intelligence=intelligence,
        llm_config=llm_config,
        max_steps=max_steps,
        **kwargs,
    )
