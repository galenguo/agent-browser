"""
ActionTracer - 步骤跟踪器

记录每次原子操作的完整信息：
- 操作类型和参数
- 执行结果和耗时
- 时间戳和顺序号
- 支持查询和导出

用于 §3.4 核心特性中的"步骤可跟踪"保证。
"""
import time
import json
import logging
from typing import Any, Optional
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


@dataclass
class TraceStep:
    """单个操作步骤记录"""
    step: int
    action: str
    params: dict
    result: dict
    status: str  # success / error
    error: Optional[str] = None
    duration_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)
    session_id: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


class ActionTracer:
    """
    步骤跟踪器，集成到 BrowserController。

    每次原子操作调用 record_step() 记录：
    - 操作类型（goto、click、input_text 等）
    - 输入参数
    - 输出结果
    - 耗时
    - 状态

    支持查询和导出全部 trace。
    """

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id
        self._steps: list[TraceStep] = []
        self._step_counter: int = 0

    def record_step(
        self,
        action: str,
        params: dict,
        result: dict,
        status: str = "success",
        error: Optional[str] = None,
        duration_ms: float = 0.0,
    ) -> TraceStep:
        """
        记录一步操作。

        Args:
            action: 操作名称（goto、click 等）
            params: 操作参数
            result: 操作结果数据
            status: success / error
            error: 错误信息（可选）
            duration_ms: 执行耗时（毫秒）

        Returns:
            TraceStep 记录
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

        logger.debug(
            f"[Trace] step={step.step} action={action} status={status} "
            f"duration={duration_ms:.0f}ms"
        )

        return step

    def start_timer(self) -> float:
        """开始计时，返回起始时间戳"""
        return time.time()

    def elapsed_ms(self, start: float) -> float:
        """计算耗时（毫秒）"""
        return (time.time() - start) * 1000

    def get_steps(self) -> list[TraceStep]:
        """获取所有步骤"""
        return list(self._steps)

    def get_step(self, step_num: int) -> Optional[TraceStep]:
        """获取指定步骤"""
        for s in self._steps:
            if s.step == step_num:
                return s
        return None

    def get_summary(self) -> dict:
        """获取 trace 摘要"""
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
        """导出全部步骤为 JSON 可序列化列表"""
        return [s.to_dict() for s in self._steps]

    def export_json(self, indent: int = 2) -> str:
        """导出为 JSON 字符串"""
        return json.dumps(self.export_trace(), indent=indent, ensure_ascii=False)

    def clear(self):
        """清空 trace"""
        self._steps.clear()
        self._step_counter = 0

    @property
    def step_count(self) -> int:
        return len(self._steps)
