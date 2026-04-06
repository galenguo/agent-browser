"""
集成测试：通过 Skill API 测试多场景组合

测试场景：
1. CLI + local + LLM 模式
2. CLI + local + Agent 模式 (需要 LLM API Key)
3. API + local + LLM 模式 (需要 FastAPI)
4. API + local + Agent 模式 (需要 FastAPI + LLM API Key)
5. API + remote + LLM 模式 (需要 FastAPI + Gateway)
6. API + remote + Agent 模式 (需要 FastAPI + Gateway + LLM API Key)

测试用例：
- 百度搜索 "ai coding"，返回前3条信息
- 小红书搜索 "中环小韭" 博主最近5条帖子
- Boss直聘 HR 招聘登录页二维码

数据流 (参考 Agent-Browser 架构方案V4):
- CLI + local: Agent → main.py → LocalCDPBackend → BrowserDaemon → CDP → CloakBrowser
- API + local: Agent → main.py → RemoteAPIBackend → HTTP → FastAPI → LocalCDPBackend → CDP
- API + remote: Agent → HTTP → FastAPI → Gateway /allocate → Docker CDP
"""
import asyncio
import os
import sys
import time
import traceback

from helpers.skill_loader import load_skill_module

# 动态加载 skill 模块
try:
    skill_main = load_skill_module("main")
    print("✅ Skill main module loaded")
except Exception as e:
    print(f"❌ Failed to load skill module: {e}")
    sys.exit(1)

# 测试提示词
TEST_PROMPTS = {
    "baidu_search": {
        "prompt": "打开百度搜索 ai coding，返回前3条信息内容",
        "url": "https://www.baidu.com",
        "description": "百度搜索测试"
    },
    "xiaohongshu_search": {
        "prompt": "打开小红书搜索中环小韭这个博主最近5条帖子",
        "url": "https://www.xiaohongshu.com",
        "description": "小红书搜索测试"
    },
    "boss_login": {
        "prompt": "打开boss直聘的hr招聘的登录页，打开二维码登录页面",
        "url": "https://www.zhipin.com",
        "description": "Boss直聘登录测试"
    }
}

# ========== 环境检查函数 ==========

async def check_cloakbrowser():
    """检查 CloakBrowser 是否运行 (local 浏览器模式)"""
    import aiohttp
    try:
        async with aiohttp.ClientSession() as session, \
                session.get("http://127.0.0.1:19222/json/version", timeout=aiohttp.ClientTimeout(total=3)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print(f"  ✅ CloakBrowser: {data.get('Browser', 'unknown')}")
                    return True
        return False
    except Exception as e:
        print(f"  ❌ CloakBrowser check failed: {e}")
        return False

async def check_fastapi():
    """检查 FastAPI 是否运行"""
    import aiohttp
    try:
        async with aiohttp.ClientSession() as session, \
                session.get("http://localhost:8000/health", timeout=aiohttp.ClientTimeout(total=3)) as resp:
                if resp.status == 200:
                    print("  ✅ FastAPI: http://localhost:8000")
                    return True
        return False
    except Exception as e:
        print(f"  ❌ FastAPI check failed: {e}")
        return False

async def check_gateway():
    """检查 Gateway 是否运行 (remote 浏览器模式)"""
    import aiohttp
    try:
        async with aiohttp.ClientSession() as session, \
                session.get("http://localhost:8001/health", timeout=aiohttp.ClientTimeout(total=3)) as resp:
                if resp.status == 200:
                    print("  ✅ Gateway: http://localhost:8001")
                    return True
        return False
    except Exception as e:
        print(f"  ❌ Gateway check failed: {e}")
        return False

def has_llm_key():
    """检查 LLM API Key 是否设置"""
    key_set = bool(os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY"))
    if key_set:
        provider = "OpenAI" if os.getenv("OPENAI_API_KEY") else "Anthropic"
        print(f"  ✅ LLM API Key: {provider}")
    else:
        print("  ⚠️ LLM API Key: 未设置")
    return key_set

# 环境依赖矩阵
ENV_REQUIREMENTS = {
    "cli_local_llm": {"checks": ["cloakbrowser"], "funcs": [check_cloakbrowser]},
    "cli_local_agent": {"checks": ["cloakbrowser", "llm_key"], "funcs": [check_cloakbrowser]},
    "api_local_llm": {"checks": ["fastapi", "cloakbrowser"], "funcs": [check_fastapi, check_cloakbrowser]},
    "api_local_agent": {"checks": ["fastapi", "cloakbrowser", "llm_key"], "funcs": [check_fastapi, check_cloakbrowser]},
    "api_remote_llm": {"checks": ["fastapi", "gateway"], "funcs": [check_fastapi, check_gateway]},
    "api_remote_agent": {"checks": ["fastapi", "gateway", "llm_key"], "funcs": [check_fastapi, check_gateway]},
}

async def check_dependencies(scenario: str) -> bool:
    """检查场景依赖是否满足"""
    req = ENV_REQUIREMENTS.get(scenario, {})
    checks = req.get("checks", [])
    funcs = req.get("funcs", [])

    print(f"  检查依赖: {checks}")

    # 运行异步检查
    check_results = await asyncio.gather(*[f() for f in funcs])

    # 检查 llm_key（同步）
    if "llm_key" in checks:
        check_results.append(has_llm_key())

    return all(check_results)

# ========== local 浏览器模式测试 ==========

async def test_cli_local_llm_mode(prompt_key: str) -> dict:
    """
    场景 1: CLI + local + LLM 模式

    数据流: Agent → main.py → LocalCDPBackend → BrowserDaemon → CDP → CloakBrowser
    """
    test = TEST_PROMPTS[prompt_key]
    result = {
        "scenario": "cli_local_llm",
        "prompt_key": prompt_key,
        "status": "UNKNOWN",
        "duration": 0,
        "error": None
    }

    start_time = time.time()

    try:
        # 重置全局状态并配置为 CLI + local 模式
        skill_main.reset()
        skill_main.configure(calling_mode="cli", browser_mode="local")

        # 创建 session
        session_id = await skill_main.create_session()
        print(f"    ✅ Session 创建成功: {session_id}")

        # 打开页面
        await skill_main.open_page(session_id, test["url"])
        print(f"    ✅ 页面打开: {test['url']}")

        # 获取快照
        snap = await skill_main.snapshot(session_id)
        elements = snap.get("elements", [])
        print(f"    ✅ Snapshot 获取: {len(elements)} 个元素")

        # 提取页面内容
        if elements:
            print("    前 3 个交互元素:")
            for i, elem in enumerate(elements[:3]):
                tag = elem.get("tag", "unknown")
                text = elem.get("text", "")[:50]
                print(f"      [{i}] {tag}: {text}")

        # 清理
        await skill_main.delete_session(session_id)
        print("    ✅ Session 已删除")

        result["status"] = "PASS"
        result["elements_count"] = len(elements)

    except Exception as e:
        result["status"] = "FAIL"
        result["error"] = str(e)
        print(f"    ❌ 测试失败: {e}")
        traceback.print_exc()

    result["duration"] = time.time() - start_time
    return result

async def test_cli_local_agent_mode(prompt_key: str) -> dict:
    """
    场景 2: CLI + local + Agent 模式

    数据流: Agent → main.py → LocalCDPBackend → browser-use Agent → LLM → CDP

    需要 LLM API Key
    """
    test = TEST_PROMPTS[prompt_key]
    result = {
        "scenario": "cli_local_agent",
        "prompt_key": prompt_key,
        "status": "UNKNOWN",
        "duration": 0,
        "error": None
    }

    start_time = time.time()

    try:
        # 重置全局状态并配置为 CLI + local 模式
        skill_main.reset()
        skill_main.configure(calling_mode="cli", browser_mode="local")

        # 创建 session
        session_id = await skill_main.create_session()
        print(f"    ✅ Session 创建成功: {session_id}")

        # 使用 Agent 执行任务
        agent_result = await skill_main.run_task(
            session_id,
            test["prompt"],
            intelligence="agent",
            max_steps=5  # 限制步数以加快测试
        )

        status = agent_result.get("status", "unknown")
        print(f"    ✅ Agent 执行完成: {status}")

        if agent_result.get("result"):
            output = agent_result["result"]
            if len(str(output)) > 300:
                output = str(output)[:300] + "..."
            print(f"    执行结果: {output}")

        # 清理
        await skill_main.delete_session(session_id)
        print("    ✅ Session 已删除")

        result["status"] = "PASS" if status in ["completed", "done", "success"] else "PARTIAL"
        result["agent_result"] = agent_result

    except Exception as e:
        result["status"] = "FAIL"
        result["error"] = str(e)
        print(f"    ❌ 测试失败: {e}")
        traceback.print_exc()

    result["duration"] = time.time() - start_time
    return result

async def test_api_local_llm_mode(prompt_key: str) -> dict:
    """
    场景 3: API + local + LLM 模式

    数据流: Agent → HTTP → FastAPI → LocalCDPBackend → CDP
    """
    test = TEST_PROMPTS[prompt_key]
    result = {
        "scenario": "api_local_llm",
        "prompt_key": prompt_key,
        "status": "UNKNOWN",
        "duration": 0,
        "error": None
    }

    start_time = time.time()

    try:
        # 重置全局状态并配置为 API + local 模式
        skill_main.reset()
        skill_main.configure(calling_mode="api", browser_mode="local", api_url="http://localhost:8000")

        # 创建 session
        session_id = await skill_main.create_session()
        print(f"    ✅ Session 创建成功: {session_id}")

        # 打开页面
        await skill_main.open_page(session_id, test["url"])
        print(f"    ✅ 页面打开: {test['url']}")

        # 获取快照
        snap = await skill_main.snapshot(session_id)
        elements = snap.get("elements", [])
        print(f"    ✅ Snapshot 获取: {len(elements)} 个元素")

        # 清理
        await skill_main.delete_session(session_id)
        print("    ✅ Session 已删除")

        result["status"] = "PASS"
        result["elements_count"] = len(elements)

    except Exception as e:
        result["status"] = "FAIL"
        result["error"] = str(e)
        print(f"    ❌ 测试失败: {e}")
        traceback.print_exc()

    result["duration"] = time.time() - start_time
    return result

async def test_api_local_agent_mode(prompt_key: str) -> dict:
    """
    场景 4: API + local + Agent 模式

    数据流: Agent → HTTP → FastAPI → browser-use Agent → CDP
    """
    test = TEST_PROMPTS[prompt_key]
    result = {
        "scenario": "api_local_agent",
        "prompt_key": prompt_key,
        "status": "UNKNOWN",
        "duration": 0,
        "error": None
    }

    start_time = time.time()

    try:
        # 重置全局状态并配置为 API + local + Agent 模式
        skill_main.reset()
        skill_main.configure(calling_mode="api", browser_mode="local", api_url="http://localhost:8000")

        # 创建 session
        session_id = await skill_main.create_session()
        print(f"    ✅ Session 创建成功: {session_id}")

        # 使用 Agent 执行任务
        agent_result = await skill_main.run_task(
            session_id,
            test["prompt"],
            intelligence="agent",
            max_steps=5
        )

        status = agent_result.get("status", "unknown")
        print(f"    ✅ Agent 执行完成: {status}")

        # 清理
        await skill_main.delete_session(session_id)
        print("    ✅ Session 已删除")

        result["status"] = "PASS" if status in ["completed", "done", "success"] else "PARTIAL"
        result["agent_result"] = agent_result

    except Exception as e:
        result["status"] = "FAIL"
        result["error"] = str(e)
        print(f"    ❌ 测试失败: {e}")
        traceback.print_exc()

    result["duration"] = time.time() - start_time
    return result

# ========== remote 浏览器模式测试（Gateway + Docker）==========

async def test_api_remote_llm_mode(prompt_key: str) -> dict:
    """
    场景 5: API + remote + LLM 模式

    数据流: Agent → HTTP → FastAPI → Gateway /allocate → Docker CDP
    """
    test = TEST_PROMPTS[prompt_key]
    result = {
        "scenario": "api_remote_llm",
        "prompt_key": prompt_key,
        "status": "UNKNOWN",
        "duration": 0,
        "error": None
    }

    start_time = time.time()

    try:
        # 重置全局状态并配置为 API + remote 模式
        skill_main.reset()
        skill_main.configure(
            calling_mode="api",
            browser_mode="remote",
            api_url="http://localhost:8000"
        )

        # 创建 session (Gateway 自动分配 Docker 浏览器)
        session_id = await skill_main.create_session()
        print(f"    ✅ Session 创建成功: {session_id}")
        print("    ✅ Gateway 已分配 Docker 浏览器")

        # 打开页面
        await skill_main.open_page(session_id, test["url"])
        print(f"    ✅ 页面打开: {test['url']}")

        # 获取快照
        snap = await skill_main.snapshot(session_id)
        elements = snap.get("elements", [])
        print(f"    ✅ Snapshot 获取: {len(elements)} 个元素")

        # 清理 (自动回收 Docker 容器)
        await skill_main.delete_session(session_id)
        print("    ✅ Session 已删除，Docker 容器已回收")

        result["status"] = "PASS"
        result["elements_count"] = len(elements)

    except Exception as e:
        result["status"] = "FAIL"
        result["error"] = str(e)
        print(f"    ❌ 测试失败: {e}")
        traceback.print_exc()

    result["duration"] = time.time() - start_time
    return result

async def test_api_remote_agent_mode(prompt_key: str) -> dict:
    """
    场景 6: API + remote + Agent 模式

    数据流: Agent → HTTP → FastAPI → Gateway → browser-use Agent → Docker CDP
    """
    test = TEST_PROMPTS[prompt_key]
    result = {
        "scenario": "api_remote_agent",
        "prompt_key": prompt_key,
        "status": "UNKNOWN",
        "duration": 0,
        "error": None
    }

    start_time = time.time()

    try:
        # 重置全局状态并配置为 API + remote + Agent 模式
        skill_main.reset()
        skill_main.configure(
            calling_mode="api",
            browser_mode="remote",
            api_url="http://localhost:8000"
        )

        # 创建 session
        session_id = await skill_main.create_session()
        print(f"    ✅ Session 创建成功: {session_id}")

        # 使用 Agent 执行任务
        agent_result = await skill_main.run_task(
            session_id,
            test["prompt"],
            intelligence="agent",
            max_steps=5
        )

        status = agent_result.get("status", "unknown")
        print(f"    ✅ Agent 执行完成: {status}")

        # 清理
        await skill_main.delete_session(session_id)
        print("    ✅ Session 已删除，Docker 容器已回收")

        result["status"] = "PASS" if status in ["completed", "done", "success"] else "PARTIAL"
        result["agent_result"] = agent_result

    except Exception as e:
        result["status"] = "FAIL"
        result["error"] = str(e)
        print(f"    ❌ 测试失败: {e}")
        traceback.print_exc()

    result["duration"] = time.time() - start_time
    return result

# ========== 测试函数映射 ==========

TEST_FUNCTIONS = {
    "cli_local_llm": test_cli_local_llm_mode,
    "cli_local_agent": test_cli_local_agent_mode,
    "api_local_llm": test_api_local_llm_mode,
    "api_local_agent": test_api_local_agent_mode,
    "api_remote_llm": test_api_remote_llm_mode,
    "api_remote_agent": test_api_remote_agent_mode,
}

# ========== 串行测试执行（避免全局状态冲突）==========

async def run_sequential_tests(scenarios: list, prompt_keys: list) -> list:
    """
    串行执行测试场景。

    注意：由于 skill 使用全局后端状态（_backend, _config），
    并行执行会导致状态冲突，因此改为串行执行。
    """
    results = []

    for scenario in scenarios:
        for prompt_key in prompt_keys:
            test_func = TEST_FUNCTIONS.get(scenario)
            if test_func:
                try:
                    print(f"\n  [{scenario}] {prompt_key}...")
                    result = await test_func(prompt_key)
                    results.append(result)
                except Exception as e:
                    results.append({
                        "scenario": scenario,
                        "prompt_key": prompt_key,
                        "status": "ERROR",
                        "error": str(e)
                    })

                # 测试间休息，让浏览器恢复
                await asyncio.sleep(1)

    return results

def print_summary(all_results: list):
    """打印测试汇总"""
    print("\n" + "=" * 70)
    print("测试汇总")
    print("=" * 70)

    passed = sum(1 for r in all_results if r.get("status") == "PASS")
    partial = sum(1 for r in all_results if r.get("status") == "PARTIAL")
    failed = sum(1 for r in all_results if r.get("status") == "FAIL")
    errors = sum(1 for r in all_results if r.get("status") in ["ERROR", "UNKNOWN"])
    skipped = sum(1 for r in all_results if r.get("status") == "SKIPPED")

    for r in all_results:
        status = r.get("status", "UNKNOWN")
        scenario = r.get("scenario", "unknown")
        prompt = r.get("prompt_key", "unknown")
        duration = r.get("duration", 0)

        if status == "PASS":
            icon = "✅"
        elif status == "PARTIAL":
            icon = "🔶"
        elif status == "SKIPPED":
            icon = "⏭️"
        else:
            icon = "❌"

        print(f"{icon} [{scenario}] {prompt}: {status} ({duration:.1f}s)")

        if r.get("error"):
            error_preview = str(r["error"])[:100]
            print(f"   Error: {error_preview}")

    print(f"\n总计: {passed} 通过, {partial} 部分通过, {failed} 失败, {errors} 错误, {skipped} 跳过")
    print(f"总测试数: {len(all_results)}")

async def main():
    """运行所有集成测试"""
    print("\n" + "=" * 70)
    print("Agent-Browser 集成测试")
    print("测试通过 Claude Code 安装 skills/agent-browser skill 进行")
    print("=" * 70)

    # 定义测试批次
    batches = [
        {
            "name": "CLI + local",
            "scenarios": ["cli_local_llm", "cli_local_agent"],
            "requires": ["cloakbrowser"],
            "require_llm_for": ["cli_local_agent"]
        },
        {
            "name": "API + local",
            "scenarios": ["api_local_llm", "api_local_agent"],
            "requires": ["fastapi", "cloakbrowser"],
            "require_llm_for": ["api_local_agent"]
        },
        {
            "name": "API + remote",
            "scenarios": ["api_remote_llm", "api_remote_agent"],
            "requires": ["fastapi", "gateway"],
            "require_llm_for": ["api_remote_agent"]
        }
    ]

    all_results = []
    prompt_keys = list(TEST_PROMPTS.keys())

    # ========== 环境检查 ==========
    print("\n" + "-" * 40)
    print("环境检查")
    print("-" * 40)

    env_status = {
        "cloakbrowser": await check_cloakbrowser(),
        "fastapi": await check_fastapi(),
        "gateway": await check_gateway(),
        "llm_key": has_llm_key()
    }

    # ========== 执行测试批次 ==========
    for batch in batches:
        print(f"\n{'='*60}")
        print(f"批次: {batch['name']}")
        print(f"{'='*60}")

        # 检查批次依赖
        batch_ok = True
        for req in batch["requires"]:
            if not env_status.get(req, False):
                print(f"⚠️ 跳过批次 {batch['name']}: 缺少 {req}")
                batch_ok = False
                break

        if not batch_ok:
            continue

        # 过滤需要 LLM 但没有 key 的场景
        scenarios_to_run = []
        for scenario in batch["scenarios"]:
            if scenario in batch.get("require_llm_for", []) and not env_status.get("llm_key", False):
                print(f"  ⏭️ 跳过 {scenario}: 需要 LLM API Key")
                all_results.append({
                    "scenario": scenario,
                    "status": "SKIPPED",
                    "reason": "No LLM API Key"
                })
                continue
            scenarios_to_run.append(scenario)

        if not scenarios_to_run:
            continue

        # 串行执行该批次所有测试（避免全局状态冲突）
        print(f"\n串行执行: {scenarios_to_run}")
        print(f"提示词: {prompt_keys}")

        results = await run_sequential_tests(scenarios_to_run, prompt_keys)
        all_results.extend(results)

        # 批次间休息
        await asyncio.sleep(1)

    # ========== 打印汇总 ==========
    print_summary(all_results)

    # 返回退出码
    failed_count = sum(1 for r in all_results if r.get("status") in ["FAIL", "ERROR"])
    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
