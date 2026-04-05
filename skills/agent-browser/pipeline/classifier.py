"""Pipeline 错误分类器 — 将 PipelineError 映射到可操作策略

分类维度：
  - SELECTOR_DRIFT: 选择器过期，DOM 结构变化
  - TIMEOUT: 页面加载慢、网络超时
  - AUTH_FAILURE: Cookie/session 过期，401/403
  - DATA_QUALITY: 返回数据格式变化或为空
  - NAVIGATION_ERROR: URL 无效、被阻断、DNS 失败
  - UNKNOWN: 无法自动分类
"""
from enum import Enum
from typing import Any, Dict, Optional, Tuple

from .errors import (
    PipelineError,
    PipelineStepError,
    StepTimeoutError,
    SelectorNotFoundError,
    URLError,
)


class ErrorCategory(Enum):
    """错误类别 — 决定 fallback 策略"""
    SELECTOR_DRIFT = "selector_drift"
    TIMEOUT = "timeout"
    AUTH_FAILURE = "auth_failure"
    DATA_QUALITY = "data_quality"
    NAVIGATION_ERROR = "navigation_error"
    UNKNOWN = "unknown"


# ── 分类规则 ──

_STATUS_CODE_RE = r'\b(\d{3})\b'
TIMEOUT_KEYWORDS = ("timeout", "timed out", "超时")
AUTH_KEYWORDS = ("401", "403", "unauthorized", "forbidden", "登录", "过期",
                 "cookie", "session", "auth")
SELECTOR_KEYWORDS = ("selector", "not found", "element", "找不到", "ref@",
                    "locator", "visible")
NAVIGATION_KEYWORDS = ("url", "navigate", "dns", "connection refused",
                     "connection reset", "ssl", "certificate", "blocked")


def _extract_status_code(message: str) -> Optional[int]:
    """从错误消息中提取 HTTP 状态码"""
    import re
    match = re.search(_STATUS_CODE_RE, message)
    if match:
        return int(match.group(1))
    return None


def classify(error: PipelineError) -> Tuple[ErrorCategory, Dict[str, Any]]:
    """
    将 PipelineError 分类为 ErrorCategory + 元数据。

    Returns:
        (category, metadata) 元组
        metadata 包含策略执行需要的上下文信息
    """
    msg_lower = str(error).lower()
    meta: Dict[str, Any] = {
        "step_name": error.step_name,
        "step_index": error.step_index,
        "adapter_name": error.adapter_name,
        "raw_message": str(error),
    }

    # 1. 按异常类型快速匹配（最精确）
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

    # 2. 按 PipelineStepError 的消息内容启发式分类
    if isinstance(error, PipelineStepError):
        # Auth 检测
        if any(kw in msg_lower for kw in AUTH_KEYWORDS):
            status = _extract_status_code(msg_lower)
            auth_meta = {**meta}
            if status:
                auth_meta["status_code"] = status
            return ErrorCategory.AUTH_FAILURE, auth_meta

        # Timeout 检测（未被 StepTimeoutError 捕获的）
        if any(kw in msg_lower for kw in TIMEOUT_KEYWORDS):
            return ErrorCategory.TIMEOUT, {**meta, "hint": "operation_timeout"}

        # Selector/元素检测
        if any(kw in msg_lower for kw in SELECTOR_KEYWORDS):
            return ErrorCategory.SELECTOR_DRIFT, {**meta, "hint": "element_issue"}

        # Navigation/URL 检测
        if any(kw in msg_lower for kw in NAVIGATION_KEYWORDS):
            return ErrorCategory.NAVIGATION_ERROR, {**meta, "hint": "url_or_connection"}

        # 数据质量：空结果、解析失败
        if any(kw in msg_lower for kw in ("empty", "no data", "parse", "json",
                                            "index", "keyerror")):
            return ErrorCategory.DATA_QUALITY, {**meta, "hint": "data_format"}

    # 3. 兜底
    return ErrorCategory.UNKNOWN, meta


def category_description(category: ErrorCategory) -> str:
    """返回面向用户的分类描述"""
    descriptions = {
        ErrorCategory.SELECTOR_DRIFT: "页面结构已变化，选择器需要更新",
        ErrorCategory.TIMEOUT: "操作超时，可能需要增加等待时间",
        ErrorCategory.AUTH_FAILURE: "认证失效，需要重新登录或更新凭证",
        ErrorCategory.DATA_QUALITY: "数据格式不符合预期，可能需要调整提取逻辑",
        ErrorCategory.NAVIGATION_ERROR: "导航失败，URL 可能无效或被阻断",
        ErrorCategory.UNKNOWN: "未知错误类型，请检查日志",
    }
    return descriptions.get(category, "未知错误")
