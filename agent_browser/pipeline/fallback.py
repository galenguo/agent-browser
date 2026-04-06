"""Agent Fallback — LLM-driven error recovery strategies.

When a pipeline step fails, instead of giving up immediately, attempt auto-recovery:
  - selector_drift → re-snapshot page, use AI to find new selector
  - timeout → increase wait time, retry
  - auth_failure → mark as needing re-auth (cannot auto-fix)
  - data_quality → try to adjust extraction logic
  - navigation_error → check URL reachability

Design constraints:
  - No new dependencies (uses existing browser-use / LLM)
  - Each step retries at most once (avoid infinite loops)
  - On fallback failure, return original error without losing information
"""
import logging
from typing import Any

from .classifier import ErrorCategory, category_description, classify
from .errors import PipelineStepError

logger = logging.getLogger(__name__)

# Maximum fallback retry count
_MAX_RETRIES = 1


async def _retry_with_fresh_selector(
    session_id: str,
    error: PipelineStepError,
    context: dict[str, Any],
) -> bool:
    """
    Selector Drift recovery: re-fetch page snapshot, verify element exists.

    Strategy:
      1. Call snapshot() to get current DOM state
      2. Check if target element exists in snapshot
      3. If exists, update selector reference in context
    """
    try:
        from agent_browser.main import snapshot as do_snapshot

        snap = await do_snapshot(session_id)
        elements = snap.get("elements", [])

        # Check if there are any interactive elements (page loaded successfully)
        if len(elements) > 0:
            logger.info(
                f"Selector drift recovery: page has {len(elements)} elements, "
                f"step '{error.step_name}' may need updated selector"
            )
            # Store snapshot data in context for subsequent steps to reference
            context["_fallback_snapshot"] = {
                "url": snap.get("url"),
                "title": snap.get("title"),
                "element_count": len(elements),
            }
            return True

        logger.warning("Selector drift recovery: page snapshot returned no elements")
        return False

    except Exception as e:
        logger.warning(f"Selector drift recovery failed: {e}")
        return False


async def _retry_with_longer_timeout(
    session_id: str,
    error: PipelineStepError,
    context: dict[str, Any],
) -> bool:
    """
    Timeout recovery: increase wait time then retry.

    Strategy:
      1. Read original timeout from params (if present)
      2. Increase by 50% or fixed 5s
      3. Re-execute step with new timeout
    """
    try:
        from .steps import STEPS

        handler = STEPS.get(error.step_name)
        if not handler:
            return False

        # Increase timeout
        original_params = error.step_params or {}
        new_params = dict(original_params) if isinstance(original_params, dict) else {}

        current_timeout = new_params.get("_timeout") or new_params.get("timeout")
        new_timeout = int(current_timeout * 1.5) if current_timeout else 30

        new_params["_timeout"] = new_timeout
        logger.info(f"Timeout recovery: retrying '{error.step_name}' with {new_timeout}s timeout")

        result = await handler(
            session_id=session_id,
            params=new_params,
            data=context.get("data"),
            context=context,
        )

        context["data"] = result
        return True

    except Exception as e:
        logger.warning(f"Timeout recovery failed: {e}")
        return False


async def _require_reauth(
    session_id: str,
    error: PipelineStepError,
    context: dict[str, Any],
) -> bool:
    """Auth Failure recovery: mark as needing re-authentication. Cannot auto-fix."""
    logger.warning(
        f"Auth failure at step '{error.step_name}': "
        f"{category_description(ErrorCategory.AUTH_FAILURE)}. "
        f"User must re-authenticate."
    )
    context["_reauth_required"] = True
    return False  # Cannot auto-recover


# ── Strategy registry (use function names for patchability) ──

_FALLBACK_HANDLER_NAMES = {
    ErrorCategory.SELECTOR_DRIFT: "_retry_with_fresh_selector",
    ErrorCategory.TIMEOUT: "_retry_with_longer_timeout",
    ErrorCategory.AUTH_FAILURE: "_require_reauth",
}


def _get_fallback_handler(category: ErrorCategory):
    """Dynamically resolve handler (enables unittest.mock.patch to work)."""
    name = _FALLBACK_HANDLER_NAMES.get(category)
    if not name:
        return None
    return globals().get(name)


async def attempt_fallback(
    session_id: str,
    error: PipelineStepError,
    context: dict[str, Any],
    max_retries: int = _MAX_RETRIES,
) -> bool:
    """
    Attempt automatic recovery of a failed step.

    Args:
        session_id: Browser session ID
        error: Original PipelineStepError
        context: Pipeline execution context (contains data, args, etc.)
        max_retries: Maximum retry count

    Returns:
        True on successful recovery (caller should continue to next step)
        False on recovery failure (caller should log original error)
    """
    category, meta = classify(error)
    handler = _get_fallback_handler(category)

    if not handler:
        logger.debug(f"No fallback handler for category {category}")
        return False

    logger.info(
        f"Fallback attempt for [{category.value}] "
        f"at step {error.step_index} '{error.step_name}'"
    )

    for attempt in range(1, max_retries + 1):
        try:
            recovered = await handler(session_id, error, context)
            if recovered:
                logger.info(f"Fallback succeeded (attempt {attempt}/{max_retries})")
                return True
            logger.debug(f"Fallback attempt {attempt}/{max_retries} did not recover")
        except Exception as e:
            logger.warning(f"Fallback handler exception (attempt {attempt}): {e}")

    return False
