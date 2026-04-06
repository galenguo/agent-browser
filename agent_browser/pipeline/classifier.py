"""Pipeline Error Classifier — Maps PipelineError to actionable strategies.

Classification dimensions:
  - SELECTOR_DRIFT: Selector expired, DOM structure changed
  - TIMEOUT: Page load slow, network timeout
  - AUTH_FAILURE: Cookie/session expired, 401/403
  - DATA_QUALITY: Returned data format changed or empty
  - NAVIGATION_ERROR: URL invalid, blocked, DNS failure
  - UNKNOWN: Cannot auto-classify
"""

from enum import Enum
from typing import Any

from .errors import (
    PipelineError,
    PipelineStepError,
    SelectorNotFoundError,
    StepTimeoutError,
    URLError,
)


class ErrorCategory(Enum):
    """Error category — determines fallback strategy."""

    SELECTOR_DRIFT = "selector_drift"
    TIMEOUT = "timeout"
    AUTH_FAILURE = "auth_failure"
    DATA_QUALITY = "data_quality"
    NAVIGATION_ERROR = "navigation_error"
    UNKNOWN = "unknown"


# ── Classification rules ──

_STATUS_CODE_RE = r"\b(\d{3})\b"
TIMEOUT_KEYWORDS = (
    "timeout",
    "timed out",
)
AUTH_KEYWORDS = ("401", "403", "unauthorized", "forbidden", "cookie", "session", "auth")
SELECTOR_KEYWORDS = ("selector", "not found", "element", "ref@", "locator", "visible")
NAVIGATION_KEYWORDS = (
    "url",
    "navigate",
    "dns",
    "connection refused",
    "connection reset",
    "ssl",
    "certificate",
    "blocked",
)


def _extract_status_code(message: str) -> int | None:
    """Extract HTTP status code from error message."""
    import re

    match = re.search(_STATUS_CODE_RE, message)
    if match:
        return int(match.group(1))
    return None


def classify(error: PipelineError) -> tuple[ErrorCategory, dict[str, Any]]:
    """
    Classify a PipelineError into an ErrorCategory + metadata.

    Returns:
        (category, metadata) tuple
        metadata contains context info needed by strategy execution.
    """
    msg_lower = str(error).lower()
    meta: dict[str, Any] = {
        "step_name": error.step_name,
        "step_index": error.step_index,
        "adapter_name": error.adapter_name,
        "raw_message": str(error),
    }

    # 1. Fast match by exception type (most precise)
    if isinstance(error, SelectorNotFoundError):
        return ErrorCategory.SELECTOR_DRIFT, {**meta, "hint": "element_not_found"}

    if isinstance(error, StepTimeoutError):
        return ErrorCategory.TIMEOUT, {**meta, "duration_hint": "increase_timeout"}

    if isinstance(error, URLError):
        status = _extract_status_code(msg_lower)
        nav_meta = {**meta}
        if status:
            nav_meta["status_code"] = status
            if status in (401, 403):
                return ErrorCategory.AUTH_FAILURE, nav_meta
        return ErrorCategory.NAVIGATION_ERROR, nav_meta

    # 2. Heuristic classification by PipelineStepError message content
    if isinstance(error, PipelineStepError):
        # Auth detection
        if any(kw in msg_lower for kw in AUTH_KEYWORDS):
            status = _extract_status_code(msg_lower)
            auth_meta = {**meta}
            if status:
                auth_meta["status_code"] = status
            return ErrorCategory.AUTH_FAILURE, auth_meta

        # Timeout detection (not caught by StepTimeoutError)
        if any(kw in msg_lower for kw in TIMEOUT_KEYWORDS):
            return ErrorCategory.TIMEOUT, {**meta, "hint": "operation_timeout"}

        # Selector/element detection
        if any(kw in msg_lower for kw in SELECTOR_KEYWORDS):
            return ErrorCategory.SELECTOR_DRIFT, {**meta, "hint": "element_issue"}

        # Navigation/URL detection
        if any(kw in msg_lower for kw in NAVIGATION_KEYWORDS):
            return ErrorCategory.NAVIGATION_ERROR, {**meta, "hint": "url_or_connection"}

        # Data quality: empty results, parse failures
        if any(kw in msg_lower for kw in ("empty", "no data", "parse", "json", "index", "keyerror")):
            return ErrorCategory.DATA_QUALITY, {**meta, "hint": "data_format"}

    # 3. Fallback
    return ErrorCategory.UNKNOWN, meta


def category_description(category: ErrorCategory) -> str:
    """Return user-facing classification description."""
    descriptions = {
        ErrorCategory.SELECTOR_DRIFT: "Page structure has changed, selectors need updating",
        ErrorCategory.TIMEOUT: "Operation timed out, may need to increase wait time",
        ErrorCategory.AUTH_FAILURE: "Authentication expired, need to re-login or update credentials",
        ErrorCategory.DATA_QUALITY: "Data format does not match expectations, may need to adjust extraction logic",
        ErrorCategory.NAVIGATION_ERROR: "Navigation failed, URL may be invalid or blocked",
        ErrorCategory.UNKNOWN: "Unknown error type, please check logs",
    }
    return descriptions.get(category, "Unknown error")
