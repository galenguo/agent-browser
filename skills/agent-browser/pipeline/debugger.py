"""Pipeline Debugger — 单步执行 + 状态检查

提供交互式调试能力：
  - 断点：在指定步骤后暂停
  - 历史：每步的输入输出记录
  - 状态检查：查看当前 data、context、页面信息

用法：
    from pipeline.debugger import debug_pipeline
    session = DebugSession(steps, session_id, args, breakpoints=[2, 5])
    result = await session.run()
    # 在 step 2 和 step 5 之后暂停
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

from .executor import PipelineStep, PipelineResult
from .template import TemplateContext

logger = logging.getLogger(__name__)


class StepRecord:
    """单步执行记录"""

    def __init__(
        self,
        step_index: int,
        op: str,
        params: Any,
        output_type: str = "unknown",
        output_size: Optional[int] = None,
        duration_ms: int = 0,
        error: Optional[Dict] = None,
    ):
        self.step_index = step_index
        self.op = op
        self.params = params
        self.output_type = output_type
        self.output_size = output_size
        self.duration_ms = duration_ms
        self.error = error

    def to_dict(self) -> dict:
        d = {
            "step_index": self.step_index,
            "op": self.op,
            "output_type": self.output_type,
            "duration_ms": self.duration_ms,
        }
        if self.output_size is not None:
            d["output_size"] = self.output_size
        if self.params is not None:
            d["params_summary"] = _summarize(self.params)
        if self.error:
            d["error"] = self.error
        return d


class DebugSession:
    """Pipeline 调试会话"""

    def __init__(
        self,
        steps: List[Dict[str, Any]],
        session_id: str,
        args: Dict[str, Any],
        breakpoints: Optional[List[int]] = None,
        stealth_config: Optional[Dict] = None,
    ):
        self.steps = [PipelineStep(s) for s in steps]
        self.session_id = session_id
        self.args = args
        self.breakpoints = set(breakpoints or [])
        self.stealth = stealth_config or {}

        self.current_step = 0
        self.data: Any = None
        self.history: List[StepRecord] = []
        self.context: Dict[str, Any] = {"args": args, "data": None}
        self.tmpl_ctx = TemplateContext(args=args)

        self._start_time: float = 0
        self._completed = False

    @property
    def total_steps(self) -> int:
        return len(self.steps)

    async def run_to_breakpoint(self) -> Dict[str, Any]:
        """
        执行到下一个 breakpoint 或结束。

        Returns:
            状态字典:
              status: "breakpoint" | "completed" | "error"
              step: 当前步骤索引 (+1 表示刚完成该步)
              data: 当前数据
              history: 最近 N 步记录
              breakpoint_hit: 命中的断点编号（仅 breakpoint 状态）
        """
        from .steps import STEPS

        while self.current_step < len(self.steps):
            step = self.steps[self.current_step]

            if step.op not in STEPS:
                record = StepRecord(
                    step_index=self.current_step,
                    op=step.op,
                    params=step.params,
                    error={"error": f"Unknown step: {step.op}"},
                )
                self.history.append(record)
                self.current_step += 1
                continue

            handler = STEPS[step.op]

            # 渲染模板参数
            from .template import render_value
            rendered_params = render_value(step.params, self.tmpl_ctx)

            # 执行步骤
            start = asyncio.get_event_loop().time()
            try:
                self.data = await handler(
                    session_id=self.session_id,
                    params=rendered_params,
                    data=self.data,
                    context=self.context,
                    stealth=self.stealth,
                )
                elapsed = int((asyncio.get_event_loop().time() - start) * 1000)

                record = StepRecord(
                    step_index=self.current_step,
                    op=step.op,
                    params=rendered_params,
                    output_type=type(self.data).__name__,
                    output_size=len(self.data) if isinstance(self.data, list) else None,
                    duration_ms=elapsed,
                )
                self.history.append(record)

                # 更新上下文
                self.context["data"] = self.data
                self.context["step_index"] = self.current_step
                self.tmpl_ctx._data = self.data

            except Exception as e:
                elapsed = int((asyncio.get_event_loop().time() - start) * 1000)
                record = StepRecord(
                    step_index=self.current_step,
                    op=step.op,
                    params=rendered_params,
                    duration_ms=elapsed,
                    error={
                        "type": type(e).__name__,
                        "message": str(e),
                    },
                )
                self.history.append(record)

            self.current_step += 1

            # 检查是否命中断点
            if self.current_step in self.breakpoints:
                return {
                    "status": "breakpoint",
                    "step": self.current_step,
                    "data": self.data,
                    "history": [r.to_dict() for r in self.history[-5:]],
                    "breakpoint_hit": self.current_step,
                    "total_steps": self.total_steps,
                }

        # 全部完成
        self._completed = True
        return {
            "status": "completed",
            "step": self.current_step,
            "data": self.data,
            "history": [r.to_dict() for r in self.history],
            "total_steps": self.total_steps,
        }

    async def run_all(self) -> Dict[str, Any]:
        """无断点地执行全部步骤（等同于 execute_pipeline 但带历史）"""
        self.breakpoints.clear()  # 清除断点 = 无暂停
        return await self.run_to_breakpoint()

    def get_state(self) -> Dict[str, Any]:
        """获取当前调试状态快照"""
        return {
            "session_id": self.session_id,
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "completed": self._completed,
            "data_type": type(self.data).__name__ if self.data is not None else "None",
            "data_preview": _summarize(self.data),
            "history_count": len(self.history),
            "breakpoints": sorted(self.breakpoints),
        }


def _summarize(value: Any, max_len: int = 200) -> str:
    """将任意值压缩为可读摘要"""
    if value is None:
        return "None"
    if isinstance(value, (list, tuple)):
        if len(value) == 0:
            return "[] (empty)"
        preview = str(value[:3]) + ("..." if len(value) > 3 else "")
        return f"[{len(value)} items] {preview}"
    if isinstance(value, dict):
        keys = list(value.keys())[:5]
        more = f" +{len(value)-5} more" if len(value) > 5 else ""
        return f"{{dict {len(value)} keys: {keys}{more}}}"
    s = str(value)
    return s[:max_len] + ("..." if len(s) > max_len else "")


async def debug_pipeline(
    steps: List[Dict[str, Any]],
    session_id: str,
    args: Dict[str, Any],
    breakpoints: Optional[List[int]] = None,
    stealth_config: Optional[Dict] = None,
) -> Any:
    """
    调试模式执行 pipeline。

    与 execute_pipeline 相同的接口，但支持断点和历史记录。

    Returns:
        最终数据（与 execute_pipeline 兼容），或断点状态字典
    """
    session = DebugSession(steps, session_id, args, breakpoints, stealth_config)
    result = await session.run_to_breakpoint()

    if result["status"] == "completed":
        return result["data"]

    # 断点模式返回完整状态
    return result
