"""
Phase 0 Baseline Measurements

在重构前建立性能基线，用于验证重构后性能无回归。

测量项：
  1. LLM 模式原子操作延迟（goto / click / fill / scroll / snapshot）
  2. Agent 模式 run_task 延迟（6 步 × 2 chunks）
  3. 隐匿开销（stealth ON vs OFF 的差值）
  4. 中间件包装开销（StealthPageHandle vs raw PageHandle）

目标：中间件开销 <5ms/操作

用法：
  # 需要运行中的 CloakBrowser (port 19222)
  python -m scripts.baseline_measurements
  # 或仅测试隐匿组件延迟（无需浏览器）
  python -m scripts.baseline_measurements --stealth-only
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# 确保项目路径在 sys.path 中
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))
if str(_project_root / "src") not in sys.path:
    sys.path.insert(0, str(_project_root / "src"))
if str(_project_root / "skills") not in sys.path:
    sys.path.insert(0, str(_project_root / "skills"))

logger = logging.getLogger(__name__)

# ── 结果存储 ────────────────────────────────────────


@dataclass
class MeasurementResult:
    """单次测量结果"""
    name: str
    duration_ms: float
    success: bool
    error: Optional[str] = None


@dataclass
class BaselineReport:
    """基线报告"""
    timestamp: str = ""
    results: Dict[str, List[MeasurementResult]] = field(default_factory=dict)

    def add(self, result: MeasurementResult):
        self.results.setdefault(result.name, []).append(result)

    def summary(self) -> dict:
        """生成统计摘要"""
        summary = {}
        for name, measurements in self.results.items():
            durations = [m.duration_ms for m in measurements if m.success]
            if not durations:
                summary[name] = {"count": len(measurements), "success": 0, "error": "all_failed"}
                continue

            summary[name] = {
                "count": len(durations),
                "success": len(durations),
                "mean_ms": round(statistics.mean(durations), 2),
                "median_ms": round(statistics.median(durations), 2),
                "p95_ms": round(sorted(durations)[int(len(durations) * 0.95)] if len(durations) > 1 else durations[0], 2),
                "min_ms": round(min(durations), 2),
                "max_ms": round(max(durations), 2),
            }
        return summary


# ── 测量工具 ────────────────────────────────────────


async def measure_op(name: str, coro_fn, iterations: int = 5) -> MeasurementResult:
    """测量单个操作的多次执行时间"""
    durations = []
    errors = []

    for i in range(iterations):
        try:
            start = time.perf_counter()
            await coro_fn()
            elapsed = (time.perf_counter() - start) * 1000
            durations.append(elapsed)
        except Exception as e:
            errors.append(str(e))
            logger.debug(f"{name} iteration {i} failed: {e}")

    if durations:
        avg = statistics.mean(durations)
        return MeasurementResult(
            name=name,
            duration_ms=round(avg, 2),
            success=True,
        )
    else:
        return MeasurementResult(
            name=name,
            duration_ms=0,
            success=False,
            error=errors[0] if errors else "unknown",
        )


async def measure_stealth_component_overhead(iterations: int = 100) -> BaselineReport:
    """
    测量隐匿组件本身的纯开销（不需要浏览器）。

    测量：
      - pre_action() 各类型的延迟
      - post_action() 延迟
      - random_mouse_move() 的 JS 构造开销（mock page）
      - human_type() 字符级延迟模拟
      - StealthMiddleware 包装/解包开销
    """
    from core.stealth_enhancer import StealthEnhancer
    from src.stealth.middleware import StealthMiddleware, StealthPageHandle, _PerSessionCircuit

    report = BaselineReport()
    stealth = StealthEnhancer()

    # 1. pre_action 延迟（各类型）
    for action_type, label in [
        ("navigate", "pre_navigate"),
        ("click", "pre_click"),
        ("input", "pre_input"),
        ("scroll", "pre_scroll"),
        ("general", "pre_general"),
    ]:
        async def _op():
            await stealth.pre_action(action_type)

        for _ in range(iterations):
            r = await measure_op(label, _op, iterations=1)
            report.add(r)

    # 2. post_action 延迟
    async def _post():
        await stealth.post_action("general")
    r = await measure_op("post_action_general", _post, iterations=iterations)
    report.add(r)

    # 3. StealthMiddleware 创建开销（不含浏览器连接）
    async def _create_mw():
        from unittest.mock import MagicMock
        backend = MagicMock()
        backend.connect = asyncio.coroutine(lambda: None)
        cfg = MagicMock()
        cfg.stealth_enabled = True
        mw = StealthMiddleware(backend, cfg)
        await mw.connect()
    r = await measure_op("middleware_create_connect", _create_mw, iterations=10)
    report.add(r)

    # 4. StealthPageHandle 包装开销
    async def _wrap_overhead():
        from unittest.mock import MagicMock
        wrapped = MagicMock()
        wrapped.goto = asyncio.coroutine(lambda *a, **k: None)
        raw_page = MagicMock()
        type(wrapped).raw_page = property(lambda self: raw_page)

        circuit = _PerSessionCircuit()
        handle = StealthPageHandle(wrapped, stealth, circuit)
        # 调用一次 goto 测量包装开销
        await handle.goto("http://example.com")
    r = await measure_op("pagehandle_wrap_goto", _wrap_overhead, iterations=50)
    report.add(r)

    return report


async def measure_browser_operations(stealth_on: bool = True, iterations: int = 3) -> BaselineReport:
    """
    测量真实浏览器操作延迟（需要 CloakBrowser 运行在 :19222）。

    如果浏览器不可达，返回空报告并记录警告。
    """
    report = BaselineReport()

    try:
        from agent_browsermain import (
            create_session, delete_session, open_page,
            snapshot, click, fill, scroll, go_back, reset,
        )
        from agent_browserconfig import SkillConfig
    except ImportError as e:
        logger.warning(f"Cannot import skill modules: {e}")
        return report

    session_id = None
    try:
        # 配置
        reset()
        config = SkillConfig()
        config.stealth_enabled = stealth_on

        # 创建 session
        session_id = await create_session()
        mode_label = f"stealth_{'on' if stealth_on else 'off'}"

        # 导航
        async def _nav():
            await open_page(session_id, "https://www.baidu.com")
        r = await measure_op(f"{mode_label}_navigate_baidu", _nav, iterations=iterations)
        report.add(r)

        # 快照
        async def _snap():
            await snapshot(session_id)
        r = await measure_op(f"{mode_label}_snapshot", _snap, iterations=iterations)
        report.add(r)

        # 点击（需要先 snapshot 获取 refs）
        snap_data = await snapshot(session_id)
        elements = snap_data.get("elements", [])
        if elements:
            ref = elements[0].get("ref", "@e0") if elements else "@e0"

            async def _click():
                await click(session_id, ref)
            r = await measure_op(f"{mode_label}_click", _click, iterations=iterations)
            report.add(r)

            # 填充（如果有 input 元素）
            input_refs = [e["ref"] for e in elements if e.get("type") == "input" or e.get("tag") == "input"]
            if input_refs:
                async def _fill():
                    await fill(session_id, input_refs[0], "test text")
                r = await measure_op(f"{mode_label}_fill", _fill, iterations=iterations)
                report.add(r)

        # 滚动
        async def _scr():
            await scroll(session_id, "down", 300)
        r = await measure_op(f"{mode_label}_scroll", _scr, iterations=iterations)
        report.add(r)

        # 后退
        async def _back():
            await go_back(session_id)
        r = await measure_op(f"{mode_label}_go_back", _back, iterations=min(iterations, 2))
        report.add(r)

    except Exception as e:
        logger.warning(f"Browser measurement failed (browser may not be running): {e}")
        report.add(MeasurementResult(
            name="browser_ops",
            duration_ms=0,
            success=False,
            error=str(e),
        ))
    finally:
        if session_id:
            try:
                await delete_session(session_id)
            except Exception:
                pass
            reset()

    return report


# ── 主入口 ────────────────────────────────────────────


async def main(stealth_only: bool = False, output_file: Optional[str] = None):
    """运行所有基线测量"""
    print("=" * 60)
    print("Phase 0: Baseline Measurements")
    print("=" * 60)

    all_reports: list[BaselineReport] = []

    # ── 1. 隐匿组件纯开销（始终可测）──
    print("\n[1/2] Measuring stealth component overhead (no browser needed)...")
    stealth_report = await measure_stealth_component_overhead(iterations=50)
    all_reports.append(stealth_report)

    summary = stealth_report.summary()
    print(f"\n  Stealth Component Overhead ({sum(s['count'] for s in summary.values())} measurements):")
    for name, stats in sorted(summary.items()):
        status = "OK" if stats.get("success", 0) > 0 else "FAIL"
        print(f"    {name:40s} mean={stats.get('mean_ms', 0):>8.1f}ms  p95={stats.get('p95_ms', 0):>8.1f}ms  [{status}]")

    # ── 2. 浏览器操作延迟（需要 CloakBrowser）──
    if not stealth_only:
        print("\n[2/2] Measuring browser operations (needs CloakBrowser on :19222)...")

        # stealth ON
        print("  → Measuring with stealth ON...")
        report_on = await measure_browser_operations(stealth_on=True, iterations=3)
        all_reports.append(report_on)

        # stealth OFF
        print("  → Measuring with stealth OFF...")
        report_off = await measure_browser_operations(stealth_on=False, iterations=3)
        all_reports.append(report_off)

        # 对比
        print("\n  Browser Operations Comparison:")
        on_summary = report_on.summary()
        off_summary = report_off.summary()

        for name in sorted(set(list(on_summary.keys()) + list(off_summary.keys()))):
            on_stat = on_summary.get(name, {})
            off_stat = off_summary.get(name, {})
            on_mean = on_stat.get("mean_ms", 0)
            off_mean = off_stat.get("mean_ms", 0)
            delta = on_mean - off_mean if off_mean > 0 else 0
            print(f"    {name:45s} ON={on_mean:>7.1f}ms  OFF={off_mean:>7.1f}ms  Δ={delta:>+7.1f}ms")
    else:
        print("\n[2/2] Skipped browser measurements (--stealth-only)")

    # ── 输出结果 ──
    final_report = BaselineReport()
    for r in all_reports:
        for measurements in r.results.values():
            for m in measurements:
                final_report.add(m)

    final_summary = final_report.summary()
    total = sum(s.get("count", 0) for s in final_summary.values())
    successful = sum(s.get("success", 0) for s in final_summary.values())

    print(f"\n{'=' * 60}")
    print(f"Total: {total} measurements, {successful} successful")

    if output_file:
        out_path = Path(output_file)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        result_data = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "summary": final_summary,
            "raw_results": {
                name: [{"duration_ms": m.duration_ms, "success": m.success, "error": m.error}
                         for m in measurements]
                for name, measurements in final_report.results.items()
            },
        }
        out_path.write_text(json.dumps(result_data, indent=2, ensure_ascii=False))
        print(f"Results saved to {out_path}")

    return final_report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase 0 Baseline Measurements")
    parser.add_argument("--stealth-only", action="store_true",
                        help="Only measure stealth component overhead (no browser needed)")
    parser.add_argument("-o", "--output", default=None,
                        help="Output JSON file path")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(message)s")

    asyncio.run(main(stealth_only=args.stealth_only, output_file=args.output))
