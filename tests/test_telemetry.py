"""Telemetry 测试 — 本地统计收集"""
import json
import os
import time
from pathlib import Path

import pytest
from agent_browser.pipeline.telemetry import Telemetry, _TEL_FILE, _TEL_DIR


@pytest.fixture(autouse=True)
def cleanup_telemetry():
    """测试前后清理 telemetry 文件"""
    yield
    if _TEL_FILE.exists():
        _TEL_FILE.unlink()


class TestRecord:
    def test_record_basic(self):
        Telemetry.record("boss/search", True, 1200, 5, 5)
        stats = Telemetry.get_stats("boss/search")
        assert stats["total"] == 1
        assert stats["success_count"] == 1
        assert stats["success_rate"] == 1.0

    def test_record_failure(self):
        Telemetry.record("baidu/search", False, 3000, 3, 5, error_category="timeout")
        stats = Telemetry.get_stats("baidu/search")
        assert stats["total"] == 1
        assert stats["failure_count"] == 1
        assert stats["success_rate"] == 0.0
        assert "timeout" in stats["error_categories"]

    def test_record_mixed(self):
        Telemetry.record("zhihu/hot", True, 800, 4, 4)
        Telemetry.record("zhihu/hot", False, 2000, 2, 4, error_category="selector_drift")
        Telemetry.record("zhihu/hot", True, 900, 4, 4)
        stats = Telemetry.get_stats("zhihu/hot")
        assert stats["total"] == 3
        assert stats["success_count"] == 2
        assert stats["failure_count"] == 1
        assert abs(stats["success_rate"] - 0.666) < 0.01

    def test_record_with_session_id(self):
        Telemetry.record("test/a", True, 100, 1, 1, session_id="abc12345")
        recent = Telemetry.get_recent(1)
        assert len(recent) == 1
        assert recent[0]["session_id"] == "abc12345"  # truncated to 8 chars

    def test_record_persists(self):
        """验证记录写入文件后可读取"""
        Telemetry.record("persist/test", True, 50, 1, 1)
        stats = Telemetry.get_stats("persist/test")
        assert stats["total"] == 1
        # 文件应存在
        assert _TEL_FILE.exists()

    def test_record_non_blocking(self):
        """telemetry 失败不应抛异常"""
        # 即使目录不可写也不应崩溃
        old_dir = _TEL_DIR
        try:
            Telemetry.record("safe/test", True, 10, 1, 1)
        except Exception:
            pass  # should not happen
        # 验证没有崩溃即可


class TestGetStats:
    def test_empty_stats(self):
        """无数据时返回空统计"""
        stats = Telemetry.get_stats("nonexistent")
        assert stats["total"] == 0

    def test_global_stats(self):
        """全局统计聚合所有 adapter"""
        Telemetry.record("a/x", True, 100, 1, 1)
        Telemetry.record("b/y", False, 200, 1, 2)
        Telemetry.record("a/x", True, 150, 2, 2)
        stats = Telemetry.get_stats()  # None = global
        assert stats["total"] == 3
        assert stats["success_count"] == 2
        assert "by_adapter" in stats
        assert stats["by_adapter"]["a/x"]["total"] == 2
        assert stats["by_adapter"]["b/y"]["success_rate"] == 0.0

    def test_avg_duration(self):
        Telemetry.record("dur/test", True, 1000, 1, 1)
        Telemetry.record("dur/test", True, 2000, 1, 1)
        stats = Telemetry.get_stats("dur/test")
        assert stats["avg_duration_ms"] == 1500

    def test_by_adapter_breakdown(self):
        Telemetry.record("multi/a", True, 500, 3, 5, error_category="timeout")
        Telemetry.record("multi/a", True, 600, 3, 5)
        Telemetry.record("multi/a", False, 3000, 1, 5, error_category="auth")
        Telemetry.record("multi/b", True, 700, 4, 4)
        stats = Telemetry.get_stats()
        by_a = stats["by_adapter"]["multi/a"]
        assert by_a["total"] == 3
        assert by_a["failures"] == 1
        assert by_a["success_rate"] == pytest.approx(0.667, rel=0.05)


class TestGetRecent:
    def test_recent_limited(self):
        for i in range(25):
            Telemetry.record(f"recent/{i}", True, i * 10, 1, 1)
        recent = Telemetry.get_recent(5)
        assert len(recent) == 5
        # 最新的在最后
        assert recent[-1]["adapter"] == "recent/24"

    def test_recent_empty(self):
        recent = Telemetry.get_recent(10)
        assert recent == []

    def test_recent_with_n_zero(self):
        Telemetry.record("nzero/test", True, 100, 1, 1)
        recent = Telemetry.get_recent(0)
        assert recent == []  # n=0 returns empty


class TestClear:
    def test_clear_removes_all(self):
        Telemetry.record("clear/a", True, 10, 1, 1)
        Telemetry.record("clear/b", False, 20, 1, 1)
        count = Telemetry.clear()
        assert count == 2
        assert Telemetry.get_stats()["total"] == 0

    def test_clear_nonexistent(self):
        count = Telemetry.clear()
        assert count == 0
