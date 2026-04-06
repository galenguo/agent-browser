"""Debugger 测试 — 单步执行和状态检查"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_browser.pipeline.debugger import DebugSession, StepRecord, _summarize, debug_pipeline


class TestSummarize:
    def test_none(self):
        assert _summarize(None) == "None"

    def test_list(self):
        result = _summarize([1, 2, 3])
        assert result == "[3 items] [1, 2, 3]"

    def test_dict(self):
        result = _summarize({"a": 1, "b": 2})
        assert "dict" in result
        assert "2 keys" in result or "1 key" in result

    def test_long_string_truncated(self):
        long_str = "x" * 300
        result = _summarize(long_str)
        assert "..." in result

    def test_short_string_passthrough(self):
        assert _summarize("hello") == "hello"


class TestStepRecord:
    def test_to_dict_success(self):
        r = StepRecord(
            step_index=0, op="navigate", params={"url": "https://x.com"}, output_type="None", duration_ms=120
        )
        d = r.to_dict()
        assert d["step_index"] == 0
        assert d["op"] == "navigate"
        assert d["duration_ms"] == 120
        assert "error" not in d

    def test_to_dict_with_error(self):
        r = StepRecord(step_index=1, op="click", params=None, error={"type": "ValueError", "message": "bad ref"})
        d = r.to_dict()
        assert d["error"]["type"] == "ValueError"


class TestDebugSessionInit:
    def test_init(self):
        steps = [{"navigate": "u"}, {"click": "@e0"}, {"evaluate": "1+1"}]
        ds = DebugSession(steps, "s1", {"q": "test"})
        assert ds.total_steps == 3
        assert ds.current_step == 0
        assert ds.breakpoints == set()

    def test_init_with_breakpoints(self):
        steps = [{"navigate": "u"}] * 5
        ds = DebugSession(steps, "s1", {}, breakpoints=[2, 4])
        assert ds.breakpoints == {2, 4}

    def test_initial_state(self):
        ds = DebugSession([{"navigate": "u"}], "s1", {})
        state = ds.get_state()
        assert state["current_step"] == 0
        assert state["total_steps"] == 1
        assert state["completed"] is False


class TestDebugSessionRun:
    @pytest.mark.asyncio
    async def test_run_to_breakpoint(self):
        steps = [
            {"navigate": "https://example.com"},
            {"wait": "body"},
            {"click": "@e0"},
            {"evaluate": "document.title"},
        ]
        ds = DebugSession(steps, "s1", {}, breakpoints=[2])
        result = await ds.run_to_breakpoint()

        assert result["status"] == "breakpoint"
        assert result["step"] == 2  # 刚完成第 2 步（wait），暂停
        assert result["breakpoint_hit"] == 2
        assert len(result["history"]) == 2  # navigate + wait
        assert ds.current_step == 2

    @pytest.mark.asyncio
    async def test_run_to_completion(self):
        steps = [
            {"navigate": "https://example.com"},
            {"evaluate": "'hello'"},
        ]
        ds = DebugSession(steps, "s1", {}, breakpoints=[])
        result = await ds.run_to_breakpoint()

        assert result["status"] == "completed"
        assert result["step"] == 2
        assert ds._completed is True
        assert len(result["history"]) == 2

    @pytest.mark.asyncio
    @patch("agent_browser.pipeline.steps.STEPS", new_callable=dict)
    async def test_unknown_step_skipped(self, mock_steps):
        """未知步骤应跳过并记录错误，不崩溃"""
        steps = [
            {"navigate": "https://example.com"},
            {"nonexistent_step": "params"},
            {"evaluate": "'ok'"},
        ]
        ds = DebugSession(steps, "s1", {}, breakpoints=[3])
        result = await ds.run_to_breakpoint()

        assert result["status"] == "completed"
        assert result["step"] == 3
        # nonexistent_step 应有 error 记录
        error_records = [r for r in result["history"] if "error" in r]
        assert len(error_records) >= 1
        assert (
            "nonexistent" in str(error_records[0]["error"]).lower()
            or "unknown" in str(error_records[0]["error"]).lower()
        )

    @pytest.mark.asyncio
    async def test_state_after_partial_run(self):
        steps = [{"navigate": "u"}] * 3
        ds = DebugSession(steps, "s1", {}, breakpoints=[2])
        await ds.run_to_breakpoint()  # 执行到 step 2 后暂停
        state = ds.get_state()
        assert state["current_step"] == 2
        assert state["completed"] is False
        assert state["history_count"] == 2


class TestDebugPipelineFunction:
    @pytest.mark.asyncio
    async def test_debug_pipeline_returns_data_on_completion(self):
        """debug_pipeline 在完成时返回数据（与 execute_pipeline 兼容）"""
        with patch("agent_browser.pipeline.debugger.DebugSession") as MockDS:
            mock_instance = MagicMock()
            mock_instance.run_to_breakpoint = AsyncMock(
                return_value={
                    "status": "completed",
                    "step": 2,
                    "data": ["result1", "result2"],
                    "history": [],
                    "total_steps": 2,
                }
            )
            MockDS.return_value = mock_instance

            result = await debug_pipeline([{"navigate": "u"}, {"evaluate": "1+1"}], "s1", {"q": "x"})
        assert result == ["result1", "result2"]

    @pytest.mark.asyncio
    async def test_debug_pipeline_returns_state_on_breakpoint(self):
        """debug_pipeline 在断点时返回状态字典"""
        with patch("agent_browser.pipeline.debugger.DebugSession") as MockDS:
            mock_instance = MagicMock()
            mock_instance.run_to_breakpoint = AsyncMock(
                return_value={
                    "status": "breakpoint",
                    "step": 1,
                    "data": None,
                    "history": [],
                    "breakpoint_hit": 1,
                    "total_steps": 2,
                }
            )
            MockDS.return_value = mock_instance

            result = await debug_pipeline([{"navigate": "u"}, {"evaluate": "1+1"}], "s1", {}, breakpoints=[1])
        assert result["status"] == "breakpoint"
        assert result["breakpoint_hit"] == 1
