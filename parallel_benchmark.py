"""
并行基准测试 — 同时运行所有测试用例

用法: python parallel_benchmark.py [--workers N]

与 benchmark.py 完全相同的测试，但所有测试用例并行执行。
每个测试创建独立的 browser context，互不干扰。

输出格式与 benchmark.py 一致，autoresearch Agent 可直接解析。
"""
import time
import asyncio
import sys
import os
from dataclasses import dataclass, field
from typing import List, Dict, Optional
import argparse

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

create_session = _ab_mod.create_session
delete_session = _ab_mod.delete_session
open_page = _ab_mod.open_page
snapshot = _ab_mod.snapshot
click = _ab_mod.click
fill = _ab_mod.fill

# 复用 benchmark.py 的测试定义和执行逻辑
from benchmark import (
    TestCase, TestResult, BenchmarkResult,
    TEST_SCENARIOS, CDP_URL, REMOTE_CDP_URL,
    run_test_case,
)


async def run_benchmark_parallel(max_concurrent: int = 6) -> BenchmarkResult:
    """并行运行所有测试用例"""
    start_total = time.time()

    # 收集所有测试用例
    all_cases: List[TestCase] = []
    for cat_key, cat_data in TEST_SCENARIOS.items():
        for case in cat_data["cases"]:
            all_cases.append(case)

    print(f"🔍 并行基准测试 — {len(all_cases)} 个用例, {max_concurrent} 并发")
    print("=" * 60)

    # 使用 Semaphore 控制并发数
    sem = asyncio.Semaphore(max_concurrent)
    results: List[TestResult] = []

    async def run_with_sem(case: TestCase) -> TestResult:
        async with sem:
            return await run_test_case(case)

    # 并行执行所有测试
    tasks = [run_with_sem(case) for case in all_cases]
    results = await asyncio.gather(*tasks)
    results = list(results)

    total_time = time.time() - start_total

    # 按分类打印结果
    for cat_key, cat_data in TEST_SCENARIOS.items():
        print(f"\n📂 {cat_data['name']}")
        for case in cat_data["cases"]:
            r = next((r for r in results if r.name == case.name), None)
            if r:
                icon = "✅" if r.passed else "❌"
                suffix = f" — {r.error}" if r.error else ""
                extra = ""
                if r.data:
                    if "skipped" in r.data:
                        icon = "⏭️"
                        extra = f" (跳过: {r.data['reason']})"
                    elif "extracted" in r.data:
                        extra = f" (提取 {r.data['count']} 条)"
                    elif "result_links" in r.data:
                        extra = f" (找到 {r.data['result_links']} 条链接)"
                    elif "elements" in r.data:
                        extra = f" ({r.data['elements']} 个元素)"
                print(f"  {icon} {case.name}: {r.duration_ms:.0f}ms, "
                      f"{r.steps} steps{extra}{suffix}")

    # 计算加权成功率
    total_weight = 0.0
    weighted_success = 0.0
    for r in results:
        w = 1.0
        for cat_data in TEST_SCENARIOS.values():
            for c in cat_data["cases"]:
                if c.name == r.name:
                    w = c.weight
                    break
        total_weight += w
        if r.passed:
            weighted_success += w

    passed = [r for r in results if r.passed]

    category_scores = {}
    for cat_key, cat_data in TEST_SCENARIOS.items():
        cat_names = {c.name for c in cat_data["cases"]}
        cat_results = [r for r in results if r.name in cat_names]
        if cat_results:
            cat_passed = sum(1 for r in cat_results if r.passed)
            category_scores[cat_key] = cat_passed / len(cat_results)

    return BenchmarkResult(
        success_rate=weighted_success / total_weight if total_weight else 0,
        avg_steps=sum(r.steps for r in passed) / max(len(passed), 1),
        avg_time_seconds=total_time,  # 总耗时（并行）
        total_tests=len(results),
        passed_tests=len(passed),
        category_scores=category_scores,
        raw_results=results,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", "-w", type=int, default=6,
                        help="最大并发测试数 (默认 6)")
    args = parser.parse_args()

    result = asyncio.run(run_benchmark_parallel(args.workers))

    print("\n" + "=" * 60)
    print(f"📊 总结果: {result.passed_tests}/{result.total_tests} 通过")
    print(f"   加权成功率: {result.success_rate:.1%}")
    print(f"   总耗时: {result.avg_time_seconds:.1f}s (并行)")
    print()
    print("📋 分场景得分:")
    for cat, score in result.category_scores.items():
        print(f"   {cat}: {score:.1%}")

    # 固定输出格式（与 benchmark.py 一致）
    print()
    print("---")
    print(f"success_rate:      {result.success_rate:.6f}")
    print(f"avg_steps:         {result.avg_steps:.1f}")
    print(f"avg_time_seconds:  {result.avg_time_seconds:.1f}")
    print(f"passed_tests:      {result.passed_tests}")
    print(f"total_tests:       {result.total_tests}")


if __name__ == "__main__":
    main()
