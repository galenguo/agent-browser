"""Pipeline 执行器 — 顺序执行 step，thread data 传递"""
import logging
from typing import Any, Dict, List, Optional

from .steps import STEPS

logger = logging.getLogger(__name__)


class PipelineStep:
    """解析后的 pipeline step"""

    def __init__(self, raw: dict):
        # raw 格式: {op: params}，如 {"navigate": "https://..."}
        self.op: str = ""
        self.params: Any = None
        for key, value in raw.items():
            self.op = key
            self.params = value
            break

    def __repr__(self):
        return f"PipelineStep({self.op})"


async def execute_pipeline(
    steps: List[dict],
    session_id: str,
    args: dict,
    stealth_config: Optional[dict] = None,
) -> Any:
    """
    顺序执行 pipeline steps。

    Args:
        steps: YAML pipeline 列表，如 [{"navigate": "..."}, {"evaluate": "..."}]
        session_id: 浏览器会话 ID
        args: 适配器参数（来自用户输入）
        stealth_config: 隐匿性配置（来自适配器 YAML）

    Returns:
        最终 data（通常是 list[dict]）
    """
    data: Any = None
    context: Dict[str, Any] = {"args": args, "data": data}
    stealth = stealth_config or {}

    parsed_steps = [PipelineStep(s) for s in steps]

    for i, step in enumerate(parsed_steps):
        if step.op not in STEPS:
            logger.warning(f"Unknown step: {step.op}, skipping")
            continue

        handler = STEPS[step.op]
        logger.debug(f"Step {i}: {step.op}")

        data = await handler(
            session_id=session_id,
            params=step.params,
            data=data,
            context=context,
            stealth=stealth,
        )
        context["data"] = data
        context["step_index"] = i

    return data
