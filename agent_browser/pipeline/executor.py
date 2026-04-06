"""Pipeline Executor — Sequential step execution with data flow.

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
import logging
import time
from typing import Any

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
        self.errors: list[dict[str, Any]] = []
        self.duration_ms: int = 0
        self.success: bool = True


async def execute_pipeline(
    steps: list[dict],
    session_id: str,
    args: dict,
    stealth_config: dict | None = None,
    timeout_per_step: float | None = None,
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
    context: dict[str, Any] = {"args": args, "data": data}
    stealth = stealth_config or {}

    parsed_steps = [PipelineStep(s) for s in steps]
    result = PipelineResult()
    result.steps_total = len(parsed_steps)

    # Create template context (shared across all steps)
    tmpl_ctx = TemplateContext(args=args)

    for i, step in enumerate(parsed_steps):
        if step.op not in STEPS:
            logger.warning(f"Unknown step '{step.op}' at position {i}, skipping")
            result.errors.append(
                {
                    "step": i,
                    "op": step.op,
                    "error": f"Unknown step: {step.op}",
                }
            )
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

        except TimeoutError as e:
            from .errors import StepTimeoutError

            te = StepTimeoutError(
                message=f"Step '{step.op}' timed out after {step_timeout}s",
                step_index=i,
                step_name=step.op,
                session_id=session_id,
                cause=e,
                fix_hint="Increase timeout or check if page is hanging.",
            )
            logger.error(te.user_message)
            result.errors.append(te.to_dict())
            result.success = False

            # Fallback: attempt recovery when not fail_fast
            if not fail_fast:
                from .fallback import attempt_fallback

                recovered = await attempt_fallback(session_id, te, context)
                if recovered:
                    logger.info(f"Step '{step.op}' recovered after timeout")
                    result.steps_executed = i + 1
                    continue  # recovered, go to next step

            if fail_fast:
                break

        except Exception as e:
            from .errors import PipelineStepError, _generate_fix_hint

            pe = PipelineStepError(
                message=str(e),
                step_index=i,
                step_name=step.op,
                step_params=rendered_params,
                session_id=session_id,
                cause=e,
                fix_hint=_generate_fix_hint(step.op, str(e)),
            )
            logger.error(pe.user_message)
            result.errors.append(pe.to_dict())
            result.success = False

            # Fallback: attempt recovery when not fail_fast
            if not fail_fast:
                from .fallback import attempt_fallback

                recovered = await attempt_fallback(session_id, pe, context)
                if recovered:
                    logger.info(f"Step '{step.op}' recovered after error")
                    result.steps_executed = i + 1
                    continue  # recovered, go to next step

            if fail_fast:
                break

        # Update context for next step
        context["data"] = data
        context["step_index"] = i
        tmpl_ctx._data = data

    result.data = data
    result.duration_ms = int((time.time() - start_time) * 1000)

    # Telemetry: record execution (non-blocking, never fails pipeline)
    try:
        from .telemetry import Telemetry

        error_cat = None
        if not result.success and result.errors:
            # Use first error's category
            err_dict = result.errors[0]
            if "step_name" in err_dict:
                error_cat = err_dict.get("step_name", "")
        Telemetry.record(
            adapter=args.get("_adapter_name", "unknown"),
            success=result.success,
            duration_ms=result.duration_ms,
            steps_executed=result.steps_executed,
            steps_total=result.steps_total,
            error_category=error_cat,
            session_id=session_id,
        )
    except Exception:
        pass  # telemetry must never break pipeline

    if result.errors:
        logger.warning(f"Pipeline completed with {len(result.errors)} errors in {result.duration_ms}ms")
    else:
        logger.info(
            f"Pipeline completed successfully: "
            f"{result.steps_executed}/{result.steps_total} steps in {result.duration_ms}ms"
        )

    return data


def list_registered_steps() -> list[str]:
    """Return names of all registered pipeline steps."""
    return sorted(STEPS.keys())
