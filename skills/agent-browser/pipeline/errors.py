"""Pipeline 异常层次 — 带上下文的类型化错误。

提供 PipelineError 基类和子类，每个错误携带：
  - step_index: 失败的步骤索引
  - step_name: 步骤操作名（click, evaluate 等）
  - adapter_name: "boss/search" 格式
  - session_id / page_url: 执行上下文
  - fix_hint: 人类可读的修复建议
"""
import logging

logger = logging.getLogger(__name__)


class PipelineError(Exception):
    """Pipeline 执行错误基类"""

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
        """结构化输出，适合日志和 API 响应"""
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
        """面向用户的友好消息"""
        parts = [f"Adapter '{self.adapter_name}' failed"]
        if self.step_index >= 0:
            parts.append(f"at step {self.step_index} '{self.step_name}'")
        parts.append(f": {self.message}")
        if self.fix_hint:
            parts.append(f"\nFix: {self.fix_hint}")
        return "".join(parts)


class AdapterLoadError(PipelineError):
    """YAML 解析/加载失败"""


class AdapterValidationError(PipelineError):
    """YAML 结构校验失败"""


class PipelineStepError(PipelineError):
    """Step 执行失败"""


class StepTimeoutError(PipelineStepError):
    """Step 超时"""


class SelectorNotFoundError(PipelineStepError):
    """选择器未找到元素"""


class URLError(PipelineError):
    """URL 无效或被阻断"""


# ── Fix Hint 规则表 ──

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
    """根据 step 类型生成修复建议"""
    hint = _HINTS.get(step_name)
    if hint:
        return hint
    # 通用 fallback
    if "timeout" in error_msg.lower():
        return "Operation timed out. Increase timeout or check if page is hanging."
    if "not found" in error_msg.lower():
        return "Target element or resource not found. Inspect page state with snapshot()."
    return "Check logs for details and verify page state."
