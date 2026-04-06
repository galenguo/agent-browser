"""Intelligence mode routing — Delegates to StealthMiddleware.run_task()."""
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
    Unified task entry point. Delegates to StealthMiddleware backend.

    Automatically gets total_timeout protection and stealth wrapping.
    """
    from agent_browser.main import _ensure_middleware
    mw = await _ensure_middleware()
    return await mw.run_task(
        session_id, task,
        intelligence=intelligence,
        llm_config=llm_config,
        max_steps=max_steps,
        **kwargs,
    )
