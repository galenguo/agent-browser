"""
快速冒烟测试 — 只跑 3 个高风险测试用例

用法: python quick_benchmark.py

输出格式与 parallel_benchmark.py 一致，用于快速判断实验是否安全。
通过 → 直接 KEEP；失败 → 用 parallel_benchmark.py 全量确认。
"""
import time
import asyncio
import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

import importlib.util
_ab_path = os.path.join(PROJECT_ROOT, "skills", "agent-browser")
_ab_spec = importlib.util.spec_from_file_location(
    "agent_browser",
    os.path.join(_ab_path, "__init__.py"),
    submodule_search_locations=[_ab_path]
)
_ab_mod = importlib.util.module_from_spec(_ab_spec)
sys.modules["agent_browser"] = _ab_mod
_ab_spec.loader.exec_module(_ab_mod)

from benchmark import (
    TestCase, TestResult, BenchmarkResult,
    TEST_SCENARIOS, CDP_URL,
    run_test_case,
)

# 只跑这 3 个高风险测试
SMOKE_TESTS = [
    TestCase("full_search_and_extract", "complex",
             "百度搜索 ai coding → 提取前5条", weight=3.0),
    TestCase("baidu_search_ai_coding", "search",
             "百度搜索 'ai coding' 提取前5条结果", weight=2.0),
    TestCase("fingerprint_check", "stealth",
             "访问 creep.js 验证浏览器指纹", weight=2.0),
]


async def run_smoke() -> BenchmarkResult:
    start_total = time.time()

    print(f"⚡ 快速冒烟测试 — {len(SMOKE_TESTS)} 个高风险用例")
    print("=" * 60)

    results = []
    for case in SMOKE_TESTS:
        r = await run_test_case(case)
        results.append(r)
        icon = "✅" if r.passed else "❌"
        suffix = f" — {r.error}" if r.error else ""
        extra = ""
        if r.data:
            if "extracted" in r.data:
                extra = f" (提取 {r.data['count']} 条)"
            elif "result_links" in r.data:
                extra = f" (找到 {r.data['result_links']} 条链接)"
            elif "elements" in r.data:
                extra = f" ({r.data['elements']} 个元素)"
        print(f"  {icon} {case.name}: {r.duration_ms:.0f}ms, "
              f"{r.steps} steps{extra}{suffix}")

    total_time = time.time() - start_total

    total_weight = sum(c.weight for c in SMOKE_TESTS)
    weighted_success = sum(
        c.weight for c, r in zip(SMOKE_TESTS, results) if r.passed
    )
    passed = [r for r in results if r.passed]

    return BenchmarkResult(
        success_rate=weighted_success / total_weight if total_weight else 0,
        avg_steps=sum(r.steps for r in passed) / max(len(passed), 1),
        avg_time_seconds=total_time,
        total_tests=len(results),
        passed_tests=len(passed),
        category_scores={},
        raw_results=results,
    )


def main():
    result = asyncio.run(run_smoke())

    print("\n" + "=" * 60)
    print(f"⚡ 冒烟结果: {result.passed_tests}/{result.total_tests} 通过")
    print(f"   加权成功率: {result.success_rate:.1%}")
    print(f"   耗时: {result.avg_time_seconds:.1f}s")

    print()
    print("---")
    print(f"success_rate:      {result.success_rate:.6f}")
    print(f"avg_steps:         {result.avg_steps:.1f}")
    print(f"avg_time_seconds:  {result.avg_time_seconds:.1f}")
    print(f"passed_tests:      {result.passed_tests}")
    print(f"total_tests:       {result.total_tests}")


if __name__ == "__main__":
    main()
