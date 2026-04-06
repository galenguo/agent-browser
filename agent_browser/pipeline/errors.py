"""Pipeline Exception Hierarchy — Typed errors with context.

Provides PipelineError base class and subclasses. Each error carries:
  - step_index: index of the failed step
  - step_name: operation name (click, evaluate, etc.)
  - adapter_name: "boss/search" format
  - session_id / page_url: execution context
  - fix_hint: human-readable fix suggestion
"""
import logging

logger = logging.getLogger(__name__)


class PipelineError(Exception):
    """Base class for pipeline execution errors."""

    def __init__(
        self,
        message: str,
        step_index: int = -1,
        step_name: str = "",
        step_params=None,
        adapter_name: str = "",
        session_id: str = "",
        page_url: str = "",
        cause: Exception = None,
        fix_hint: str = "",
    ):
        self.message = message
        self.step_index = step_index
        self.step_name = step_name
        self.step_params = step_params
        self.adapter_name = adapter_name
        self.session_id = session_id
        self.page_url = page_url
        self.cause = cause
        self.fix_hint = fix_hint
        super().__init__(message)

    def to_dict(self) -> dict:
        """Structured output, suitable for logs and API responses."""
        return {
            "error": "pipeline_error",
            "message": str(self),
            "step": self.step_index,
            "step_name": self.step_name,
            "adapter": self.adapter_name,
            "session_id": self.session_id,
            "url": self.page_url,
            "fix_hint": self.fix_hint,
        }

    @property
    def user_message(self) -> str:
        """User-friendly message."""
        parts = [f"Adapter '{self.adapter_name}' failed"]
        if self.step_index >= 0:
            parts.append(f"at step {self.step_index} '{self.step_name}'")
        parts.append(f": {self.message}")
        if self.fix_hint:
            parts.append(f"\nFix: {self.fix_hint}")
        return "".join(parts)


class AdapterLoadError(PipelineError):
    """YAML parse/load failure."""


class AdapterValidationError(PipelineError):
    """YAML structure validation failure."""


class PipelineStepError(PipelineError):
    """Step execution failure."""


class StepTimeoutError(PipelineStepError):
    """Step timeout."""


class SelectorNotFoundError(PipelineStepError):
    """Selector did not find element."""


class URLError(PipelineError):
    """URL invalid or blocked."""


# ── Fix Hint rule table ──

_HINTS = {
    "select":     "Site DOM may have changed. Re-run explore to update selectors.",
    "click":      "Element not found. Try snapshot(session_id) to inspect current DOM.",
    "type":       "Input element missing or not interactable. Check selector and page state.",
    "wait":       "Page loaded slowly. Increase timeout or check network connectivity.",
    "evaluate":  "JS extraction failed. Site may use newer framework. Check console for errors.",
    "fetch":      "API endpoint may be down or require auth. Check cookies and headers.",
    "navigate":   "URL may be invalid or blocked by security policy. Verify site accessibility.",
    "tap":        "Vue/Pinia store not detected. Strategy may need update to 'intercept'.",
    "limit":      "Result count issue. Check if data exists before limiting.",
    "map":        "Data transformation error. Check item field names against actual data shape.",
    "filter":     "Filter condition matched no items. Relax filter criteria.",
    "sort":       "Sort key not found in data. Check field names.",
    "scroll":     "Scroll operation failed. Page may not have scrollable content.",
}


def _generate_fix_hint(step_name: str, error_msg: str) -> str:
    """Generate a fix suggestion based on step type."""
    hint = _HINTS.get(step_name)
    if hint:
        return hint
    # Generic fallback
    if "timeout" in error_msg.lower():
        return "Operation timed out. Increase timeout or check if page is hanging."
    if "not found" in error_msg.lower():
        return "Target element or resource not found. Inspect page state with snapshot()."
    return "Check logs for details and verify page state."
