"""Fallback 测试 — 错误恢复策略"""
from unittest.mock import AsyncMock, patch

import pytest

from agent_browser.pipeline.classifier import ErrorCategory
from agent_browser.pipeline.errors import (
    PipelineStepError,
    StepTimeoutError,
)
from agent_browser.pipeline.fallback import (
    _FALLBACK_HANDLER_NAMES,
    attempt_fallback,
)


class TestFallbackHandlersExist:
    """每种已知类别都有 handler"""

    def test_selector_drift_has_handler(self):
        assert ErrorCategory.SELECTOR_DRIFT in _FALLBACK_HANDLER_NAMES

    def test_timeout_has_handler(self):
        assert ErrorCategory.TIMEOUT in _FALLBACK_HANDLER_NAMES

    def test_auth_failure_has_handler(self):
        assert ErrorCategory.AUTH_FAILURE in _FALLBACK_HANDLER_NAMES

    def test_unknown_has_no_handler(self):
        assert ErrorCategory.UNKNOWN not in _FALLBACK_HANDLER_NAMES


class TestFallbackSelectorDrift:
    @pytest.mark.asyncio
    async def test_recovery_on_snapshot_success(self):
        """页面有元素时 selector drift 恢复成功"""
        pe = PipelineStepError(
            message="element not found: #job-card",
            step_index=2, step_name="click",
            adapter_name="boss/search",
        )

        mock_handler = AsyncMock(return_value=True)
        with patch("agent_browser.pipeline.fallback._get_fallback_handler",
                   return_value=mock_handler):

            recovered = await attempt_fallback("s1", pe, {"data": []})
            assert recovered is True

    @pytest.mark.asyncio
    async def test_no_recovery_on_empty_page(self):
        """页面无元素时 selector drift 恢复失败"""
        pe = PipelineStepError(
            message="element not found",
            step_index=2, step_name="click",
        )

        with patch("agent_browser.pipeline.fallback._retry_with_fresh_selector",
                   new_callable=AsyncMock(return_value=False)):

            recovered = await attempt_fallback("s1", pe, {"data": []})
            assert recovered is False

    @pytest.mark.asyncio
    async def test_unknown_category_no_handler(self):
        """未知类别不尝试恢复"""
        pe = PipelineStepError(message="weird error", step_index=0)

        recovered = await attempt_fallback("s1", pe, {})
        assert recovered is False


class TestFallbackTimeout:
    @pytest.mark.asyncio
    async def test_timeout_retry_increases_timeout(self):
        """超时恢复：增加超时后重试成功"""
        te = StepTimeoutError(
            message="timed out after 5s",
            step_index=1, step_name="wait",
            session_id="s1",
        )

        mock_handler = AsyncMock(return_value=True)
        with patch("agent_browser.pipeline.fallback._get_fallback_handler",
                   return_value=mock_handler):

            recovered = await attempt_fallback("s1", te, {"data": None})
            assert recovered is True

    @pytest.mark.asyncio
    async def test_timeout_retry_fails(self):
        """超时恢复失败时返回原始错误"""
        te = StepTimeoutError(message="timed out", step_index=1)

        with patch("agent_browser.pipeline.fallback._retry_with_longer_timeout",
                   new_callable=AsyncMock(return_value=False)):

            recovered = await attempt_fallback("s1", te, {})
            assert recovered is False


class TestFallbackAuthFailure:
    @pytest.mark.asyncio
    async def test_auth_marks_reauth_required(self):
        """认证失败标记需要重新认证，无法自动恢复"""
        pe = PipelineStepError(
            message="401 unauthorized",
            step_index=3, step_name="fetch",
        )

        context = {}
        recovered = await attempt_fallback("s1", pe, context)
        assert recovered is False
        assert context.get("_reauth_required") is True


class TestFallbackMaxRetries:
    @pytest.mark.asyncio
    async def test_respects_max_retries_param(self):
        """尊重 max_retries 参数"""
        pe = PipelineStepError(message="fail", step_index=0)

        mock_handler = AsyncMock(return_value=False)
        with patch("agent_browser.pipeline.fallback._get_fallback_handler",
                   return_value=mock_handler):

            result = await attempt_fallback("s1", pe, {}, max_retries=3)
            assert result is False
            assert mock_handler.call_count == 3  # 尝试了 3 次
