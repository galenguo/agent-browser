"""Pipeline Debugger — Single-step execution + state inspection.

Provides interactive debugging capabilities:
  - Breakpoints: pause after specified steps
  - History: input/output record for each step
  - State inspection: view current data, context, page info

Usage:
    from pipeline.debugger import debug_pipeline
    session = DebugSession(steps, session_id, args, breakpoints=[2, 5])
    result = await session.run()
    # Pauses after step 2 and step 5
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

from .executor import PipelineStep, PipelineResult
from .template import TemplateContext

logger = logging.getLogger(__name__)


class StepRecord:
    """Single step execution record."""

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
    """Pipeline debug session."""

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
        Execute until next breakpoint or completion.

        Returns:
            Status dict:
              status: "breakpoint" | "completed" | "error"
              step: current step index (+1 means just completed this step)
              data: current data
              history: recent N step records
              breakpoint_hit: breakpoint number hit (only for breakpoint status)
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

            # Render template parameters
            from .template import render_value
            rendered_params = render_value(step.params, self.tmpl_ctx)

            # Execute step
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

                # Update context
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

            # Check if breakpoint was hit
            if self.current_step in self.breakpoints:
                return {
                    "status": "breakpoint",
                    "step": self.current_step,
                    "data": self.data,
                    "history": [r.to_dict() for r in self.history[-5:]],
                    "breakpoint_hit": self.current_step,
                    "total_steps": self.total_steps,
                }

        # All done
        self._completed = True
        return {
            "status": "completed",
            "step": self.current_step,
            "data": self.data,
            "history": [r.to_dict() for r in self.history],
            "total_steps": self.total_steps,
        }

    async def run_all(self) -> Dict[str, Any]:
        """Execute all steps without breakpoints (same as execute_pipeline but with history)."""
        self.breakpoints.clear()  # Clear breakpoints = no pauses
        return await self.run_to_breakpoint()

    def get_state(self) -> Dict[str, Any]:
        """Get current debug state snapshot."""
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
    """Compress any value into a readable summary."""
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
    Execute pipeline in debug mode.

    Same interface as execute_pipeline, but supports breakpoints and history.

    Returns:
        Final data (compatible with execute_pipeline), or breakpoint status dict.
    """
    session = DebugSession(steps, session_id, args, breakpoints, stealth_config)
    result = await session.run_to_breakpoint()

    if result["status"] == "completed":
        return result["data"]

    # Breakpoint mode returns full state
    return result
