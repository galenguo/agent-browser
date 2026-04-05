"""Pipeline 执行 telemetry — 零外部依赖的本地统计

存储格式: JSONL (~/.agent-browser/telemetry.jsonl)
每行一条记录，append-only 写入。

使用方式:
    from pipeline.telemetry import Telemetry
    Telemetry.record("boss/search", True, 1200, 5, 5)
    stats = Telemetry.get_stats("boss/search")  # 单 adapter
    stats = Telemetry.get_stats()           # 全局
"""
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from collections import defaultdict

_TEL_DIR = Path.home() / ".agent-browser"
_TEL_FILE = _TEL_DIR / "telemetry.jsonl"


class Telemetry:
    """本地 telemetry 收集器 — append-only JSONL"""

    @staticmethod
    def record(
        adapter: str,
        success: bool,
        duration_ms: int,
        steps_executed: int,
        steps_total: int,
        error_category: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> None:
        """记录一次 pipeline 执行"""
        entry: Dict[str, Any] = {
            "ts": time.time(),
            "adapter": adapter,
            "success": success,
            "duration_ms": duration_ms,
            "steps_executed": steps_executed,
            "steps_total": steps_total,
        }
        if error_category:
            entry["error_category"] = error_category
        if session_id:
            entry["session_id"] = session_id[-8:]  # 截断保护隐私

        try:
            _TEL_DIR.mkdir(parents=True, exist_ok=True)
            with open(_TEL_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass  # telemetry 不应阻断主流程

    @staticmethod
    def get_stats(adapter: Optional[str] = None) -> Dict[str, Any]:
        """
        获取统计摘要。

        Args:
            adapter: 指定 adapter 名称获取单适配器统计，None 获取全局统计

        Returns:
            统计字典: {total, success_rate, avg_duration_ms, error_categories, by_adapter}
        """
        entries = Telemetry._load_entries()
        if adapter:
            entries = [e for e in entries if e.get("adapter") == adapter]

        total = len(entries)
        if total == 0:
            return {"total": 0}

        successes = sum(1 for e in entries if e.get("success"))
        total_duration = sum(e.get("duration_ms", 0) for e in entries)

        # 错误分类统计
        categories: Dict[str, int] = defaultdict(int)
        for e in entries:
            cat = e.get("error_category", "none")
            categories[cat] += 1

        # 按 adapter 分解（仅全局统计）
        by_adapter: Dict[str, Dict[str, Any]] = {}
        if not adapter:
            for e in entries:
                a = e.get("adapter", "unknown")
                if a not in by_adapter:
                    by_adapter[a] = {"total": 0, "success": 0, "failures": 0}
                by_adapter[a]["total"] += 1
                if e.get("success"):
                    by_adapter[a]["success"] += 1
                else:
                    by_adapter[a]["failures"] += 1
            # 计算每个 adapter 的成功率
            for a, s in by_adapter.items():
                s["success_rate"] = s["success"] / s["total"] if s["total"] > 0 else 0

        result: Dict[str, Any] = {
            "total": total,
            "success_count": successes,
            "failure_count": total - successes,
            "success_rate": successes / total,
            "avg_duration_ms": round(total_duration / total) if total > 0 else 0,
            "error_categories": dict(categories),
        }
        if by_adapter:
            result["by_adapter"] = by_adapter

        return result

    @staticmethod
    def get_recent(n: int = 20) -> List[Dict[str, Any]]:
        """获取最近 N 条记录（最新的在前）"""
        entries = Telemetry._load_entries()
        return entries[-n:] if n > 0 else []

    @staticmethod
    def clear() -> int:
        """清除所有 telemetry 数据。返回删除的条数。"""
        if not _TEL_FILE.exists():
            return 0
        count = sum(1 for _ in open(_TEL_FILE))
        _TEL_FILE.unlink(missing_ok=True)
        return count

    @staticmethod
    def _load_entries() -> List[Dict[str, Any]]:
        """加载所有记录"""
        entries: List[Dict[str, Any]] = []
        if not _TEL_FILE.exists():
            return entries
        try:
            with open(_TEL_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except OSError:
            pass
        return entries
