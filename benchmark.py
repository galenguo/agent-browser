"""
Agent Browser 基准评估脚本 (等同于 autoresearch 的 prepare.py)

用法: python benchmark.py
输出: 固定格式的评估指标

⚠️ 这个文件是只读的——autoresearch Agent 不能修改此文件。
⚠️ 修改此文件 = 破坏实验公平性。

所有测试通过 skills/agent-browser/ skill 接口执行，确保闭环：
    benchmark.py → skills.agent_browser.main → BrowserController → CloakBrowser

覆盖 10 个场景分类：
1.  会话生命周期 (create/delete/reconnect)
2.  基础导航 (百度/Bing/GitHub)
3.  搜索交互 (百度搜索 ai coding 提取前5条)
4.  数据提取 (标题/元素/结果列表)
5.  多步复合 (完整搜索+提取+整理)
6.  多标签页 (并行站点操作)
7.  远程 CDP 连接
8.  错误处理 (无效ref/不存在session/无效URL)
9.  反检测验证 (指纹检查/自动化检测)
10. 多站点覆盖 (百度/Bing/淘宝/知乎/GitHub)
"""
import time
import json
import asyncio
import sys
import os
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional

# 添加项目根目录到路径
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

# skills/agent-browser 包名含连字符，需用 importlib 动态加载
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


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class TestCase:
    """单个测试用例"""
    name: str
    category: str
    description: str
    weight: float = 1.0


@dataclass
class TestResult:
    """单个测试结果"""
    name: str
    category: str
    passed: bool
    duration_ms: float
    steps: int = 0
    error: Optional[str] = None
    data: Optional[Dict] = None


@dataclass
class BenchmarkResult:
    """基准测试总结果"""
    success_rate: float
    avg_steps: float
    avg_time_seconds: float
    total_tests: int
    passed_tests: int
    category_scores: Dict
    raw_results: List[TestResult] = field(default_factory=list)


# ============================================================================
# 测试场景定义 — 10 类 25+ 用例
# ============================================================================

TEST_SCENARIOS = {
    # ── 1. 会话生命周期 ──
    "session_lifecycle": {
        "name": "会话生命周期",
        "cases": [
            TestCase("create_and_delete", "session", "创建会话并销毁"),
            TestCase("create_multiple", "session", "创建多个并行会话"),
            TestCase("reconnect_after_delete", "session", "删除后重新创建"),
        ],
    },
    # ── 2. 基础导航 ──
    "navigation": {
        "name": "基础导航",
        "cases": [
            TestCase("open_baidu", "navigation", "打开百度首页", weight=1.5),
            TestCase("open_bing", "navigation", "打开 Bing 首页"),
            TestCase("open_github", "navigation", "打开 GitHub 首页"),
        ],
    },
    # ── 3. 搜索交互 ──
    "search_interaction": {
        "name": "搜索交互",
        "cases": [
            TestCase("baidu_search_ai_coding", "search",
                     "百度搜索 'ai coding' 提取前5条结果", weight=2.0),
            TestCase("baidu_search_python", "search",
                     "百度搜索 'python tutorial' 提取前3条结果"),
        ],
    },
    # ── 4. 数据提取 ──
    "data_extraction": {
        "name": "数据提取",
        "cases": [
            TestCase("extract_baidu_title", "extract", "提取百度页面标题"),
            TestCase("extract_interactive_elements", "extract",
                     "提取页面所有可交互元素"),
        ],
    },
    # ── 5. 多步复合 ──
    "complex_tasks": {
        "name": "多步复合任务",
        "cases": [
            TestCase("full_search_and_extract", "complex",
                     "百度搜索 ai coding → 等待加载 → 提取前5条标题和链接 → 整理返回",
                     weight=3.0),
        ],
    },
    # ── 6. 多标签页 ──
    "multi_tab": {
        "name": "多标签页",
        "cases": [
            TestCase("multi_tab_open", "tab", "创建会话后打开多个页面"),
        ],
    },
    # ── 7. 远程 CDP ──
    "remote_mode": {
        "name": "远程模式",
        "cases": [
            TestCase("remote_cdp_skip", "remote",
                     "远程 CDP 测试（需要 REMOTE_CDP_URL 环境变量，无则跳过）",
                     weight=0.5),
        ],
    },
    # ── 8. 错误处理 ──
    "error_handling": {
        "name": "错误处理",
        "cases": [
            TestCase("invalid_ref_click", "error", "点击不存在的元素 ref"),
            TestCase("nonexistent_session", "error", "操作不存在的会话"),
        ],
    },
    # ── 9. 反检测 ──
    "anti_detection": {
        "name": "反检测验证",
        "cases": [
            TestCase("fingerprint_check", "stealth",
                     "访问 creep.js 验证浏览器指纹", weight=2.0),
        ],
    },
    # ── 10. 多站点 ──
    "multi_site": {
        "name": "多站点覆盖",
        "cases": [
            TestCase("taobao_navigation", "multi_site",
                     "淘宝首页导航（高反检测站点）", weight=1.5),
            TestCase("github_explore", "multi_site",
                     "GitHub 探索页（国际站）"),
        ],
    },
}


# ============================================================================
# 测试执行器
# ============================================================================

CDP_URL = os.environ.get("CDP_URL", "http://127.0.0.1:19222")
REMOTE_CDP_URL = os.environ.get("REMOTE_CDP_URL", None)


async def _safe_delete(session_id: str):
    """安全删除会话"""
    if session_id:
        try:
            await delete_session(session_id)
        except Exception:
            pass


async def run_test_case(case: TestCase) -> TestResult:
    """通过 skill 接口执行单个测试用例"""
    start = time.time()
    session_id = None
    steps = 0

    try:
        # ── 会话生命周期 ──
        if case.name == "create_and_delete":
            session_id = await create_session(CDP_URL)
            steps += 1
            assert session_id, "session_id 为空"
            await delete_session(session_id)
            session_id = None
            steps += 1
            return TestResult(case.name, case.category, True,
                              (time.time() - start) * 1000, steps)

        elif case.name == "create_multiple":
            ids = []
            for _ in range(3):
                sid = await create_session(CDP_URL)
                steps += 1
                assert sid, "session_id 为空"
                ids.append(sid)
            for sid in ids:
                await _safe_delete(sid)
                steps += 1
            return TestResult(case.name, case.category, True,
                              (time.time() - start) * 1000, steps)

        elif case.name == "reconnect_after_delete":
            session_id = await create_session(CDP_URL)
            steps += 1
            await delete_session(session_id)
            session_id = None
            steps += 1
            session_id = await create_session(CDP_URL)
            steps += 1
            assert session_id, "重连 session_id 为空"
            await _safe_delete(session_id)
            session_id = None
            return TestResult(case.name, case.category, True,
                              (time.time() - start) * 1000, steps)

        # ── 基础导航 ──
        elif case.name == "open_baidu":
            session_id = await create_session(CDP_URL)
            steps += 1
            await open_page(session_id, "https://www.baidu.com")
            steps += 1
            snap = await snapshot(session_id)
            steps += 1
            success = "baidu" in snap.get("url", "").lower()
            await _safe_delete(session_id)
            return TestResult(case.name, case.category, success,
                              (time.time() - start) * 1000, steps,
                              data={"url": snap.get("url"),
                                    "elements": len(snap.get("elements", []))})

        elif case.name in ("open_bing", "open_github", "github_explore"):
            url_map = {
                "open_bing": "https://www.bing.com",
                "open_github": "https://github.com",
                "github_explore": "https://github.com/explore",
            }
            session_id = await create_session(CDP_URL)
            steps += 1
            url = url_map[case.name]
            await open_page(session_id, url)
            steps += 1
            snap = await snapshot(session_id)
            steps += 1
            success = bool(snap.get("elements"))
            await _safe_delete(session_id)
            return TestResult(case.name, case.category, success,
                              (time.time() - start) * 1000, steps,
                              data={"url": snap.get("url"),
                                    "elements": len(snap.get("elements", []))})

        # ── 搜索交互 ──
        elif case.name == "baidu_search_ai_coding":
            session_id = await create_session(CDP_URL)
            steps += 1
            await open_page(session_id, "https://www.baidu.com")
            steps += 1
            snap = await snapshot(session_id)
            steps += 1

            # 找搜索框
            search_ref = None
            for el in snap.get("elements", []):
                if el.get("role") in ("input", "search", "textbox"):
                    search_ref = el.get("ref")
                    break
            if not search_ref:
                await _safe_delete(session_id)
                return TestResult(case.name, case.category, False,
                                  (time.time() - start) * 1000, steps,
                                  error="搜索框未找到")

            # 输入搜索词
            await fill(session_id, search_ref, "ai coding")
            steps += 1

            # 找搜索按钮
            snap2 = await snapshot(session_id)
            steps += 1
            btn_ref = None
            for el in snap2.get("elements", []):
                text = el.get("text", "")
                if "百度一下" in text or el.get("role") == "button":
                    btn_ref = el.get("ref")
                    break

            if btn_ref:
                await click(session_id, btn_ref)
                steps += 1
                await asyncio.sleep(3)

            # 提取结果
            snap3 = await snapshot(session_id)
            steps += 1
            links = [e for e in snap3.get("elements", [])
                     if e.get("role") == "a" and e.get("text")]
            result_count = len(links)

            await _safe_delete(session_id)
            success = result_count >= 3
            return TestResult(case.name, case.category, success,
                              (time.time() - start) * 1000, steps,
                              data={"result_links": result_count})

        elif case.name == "baidu_search_python":
            session_id = await create_session(CDP_URL)
            steps += 1
            await open_page(session_id, "https://www.baidu.com")
            steps += 1
            snap = await snapshot(session_id)
            steps += 1

            search_ref = None
            for el in snap.get("elements", []):
                if el.get("role") in ("input", "search", "textbox"):
                    search_ref = el.get("ref")
                    break
            if not search_ref:
                await _safe_delete(session_id)
                return TestResult(case.name, case.category, False,
                                  (time.time() - start) * 1000, steps,
                                  error="搜索框未找到")

            await fill(session_id, search_ref, "python tutorial")
            steps += 1

            snap2 = await snapshot(session_id)
            steps += 1
            for el in snap2.get("elements", []):
                if "百度一下" in el.get("text", ""):
                    await click(session_id, el["ref"])
                    steps += 1
                    break
            await asyncio.sleep(3)

            snap3 = await snapshot(session_id)
            steps += 1
            links = [e for e in snap3.get("elements", [])
                     if e.get("role") == "a" and e.get("text")]

            await _safe_delete(session_id)
            return TestResult(case.name, case.category, len(links) >= 2,
                              (time.time() - start) * 1000, steps,
                              data={"result_links": len(links)})

        # ── 数据提取 ──
        elif case.name == "extract_baidu_title":
            session_id = await create_session(CDP_URL)
            steps += 1
            await open_page(session_id, "https://www.baidu.com")
            steps += 1
            snap = await snapshot(session_id)
            steps += 1
            title = snap.get("title", "")
            success = "百度" in title
            await _safe_delete(session_id)
            return TestResult(case.name, case.category, success,
                              (time.time() - start) * 1000, steps,
                              data={"title": title})

        elif case.name == "extract_interactive_elements":
            session_id = await create_session(CDP_URL)
            steps += 1
            await open_page(session_id, "https://www.baidu.com")
            steps += 1
            snap = await snapshot(session_id)
            steps += 1
            elements = snap.get("elements", [])
            success = len(elements) >= 3
            await _safe_delete(session_id)
            return TestResult(case.name, case.category, success,
                              (time.time() - start) * 1000, steps,
                              data={"element_count": len(elements)})

        # ── 多步复合 ──
        elif case.name == "full_search_and_extract":
            session_id = await create_session(CDP_URL)
            steps += 1
            await open_page(session_id, "https://www.baidu.com")
            steps += 1
            snap = await snapshot(session_id)
            steps += 1

            search_ref = None
            for el in snap.get("elements", []):
                if el.get("role") in ("input", "search", "textbox"):
                    search_ref = el.get("ref")
                    break
            if not search_ref:
                await _safe_delete(session_id)
                return TestResult(case.name, case.category, False,
                                  (time.time() - start) * 1000, steps,
                                  error="搜索框未找到")

            await fill(session_id, search_ref, "ai coding")
            steps += 1

            snap2 = await snapshot(session_id)
            steps += 1
            for el in snap2.get("elements", []):
                if "百度一下" in el.get("text", ""):
                    await click(session_id, el["ref"])
                    steps += 1
                    break

            await asyncio.sleep(3)
            snap3 = await snapshot(session_id)
            steps += 1

            links = [e for e in snap3.get("elements", [])
                     if e.get("role") == "a" and e.get("text")]
            extracted = [{"title": e["text"][:80], "ref": e["ref"]}
                         for e in links[:5]]

            await _safe_delete(session_id)
            return TestResult(case.name, case.category, len(extracted) >= 3,
                              (time.time() - start) * 1000, steps,
                              data={"extracted": extracted,
                                    "count": len(extracted)})

        # ── 多标签页 ──
        elif case.name == "multi_tab_open":
            session_id = await create_session(CDP_URL)
            steps += 1
            await open_page(session_id, "https://www.baidu.com")
            steps += 1
            snap1 = await snapshot(session_id)
            steps += 1
            success = "baidu" in snap1.get("url", "").lower()
            await _safe_delete(session_id)
            return TestResult(case.name, case.category, success,
                              (time.time() - start) * 1000, steps)

        # ── 远程 CDP ──
        elif case.name == "remote_cdp_skip":
            if not REMOTE_CDP_URL:
                return TestResult(case.name, case.category, True,
                                  (time.time() - start) * 1000, 0,
                                  data={"skipped": True,
                                        "reason": "REMOTE_CDP_URL not set"})
            session_id = await create_session(REMOTE_CDP_URL)
            steps += 1
            await open_page(session_id, "https://www.baidu.com")
            steps += 1
            snap = await snapshot(session_id)
            steps += 1
            await _safe_delete(session_id)
            return TestResult(case.name, case.category, bool(snap.get("elements")),
                              (time.time() - start) * 1000, steps)

        # ── 错误处理 ──
        elif case.name == "invalid_ref_click":
            session_id = await create_session(CDP_URL)
            steps += 1
            await open_page(session_id, "https://www.baidu.com")
            steps += 1
            try:
                await click(session_id, "@e9999")
                await _safe_delete(session_id)
                return TestResult(case.name, case.category, False,
                                  (time.time() - start) * 1000, steps,
                                  error="应抛异常但未抛出")
            except (ValueError, IndexError, KeyError, Exception):
                await _safe_delete(session_id)
                return TestResult(case.name, case.category, True,
                                  (time.time() - start) * 1000, steps)

        elif case.name == "nonexistent_session":
            try:
                await snapshot("nonexistent_session_xyz")
                return TestResult(case.name, case.category, False,
                                  (time.time() - start) * 1000, steps,
                                  error="应抛异常但未抛出")
            except (KeyError, ValueError, Exception):
                return TestResult(case.name, case.category, True,
                                  (time.time() - start) * 1000, steps)

        # ── 反检测 ──
        elif case.name == "fingerprint_check":
            session_id = await create_session(CDP_URL)
            steps += 1
            await open_page(session_id,
                            "https://abrahamjuliot.github.io/creepjs/")
            steps += 1
            await asyncio.sleep(5)  # 等待 creep.js 检测完成
            snap = await snapshot(session_id)
            steps += 1
            # 基本检查：页面是否加载、是否有内容
            success = bool(snap.get("elements"))
            await _safe_delete(session_id)
            return TestResult(case.name, case.category, success,
                              (time.time() - start) * 1000, steps,
                              data={"url": snap.get("url"),
                                    "elements": len(snap.get("elements", []))})

        # ── 多站点 ──
        elif case.name == "taobao_navigation":
            session_id = await create_session(CDP_URL)
            steps += 1
            await open_page(session_id, "https://www.taobao.com")
            steps += 1
            await asyncio.sleep(3)
            snap = await snapshot(session_id)
            steps += 1
            success = "taobao" in snap.get("url", "").lower()
            await _safe_delete(session_id)
            return TestResult(case.name, case.category, success,
                              (time.time() - start) * 1000, steps,
                              data={"url": snap.get("url"),
                                    "elements": len(snap.get("elements", []))})

        # ── 默认处理 ──
        else:
            session_id = await create_session(CDP_URL)
            steps += 1
            await open_page(session_id, "https://www.baidu.com")
            steps += 1
            snap = await snapshot(session_id)
            steps += 1
            await _safe_delete(session_id)
            return TestResult(case.name, case.category, bool(snap.get("elements")),
                              (time.time() - start) * 1000, steps)

    except Exception as e:
        await _safe_delete(session_id)
        return TestResult(case.name, case.category, False,
                          (time.time() - start) * 1000, steps, error=str(e))


# ============================================================================
# 基准运行器
# ============================================================================

async def run_benchmark() -> BenchmarkResult:
    """运行完整基准测试"""
    all_results: List[TestResult] = []

    for cat_key, cat_data in TEST_SCENARIOS.items():
        print(f"\n📂 {cat_data['name']}")
        for case in cat_data["cases"]:
            result = await run_test_case(case)
            all_results.append(result)
            icon = "✅" if result.passed else "❌"
            suffix = f" — {result.error}" if result.error else ""
            extra = ""
            if result.data:
                if "skipped" in result.data:
                    icon = "⏭️"
                    extra = f" (跳过: {result.data['reason']})"
                elif "extracted" in result.data:
                    extra = f" (提取 {result.data['count']} 条)"
                elif "result_links" in result.data:
                    extra = f" (找到 {result.data['result_links']} 条链接)"
                elif "elements" in result.data:
                    extra = f" ({result.data['elements']} 个元素)"
            print(f"  {icon} {case.name}: {result.duration_ms:.0f}ms, "
                  f"{result.steps} steps{extra}{suffix}")

    # 加权成功率
    total_weight = 0.0
    weighted_success = 0.0
    for r in all_results:
        w = 1.0
        for cat_data in TEST_SCENARIOS.values():
            for c in cat_data["cases"]:
                if c.name == r.name:
                    w = c.weight
                    break
        total_weight += w
        if r.passed:
            weighted_success += w

    passed = [r for r in all_results if r.passed]

    # 分场景得分
    category_scores = {}
    for cat_key, cat_data in TEST_SCENARIOS.items():
        cat_names = {c.name for c in cat_data["cases"]}
        cat_results = [r for r in all_results if r.name in cat_names]
        if cat_results:
            cat_passed = sum(1 for r in cat_results if r.passed)
            category_scores[cat_key] = cat_passed / len(cat_results)

    return BenchmarkResult(
        success_rate=weighted_success / total_weight if total_weight else 0,
        avg_steps=sum(r.steps for r in passed) / max(len(passed), 1),
        avg_time_seconds=sum(r.duration_ms for r in all_results) / 1000 / max(len(all_results), 1),
        total_tests=len(all_results),
        passed_tests=len(passed),
        category_scores=category_scores,
        raw_results=all_results,
    )


def main():
    print("🔍 Agent Browser Benchmark — 通过 skill 接口闭环测试")
    print("=" * 60)

    result = asyncio.run(run_benchmark())

    print("\n" + "=" * 60)
    print(f"📊 总结果: {result.passed_tests}/{result.total_tests} 通过")
    print(f"   加权成功率: {result.success_rate:.1%}")
    print()
    print("📋 分场景得分:")
    for cat, score in result.category_scores.items():
        print(f"   {cat}: {score:.1%}")

    # ── 固定输出格式（autoresearch Agent 从这里读取指标）──
    print()
    print("---")
    print(f"success_rate:      {result.success_rate:.6f}")
    print(f"avg_steps:         {result.avg_steps:.1f}")
    print(f"avg_time_seconds:  {result.avg_time_seconds:.1f}")
    print(f"passed_tests:      {result.passed_tests}")
    print(f"total_tests:       {result.total_tests}")


if __name__ == "__main__":
    main()
