"""ActionTracer - Step tracer.

Records complete information for every atomic operation:
- Operation type and parameters
- Execution result and duration
- Timestamp and sequence number
- Supports querying and export

Used for the "step traceability" guarantee in core features.
"""

import json
import logging
import time
from dataclasses import asdict, dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class TraceStep:
    """Single operation step record."""

    step: int
    action: str
    params: dict
    result: dict
    status: str  # success / error
    error: str | None = None
    duration_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)
    session_id: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class ActionTracer:
    """
    Step tracer, integrated into BrowserController.

    Every atomic operation call records via record_step():
    - Operation type (goto, click, input_text, etc.)
    - Input parameters
    - Output results
    - Duration
    - Status

    Supports querying and exporting the full trace.
    """

    def __init__(self, session_id: str | None = None):
        self.session_id = session_id
        self._steps: list[TraceStep] = []
        self._step_counter: int = 0

    def record_step(
        self,
        action: str,
        params: dict,
        result: dict,
        status: str = "success",
        error: str | None = None,
        duration_ms: float = 0.0,
    ) -> TraceStep:
        """
        Record one operation step.

        Args:
            action: Operation name (goto, click, etc.)
            params: Operation parameters
            result: Operation result data
            status: success / error
            error: Error message (optional)
            duration_ms: Execution duration in milliseconds

        Returns:
            TraceStep record
        """
        self._step_counter += 1
        step = TraceStep(
            step=self._step_counter,
            action=action,
            params=params,
            result=result,
            status=status,
            error=error,
            duration_ms=duration_ms,
            timestamp=time.time(),
            session_id=self.session_id,
        )
        self._steps.append(step)

        logger.debug(f"[Trace] step={step.step} action={action} status={status} duration={duration_ms:.0f}ms")

        return step

    def start_timer(self) -> float:
        """Start timing, return start timestamp."""
        return time.time()

    def elapsed_ms(self, start: float) -> float:
        """Calculate elapsed time in milliseconds."""
        return (time.time() - start) * 1000

    def get_steps(self) -> list[TraceStep]:
        """Get all steps."""
        return list(self._steps)

    def get_step(self, step_num: int) -> TraceStep | None:
        """Get a specific step by number."""
        for s in self._steps:
            if s.step == step_num:
                return s
        return None

    def get_summary(self) -> dict:
        """Get trace summary."""
        success_count = sum(1 for s in self._steps if s.status == "success")
        error_count = sum(1 for s in self._steps if s.status == "error")
        total_duration = sum(s.duration_ms for s in self._steps)

        return {
            "session_id": self.session_id,
            "total_steps": len(self._steps),
            "success_count": success_count,
            "error_count": error_count,
            "total_duration_ms": round(total_duration, 1),
        }

    def export_trace(self) -> list[dict]:
        """Export all steps as a JSON-serializable list."""
        return [s.to_dict() for s in self._steps]

    def export_json(self, indent: int = 2) -> str:
        """Export as a JSON string."""
        return json.dumps(self.export_trace(), indent=indent, ensure_ascii=False)

    def clear(self):
        """Clear the trace."""
        self._steps.clear()
        self._step_counter = 0

    @property
    def step_count(self) -> int:
        return len(self._steps)
