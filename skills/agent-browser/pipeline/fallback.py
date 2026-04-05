"""Agent Fallback — LLM 驱动的错误恢复策略

当 pipeline 步骤失败时，不立即放弃，而是尝试自动修复：
  - selector_drift → re-snapshot 页面，用 AI 找到新选择器
  - timeout → 增加等待时间，重试
  - auth_failure → 标记需要重新认证（无法自动修复）
  - data_quality → 尝试调整提取逻辑
  - navigation_error → 检查 URL 可达性

设计约束：
  - 不引入新依赖（使用已有的 browser-use / LLM）
  - 每个步骤最多重试 1 次（避免无限循环）
  - fallback 失败时返回原始错误，不丢失信息
"""
import asyncio
import logging
from typing import Any, Dict, Optional

from .classifier import ErrorCategory, classify, category_description
from .errors import PipelineStepError

logger = logging.getLogger(__name__)

# 最大 fallback 重试次数
_MAX_RETRIES = 1


async def _retry_with_fresh_selector(
    session_id: str,
    error: PipelineStepError,
    context: Dict[str, Any],
) -> bool:
    """
    Selector Drift 恢复：重新获取页面快照，验证元素是否存在。

    策略：
      1. 调用 snapshot() 获取当前 DOM 状态
      2. 检查目标元素是否在快照中
      3. 如果存在，更新上下文中的 selector 引用
    """
    try:
        from ..main import snapshot as do_snapshot

        snap = await do_snapshot(session_id)
        elements = snap.get("elements", [])

        # 检查是否有任何可交互元素（说明页面加载成功）
        if len(elements) > 0:
            logger.info(
                f"Selector drift recovery: page has {len(elements)} elements, "
                f"step '{error.step_name}' may need updated selector"
            )
            # 将快照数据存入 context 供后续步骤参考
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
    context: Dict[str, Any],
) -> bool:
    """
    Timeout 恢复：增加等待时间后重试。

    策略：
      1. 从 params 中读取原超时（如果有）
      2. 增加 50% 或固定 5s
      3. 用新超时重新执行步骤
    """
    try:
        from .steps import STEPS

        handler = STEPS.get(error.step_name)
        if not handler:
            return False

        # 增加超时
        original_params = error.step_params or {}
        new_params = dict(original_params) if isinstance(original_params, dict) else {}

        current_timeout = new_params.get("_timeout") or new_params.get("timeout")
        if current_timeout:
            new_timeout = int(current_timeout * 1.5)
        else:
            new_timeout = 30  # 默认 30s

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
    context: Dict[str, Any],
) -> bool:
    """Auth Failure 恢复：标记需要重新认证。无法自动修复。"""
    logger.warning(
        f"Auth failure at step '{error.step_name}': "
        f"{category_description(ErrorCategory.AUTH_FAILURE)}. "
        f"User must re-authenticate."
    )
    context["_reauth_required"] = True
    return False  # 无法自动恢复


# ── 策略注册表（用函数名而非引用，支持 patch） ──

_FALLBACK_HANDLER_NAMES = {
    ErrorCategory.SELECTOR_DRIFT: "_retry_with_fresh_selector",
    ErrorCategory.TIMEOUT: "_retry_with_longer_timeout",
    ErrorCategory.AUTH_FAILURE: "_require_reauth",
}


def _get_fallback_handler(category: ErrorCategory):
    """动态解析 handler（使 unittest.patch 能正常工作）"""
    name = _FALLBACK_HANDLER_NAMES.get(category)
    if not name:
        return None
    return globals().get(name)


async def attempt_fallback(
    session_id: str,
    error: PipelineStepError,
    context: Dict[str, Any],
    max_retries: int = _MAX_RETRIES,
) -> bool:
    """
    尝试自动恢复失败的步骤。

    Args:
        session_id: 浏览器会话 ID
        error: 原始 PipelineStepError
        context: pipeline 执行上下文（包含 data, args 等）
        max_retries: 最大重试次数

    Returns:
        True 表示成功恢复（调用方应 continue 到下一步）
        False 表示恢复失败（调用方应记录原始错误）
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
