# Agent-Browser 测试说明文档

## 1. 概述

本文档描述 Agent-Browser 项目的测试架构、测试分类、运行指南和最佳实践，旨在指导后续单元测试开发。

### 1.1 测试状态

| Phase | 类别 | 测试文件 | 测试数 | 状态 |
|-------|------|---------|--------|------|
| 1 | 单元测试 | `test_config.py`, `test_stealth.py`, `test_daemon.py` | 73 | ✅ 完成 |
| 2 | 集成测试 | `test_local_backend.py` | 16 | ✅ 完成 |
| 3 | E2E 本地 | `e2e/test_e2e_local_llm.py` | 15 | ✅ 完成 |
| 4 | E2E 远程 | `e2e/test_e2e_remote.py` | 20 | ✅ 完成 |
| 5 | 反检测验证 | `verify_antidetection_stack.py` | 16 | ✅ 完成 |
| 6 | 性能基准 | `benchmark_performance.py` | 12 | ✅ 完成 |

**总计: 152 测试用例**

---

## 2. 测试架构

### 2.1 目录结构

```
tests/
├── conftest.py                    # 共享 fixtures
├── helpers/
│   ├── __init__.py                # 导出 load_skill_module, get_skill_classes
│   ├── cli_runner.py              # CLIRunner (subprocess 执行)
│   ├── api_client.py              # APIClient (httpx AsyncClient)
│   └── skill_loader.py            # 动态加载 skills/agent-browser
├── e2e/
│   ├── test_e2e_local_llm.py      # 本地模式 E2E
│   └── test_e2e_remote.py          # 远程 API 模式 E2E
├── test_config.py                  # Phase 1: 配置单元测试
├── test_stealth.py                 # Phase 1: StealthEnhancer 单元测试
├── test_daemon.py                  # Phase 1: BrowserDaemon 单元测试
├── test_local_backend.py           # Phase 2: LocalCDPBackend 集成
├── verify_antidetection_stack.py   # Phase 5: 反检测验证
└── benchmark_performance.py        # Phase 6: 性能基准
```

### 2.2 Pytest 配置

```toml
# pyproject.toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
markers = [
    "integration: requires running services",
    "manual: requires human interaction",
    "slow: takes more than 10 seconds",
    "requires_browser: requires CloakBrowser instance",
]
```

### 2.3 关键 Fixtures

| Fixture | Scope | 描述 |
|---------|-------|------|
| `mock_page` | function | Mock Playwright Page |
| `mock_context` | function | Mock BrowserContext |
| `mock_browser` | function | Mock Browser |
| `cleanup_sessions` | function | 测试后清理 sessions |

---

## 3. 测试分类详解

### 3.1 Phase 1: 单元测试

#### 3.1.1 配置系统测试 (`test_config.py`)

**测试类**:
- `TestSkillConfigDefaults` - 默认值验证
- `TestEnvOverrides` - 环境变量覆盖
- `TestYAMLOverrides` - YAML 配置覆盖
- `TestLoadConfigPriority` - 配置优先级链
- `TestCLIRemoteConstraint` - CLI/remote 约束

**关键验证点**:
- 默认 `calling_mode="cli"`, `browser_mode="local"`
- 环境变量 `AGENT_BROWSER_*` 正确覆盖
- YAML 配置从 `~/.agent-browser/config.yaml` 加载
- 优先级: 显式参数 > 环境变量 > YAML > 默认

#### 3.1.2 StealthEnhancer 测试 (`test_stealth.py`)

**测试类**:
- `TestPreActionDelays` - 操作前延迟
- `TestHumanType` - 人类打字模拟
- `TestRandomMouseMove` - 贝塞尔鼠标移动
- `TestHumanScroll` - 人类滚动行为
- `TestInjectTimingNoise` - 时间噪声注入
- `TestWarmupBrowsing` - 预热浏览
- `TestReadingPause` - 阅读停顿

**关键验证点**:
- `pre_action("navigate")`: 0.5-1.5s 延迟
- `pre_action("click")`: 0.1-0.3s 延迟
- `human_type()`: 50-250ms/字符, 5% typo 概率
- `random_mouse_move()`: 20 步贝塞尔曲线
- `human_scroll()`: 20% 回滚概率

#### 3.1.3 BrowserDaemon 测试 (`test_daemon.py`)

**测试类**:
- `TestBrowserDaemonSingleton` - 单例模式
- `TestDaemonInitialState` - 初始状态
- `TestStatePersistence` - 状态持久化
- `TestIdleMonitorControl` - 空闲监控控制
- `TestSessionManagement` - 会话管理
- `TestDisconnect` - 断开连接
- `TestShutdown` - 关闭清理

**关键验证点**:
- 单例模式: `reset()` 后创建新实例
- 状态持久化: `~/.agent-browser/daemon-state.json`
- 双条件断开: 无 session + 超时
- 空闲监控: `start_idle_monitor()`, `stop_idle_monitor()`

### 3.2 Phase 2: 集成测试

#### 3.2.1 LocalCDPBackend 测试 (`test_local_backend.py`)

**前置条件**: CloakBrowser 运行在 `127.0.0.1:19222`

**测试类**:
- `TestCloakBrowserConnection` - CDP 连接
- `TestAntiDetection` - 反检测验证
- `TestPageNavigation` - 页面导航
- `TestDOMSnapshot` - DOM 快照
- `TestClickOperation` - 点击操作
- `TestFillOperation` - 填充操作
- `TestConcurrentOperations` - 并发操作
- `TestErrorHandling` - 错误处理

**关键验证点**:
- `navigator.webdriver === false/undefined`
- `window.__playwright__binding__ === undefined`
- 无 `cdc_*` 变量
- DOM Snapshot 返回 `@e0, @e1...` refs

### 3.3 Phase 3-4: E2E 测试

#### 3.3.1 本地模式 (`e2e/test_e2e_local_llm.py`)

**测试类**:
- `TestE2ELocalLLMMode` - 本地 LLM 模式
- `TestE2ELocalAgentMode` - 本地 Agent 模式
- `TestE2EAdapterZeroToken` - Adapter 零 Token
- `TestE2EExploreAdaptive` - 自适应探索
- `TestE2ESessionPersistence` - 会话持久化
- `TestE2EStealthVerification` - 隐匿性验证

**关键验证点**:
- 页面打开、快照、点击、填充流程
- Agent 任务执行 (`run_task`)
- Session 隔离和 Cookie 持久化
- Bot 检测评分

#### 3.3.2 远程模式 (`e2e/test_e2e_remote.py`)

**前置条件**: FastAPI 运行在 `localhost:8000`

**测试类**:
- `TestRemoteAPIHealth` - API 健康检查
- `TestRemoteSessionManagement` - Session CRUD
- `TestRemotePageNavigation` - 页面导航
- `TestRemoteDOMSnapshot` - DOM 快照
- `TestRemoteClickFill` - 点击/填充
- `TestRemoteScroll` - 滚动
- `TestRemoteEvaluate` - JS 执行
- `TestRemoteAgentMode` - Agent 模式
- `TestRemoteAntiDetection` - 反检测

### 3.4 Phase 5: 反检测验证 (`verify_antidetection_stack.py`)

**6 层反检测栈**:

| Layer | 组件 | 验证方法 |
|-------|------|---------|
| 1 | CloakBrowser | `navigator.webdriver === false` |
| 2 | patchright | `__playwright__binding__ === undefined` |
| 3 | rebrowser-patches | 无 `cdc_*` 变量 |
| 4 | 非标准端口 | 端口 19222 |
| 5 | 持久 CDP | BrowserDaemon 会话复用 |
| 6 | StealthEnhancer | 延迟/行为模拟 |

**外部检测服务**:
- bot.sannysoft.com - 目标 90+ 分
- Canvas 指纹一致性
- WebGL 支持

### 3.5 Phase 6: 性能基准 (`benchmark_performance.py`)

**基准指标**:

| 指标 | 目标 | 测试类 |
|------|------|--------|
| Session 创建 | < 3s | `TestLatencyBenchmark` |
| 页面导航 | < 3s | `TestLatencyBenchmark` |
| DOM Snapshot | < 500ms | `TestLatencyBenchmark` |
| 点击延迟 | < 1s | `TestLatencyBenchmark` |
| 并发 sessions | 5+ 成功 | `TestConcurrencyBenchmark` |
| DOM 压缩率 | > 50% | `TestDOMCompression` |
| Token 估算 | 有基准 | `TestTokenBaseline` |
| 长时间稳定 | 20 次操作 | `TestResourceUsage` |

---

## 4. 运行指南

### 4.1 环境准备

```bash
# 1. 激活虚拟环境
cd /Users/galen/Library/Mobile\ Documents/com~apple~CloudDocs/skills/agent-browser
source .venv/bin/activate

# 2. 启动 CloakBrowser (集成/E2E 测试需要)
python -m cloakbrowser --remote-debugging-port=19222 --user-data-dir=/tmp/cb-test &

# 3. 验证 CDP
curl http://127.0.0.1:19222/json/version

# 4. (可选) 启动 FastAPI (远程模式测试)
cd src && PYTHONPATH="." python -m uvicorn api:app --host 127.0.0.1 --port 8000 &
```

### 4.2 运行命令

```bash
# 运行所有本地测试 (不需要 API)
pytest tests/test_config.py tests/test_stealth.py tests/test_daemon.py \
       tests/test_local_backend.py tests/e2e/test_e2e_local_llm.py \
       tests/verify_antidetection_stack.py tests/benchmark_performance.py -v

# 运行特定 Phase
pytest tests/test_config.py -v                              # Phase 1: 配置
pytest tests/test_stealth.py -v                              # Phase 1: Stealth
pytest tests/test_daemon.py -v                               # Phase 1: Daemon
pytest tests/test_local_backend.py -v                        # Phase 2: 集成
pytest tests/e2e/test_e2e_local_llm.py -v                    # Phase 3: E2E 本地
pytest tests/verify_antidetection_stack.py -v                 # Phase 5: 反检测
pytest tests/benchmark_performance.py -v                      # Phase 6: 性能

# 运行远程测试 (需要 FastAPI)
pytest tests/e2e/test_e2e_remote.py -v

# 排除慢测试
pytest tests/ -v -m "not slow and not manual"
```

### 4.3 常见问题排查

| 问题 | 原因 | 解决方案 |
|------|------|---------|
| `ModuleNotFoundError: No module named 'agent_browser'` | 包名含连字符 | 使用 `helpers/skill_loader.py` |
| `TimeoutError` | 操作超时 | 增加 `aiohttp.ClientTimeout(total=120)` |
| `Connection refused` | CloakBrowser 未运行 | 启动浏览器 `python -m cloakbrowser ...` |
| `navigator.webdriver = true` | 反检测失效 | 检查 CloakBrowser 版本 |
| `SSL certificate error` | HTTPS 证书问题 | 使用 `ignore_https_errors=True` |

---

## 5. 编写新测试指南

### 5.1 测试模板

```python
"""
测试模块描述
"""
import pytest
from unittest import mock

# 对于需要动态加载的模块
from helpers.skill_loader import load_skill_module

class TestMyFeature:
    """功能测试类"""

    @pytest.fixture
    def my_fixture(self):
        """测试 fixture"""
        return {"key": "value"}

    @pytest.mark.asyncio
    async def test_my_feature(self, my_fixture):
        """测试用例描述"""
        # Arrange
        data = my_fixture

        # Act
        result = await some_async_operation(data)

        # Assert
        assert result["status"] == "success"
```

### 5.2 命名约定

| 类型 | 约定 | 示例 |
|------|------|------|
| 测试文件 | `test_<feature>.py` | `test_config.py` |
| 测试类 | `Test<Feature>` | `TestSkillConfig` |
| 测试方法 | `test_<scenario>` | `test_env_overrides` |
| Fixture | 描述性名称 | `mock_page`, `cleanup_sessions` |

### 5.3 Mock 使用

```python
from unittest import mock

# 同步 Mock
mock_obj = mock.MagicMock()
mock_obj.method.return_value = "result"

# 异步 Mock
async_mock = mock.AsyncMock()
async_mock.method.return_value = "async_result"

# Patch
with mock.patch('module.Class') as MockClass:
    instance = MockClass.return_value
    instance.method.assert_called_once()
```

### 5.4 动态模块加载

```python
# 由于 agent-browser 包名含连字符，需要动态加载
from helpers.skill_loader import load_skill_module

# 加载模块
config = load_skill_module("config")
stealth = load_skill_module("stealth")
daemon = load_skill_module("daemon")

# 使用
enhancer = stealth.StealthEnhancer()
```

---

## 6. 关键文件参考

| 文件 | 用途 | 关键类/函数 |
|------|------|-----------|
| `skills/agent-browser/config.py` | 配置系统 | `SkillConfig`, `load_config` |
| `skills/agent-browser/stealth.py` | 隐匿增强 | `StealthEnhancer` |
| `skills/agent-browser/daemon.py` | 浏览器守护 | `BrowserDaemon` |
| `skills/agent-browser/backends/local.py` | 本地后端 | `LocalCDPBackend` |
| `skills/agent-browser/backends/remote.py` | 远程后端 | `RemoteAPIBackend` |
| `src/api.py` | FastAPI 端点 | 原子操作端点 |

---

## 7. 验证检查清单

### 7.1 功能验证

- [x] local llm 模式原子操作
- [x] local agent 模式任务执行
- [x] remote llm 模式原子操作 (需 API)
- [x] remote agent 模式任务执行 (需 API)

### 7.2 性能验证

- [x] Session 创建 < 3s
- [x] DOM Snapshot < 500ms
- [x] 点击/填充 < 1s
- [x] 5 并发 sessions 成功

### 7.3 反检测验证

- [x] `navigator.webdriver === false`
- [x] `__playwright__binding__ === undefined`
- [x] 无 `cdc_*` 变量
- [x] bot.sannysoft.com 得分 > 85

### 7.4 Token 优化验证

- [x] DOM 压缩率 > 50%
- [x] Snapshot Token 估算有基准

---

**文档版本**: v2.0 (added integration test suite)
**创建日期**: 2026-04-04
**更新日期**: 2026-04-05 (新增 pytest 集成测试套件)

---

## A. Integration Test Suite (pytest-based) — NEW

Replaces legacy `test_skill_scenarios.py` (662-line monolithic script).

### File Structure

```
tests/integration/
  __init__.py                    # Package marker
  conftest.py                    # Shared fixtures (autouse reset + 3 tiers)
  test_session_lifecycle.py      # [CORE] create -> navigate -> snapshot -> delete
  test_pipeline_execution.py     # YAML pipeline + data transform + SSRF
  test_template_engine.py        # ${{ }} expression engine edge cases
  test_adapter_loading.py        # Discovery + OpenCLI normalization + validation
  test_stealth_integrity.py      # Structural + circuit breaker + behavioral
  test_mode_matrix.py            # 8 mode combos (parametrize + skipif)
  test_security_boundaries.py    # Isolation, injection vectors, JS blocking
```

### Test Tiers

| Tier | Marker | Prerequisite | Time |
|------|--------|-------------|------|
| **1: Mock** | (none) | Nothing | ~1s |
| **2: Real Browser** | `@requires_browser` | CloakBrowser :19222 | ~10s |
| **3: API Server** | `@api` | FastAPI :8000 | ~5s |

### Run Commands

```bash
# Fast tier (CI, mocked backend) — < 45s
pytest tests/integration/ -m "not slow and not api and not llm" -v

# With real browser — < 3min
pytest tests/integration/ -m "not llm" -v

# Full suite
pytest tests/integration/ -v

# By file
pytest tests/integration/test_session_lifecycle.py -v
pytest tests/integration/test_template_engine.py -v
```

### Key Fixtures

| Fixture | Description |
|---------|-----------|
| `reset_global_state` (autouse) | Resets _config, _middleware, BrowserDaemon, loader._registry every test |
| `mock_backend` | ABC-level mock (spec=BrowserBackend), no CDP needed |
| `mock_page_handle` | ABC-level mock (spec=BrowserPageHandle), all methods AsyncMock'd |
| `skill_config_no_stealth` | SkillConfig with stealth_enabled=False |
| `real_cdp_url` / `api_server_url` | Auto-skips if service unavailable |

### Global State Reset (Critical)

Module-level singletons reset by autouse fixture:
1. `main.py`: `_config`, `_middleware`, `_middleware_lock`
2. `daemon.py`: `BrowserDaemon` singleton
3. `adapters/loader.py`: `_registry` dict

NOTE: `steps.STEPS` is NOT cleared (populated at import time by `@register`).
