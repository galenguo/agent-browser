"""智能模式路由 — LLM 模式 / Agent 模式"""
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
    统一任务入口。

    Args:
        session_id: 浏览器会话 ID
        task: 任务描述
        intelligence: "agent"（内置 LLM 自主执行）或 "llm"（外部驱动）
        llm_config: LLM 配置 {provider, model, api_key, base_url, temperature}
        max_steps: Agent 模式最大步数

    Returns:
        Agent 模式: {"status": "completed"/"failed", "result": ..., "steps": N}
        LLM 模式: {"status": "ready", "tools": [...], "session_id": ...}
    """
    if intelligence == "agent":
        from .agent_runner import run_agent_task
        return await run_agent_task(session_id, task, llm_config, max_steps, **kwargs)
    else:
        # LLM 模式：返回可用工具描述，由外部 LLM 驱动 ReAct 循环
        return {
            "status": "ready",
            "mode": "llm",
            "session_id": session_id,
            "tools": [
                {"name": "snapshot", "description": "获取页面快照", "params": []},
                {"name": "click", "description": "点击元素", "params": ["ref"]},
                {"name": "fill", "description": "填充输入", "params": ["ref", "text"]},
                {"name": "scroll", "description": "滚动页面", "params": ["direction", "amount"]},
                {"name": "go_back", "description": "后退", "params": []},
                {"name": "hover", "description": "悬停元素", "params": ["ref"]},
                {"name": "press_key", "description": "按键", "params": ["key"]},
            ],
        }
