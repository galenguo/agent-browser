"""Pipeline 执行器 — 顺序执行 step，data 流传递

Execution model:
  result = None
  for step in pipeline:
      handler = registry.get(step_name)
      result = await handler(page, params, result, args)
      # result flows to next step

Features:
  - Step-level timeout (configurable per-step or global)
  - Error handling with continue_on_error / fail_fast modes
  - Template rendering for all string parameters
  - Progress logging with step index
"""
import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional

from .steps import STEPS
from .template import TemplateContext, render_value

logger = logging.getLogger(__name__)


class PipelineStep:
    """Parsed pipeline step: {op: params}"""

    def __init__(self, raw: dict):
        self.op: str = ""
        self.params: Any = None
        for key, value in raw.items():
            self.op = key
            self.params = value
            break

    def __repr__(self):
        return f"PipelineStep({self.op})"


class PipelineResult:
    """Pipeline execution result with metadata."""

    def __init__(self):
        self.data: Any = None
        self.steps_executed: int = 0
        self.steps_total: int = 0
        self.errors: List[Dict[str, Any]] = []
        self.duration_ms: int = 0
        self.success: bool = True


async def execute_pipeline(
    steps: List[dict],
    session_id: str,
    args: dict,
    stealth_config: Optional[dict] = None,
    timeout_per_step: Optional[float] = None,
    fail_fast: bool = True,
) -> Any:
    """
    Execute pipeline steps sequentially.

    Args:
        steps: YAML pipeline list, e.g., [{"navigate": "..."}, {"evaluate": "..."}]
        session_id: Browser session ID
        args: Adapter arguments (from user input)
        stealth_config: Stealth config (from adapter YAML)
        timeout_per_step: Per-step timeout in seconds (None = no limit)
        fail_fast: If True, stop on first error. If False, collect errors and continue.

    Returns:
        Final data (usually list[dict]), or PipelineResult if return_result=True.
    """
    start_time = time.time()
    data: Any = None
    context: Dict[str, Any] = {"args": args, "data": data}
    stealth = stealth_config or {}

    parsed_steps = [PipelineStep(s) for s in steps]
    result = PipelineResult()
    result.steps_total = len(parsed_steps)

    # Create template context (shared across all steps)
    tmpl_ctx = TemplateContext(args=args)

    for i, step in enumerate(parsed_steps):
        if step.op not in STEPS:
            logger.warning(f"Unknown step '{step.op}' at position {i}, skipping")
            result.errors.append({
                "step": i, "op": step.op,
                "error": f"Unknown step: {step.op}",
            })
            if fail_fast:
                result.success = False
                break
            continue

        handler = STEPS[step.op]
        logger.info(f"Pipeline step {i}/{len(parsed_steps)}: {step.op}")

        # Render templates in params before passing to handler
        rendered_params = render_value(step.params, tmpl_ctx)

        try:
            step_timeout = timeout_per_step
            # Allow per-step timeout override from params dict
            if isinstance(rendered_params, dict) and "_timeout" in rendered_params:
                step_timeout = rendered_params.pop("_timeout")

            if step_timeout and step_timeout > 0:
                data = await asyncio.wait_for(
                    handler(
                        session_id=session_id,
                        params=rendered_params,
                        data=data,
                        context=context,
                        stealth=stealth,
                    ),
                    timeout=step_timeout,
                )
            else:
                data = await handler(
                    session_id=session_id,
                    params=rendered_params,
                    data=data,
                    context=context,
                    stealth=stealth,
                )

            result.steps_executed = i + 1

        except asyncio.TimeoutError:
            error_msg = f"Step '{step.op}' timed out after {step_timeout}s"
            logger.error(f"Pipeline step {i} TIMEOUT: {error_msg}")
            result.errors.append({"step": i, "op": step.op, "error": error_msg})
            result.success = False
            if fail_fast:
                break

        except Exception as e:
            error_msg = f"Step '{step.op}' failed: {e}"
            logger.error(f"Pipeline step {i} ERROR: {error_msg}")
            result.errors.append({"step": i, "op": step.op, "error": str(e)})
            result.success = False
            if fail_fast:
                break

        # Update context for next step
        context["data"] = data
        context["step_index"] = i
        tmpl_ctx._data = data

    result.data = data
    result.duration_ms = int((time.time() - start_time) * 1000)

    if result.errors:
        logger.warning(
            f"Pipeline completed with {len(result.errors)} errors "
            f"in {result.duration_ms}ms"
        )
    else:
        logger.info(
            f"Pipeline completed successfully: "
            f"{result.steps_executed}/{result.steps_total} steps in {result.duration_ms}ms"
        )

    return data


def list_registered_steps() -> List[str]:
    """Return names of all registered pipeline steps."""
    return sorted(STEPS.keys())
