# Stealth-Browser 测试说明文档

## 1. 概述

本文档描述 Stealth-Browser 项目的测试架构、测试分类、运行指南和最佳实践，旨在指导后续单元测试开发。

### 1.1 测试状态

| 类别 | 目录/文件 | 测试数 | 状态 |
|------|----------|--------|------|
| 单元测试（核心） | `unit/test_config`, `unit/test_stealth`, `unit/test_daemon`, `unit/test_controller` | ~73 | ✅ 完成 |
| 单元测试（Pipeline v2.3） | `unit/test_classifier`, `unit/test_fallback`, `unit/test_debugger`, `unit/test_telemetry`, `unit/test_template_errors` | ~78 | ✅ 完成 |
| 单元测试（Explore） | `unit/test_explore_analysis`, `unit/test_explore_cascade`, `unit/test_explore_synthesizer` | ~30 | ✅ 完成 |
| 单元测试（Intervention） | `unit/test_detection`, `unit/test_cli_session_cache`, `unit/test_k8s_node_manager` | ~55 | ✅ 完成 |
| 集成测试 | `integration/` (8 files) | ~50 | ✅ 完成 |
| 中间件测试 | `stealth/test_stealth_middleware`, `stealth/test_stealth_profiles` | 41 | ✅ 完成 |
| 安全测试 | `unit/test_security_hardening`, `unit/test_auth_ownership` | ~20 | ✅ 完成 |
| 场景测试 | `scenarios/test_scenario_*.py` (7 files) | ~26 | ⚠️ 需真实浏览器 |
| 浏览器后端测试 | `browser/test_local_backend`, `browser/test_daemon`, `browser/test_anti_detection` | ~25 | ⚠️ 需 CDP 连接 |
| Skill 测试 | `skill/test_skill_facade`, `skill/test_deploy_wizard_complete` | ~50 | ✅ 完成 |
| E2E 测试 | `e2e/` (9+ files) | ~40+ | ⚠️ 需 API 服务或浏览器 |

**总计: ~1021 测试用例（含 E2E 和真实浏览器测试）**

---

## 2. 测试架构

### 2.1 目录结构

```
tests/
├── conftest.py                        # 全局 fixtures
├── helpers/
│   ├── __init__.py                    # 导出 load_skill_module, get_skill_classes
│   ├── cli_runner.py                  # CLIRunner (subprocess 执行)
│   ├── api_client.py                  # APIClient (httpx AsyncClient)
│   └── skill_loader.py               # 动态加载 stealth_browser 模块
│
├── unit/                              # ★ 单元测试（~31 文件，无需浏览器）
│   ├── test_config.py                 # 配置系统
│   ├── test_basic.py                  # 基础功能
│   ├── test_classifier.py             # 错误分类器
│   ├── test_fallback.py               # 自动恢复策略
│   ├── test_debugger.py               # 调试器
│   ├── test_telemetry.py              # 遥测统计
│   ├── test_template_errors.py        # 模板错误
│   ├── test_explore_*.py              # 探索模块（3 文件）
│   ├── test_security_hardening.py     # 安全加固
│   ├── test_auth_ownership.py         # 所有权授权
│   ├── test_adapter_validation.py    # 适配器校验
│   ├── test_controller.py             # 控制器
│   ├── test_deploy_config.py          # 部署配置
│   ├── test_profile_manager.py        # Profile 管理
│   ├── test_persistent_profile.py     # 持久化 Profile
│   ├── test_setup_integration.py      # 安装集成
│   ├── test_shell_scripts.py          # Shell 脚本
│   ├── test_skill_installation.py     # Skill 安装
│   ├── test_mode*.py                  # 模式矩阵（3 文件）
│   ├── test_docker_smoke.py           # Docker 冒烟
│   ├── test_distributed.py            # 分布式
│   ├── test_comprehensive.py          # 综合测试
│   ├── test_api.py                    # API 测试
│   └── test_zhipin*.py / test_xiaohongshu_scenarios.py  # 站点特定
│
├── stealth/                           # ★ 反检测层测试
│   ├── test_stealth.py                # StealthEnhancer（人类行为模拟）
│   ├── test_stealth_middleware.py     # StealthMiddleware（熔断器）
│   └── test_stealth_profiles.py      # StealthProfile 预设（22 tests）
│
├── browser/                            # ★ 浏览器后端测试（需 CDP）
│   ├── test_local_backend.py          # LocalCDPBackend
│   ├── test_daemon.py                 # BrowserDaemon
│   └── test_anti_detection.py         # 反检测验证
│
├── scenarios/                          # ★ 场景测试（需真实浏览器）
│   ├── test_scenario_1_cli_local_basic.py
│   ├── test_scenario_1_optimized.py
│   ├── test_scenario_2_cli_local_full_task.py
│   ├── test_scenario_3_api_local_agent.py
│   ├── test_scenario_4_cli_remote_gateway.py
│   ├── test_scenario_5_api_remote_gateway.py
│   ├── test_scenario_6_anti_detection.py
│   └── test_scenario_7_token_optimization.py
│
├── skill/                              # ★ Skill 层测试
│   ├── test_skill_facade.py           # Facade 路由
│   ├── test_skill_extension.py        # Extension popup + SKILL.md conformance (91 tests)
│   └── test_deploy_wizard_complete.py # 部署向导
│
├── integration/                        # ★ 集成测试套件（pytest-based）
│   ├── __init__.py
│   ├── conftest.py                    # 共享 fixtures (3 tiers: mock/browser/api)
│   ├── test_session_lifecycle.py      # 会话生命周期 CRUD
│   ├── test_pipeline_execution.py     # YAML pipeline 执行
│   ├── test_template_engine.py       # 模板引擎表达式边界测试
│   ├── test_adapter_loading.py       # 适配器发现 + 加载 + 校验
│   ├── test_stealth_integrity.py     # 隐匿完整性
│   ├── test_mode_matrix.py           # 8 种模式组合参数化测试
│   └── test_security_boundaries.py   # 安全边界
│
└── e2e/                               # E2E 测试（需 CloakBrowser 或 API 服务）
    ├── test_e2e_local_llm.py          # 本地模式 E2E
    ├── test_e2e_remote.py             # 远程 API 模式 E2E
    ├── test_e2e_pipeline.py           # Pipeline 真实 DOM
    ├── test_e2e_mode_matrix.py        # 模式矩阵
    ├── test_e2e_anti_detection.py     # 反检测验证
    └── ...
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
    "api: requires FastAPI server",
]
```

### 2.3 关键 Fixtures

| Fixture | Scope | 描述 |
|---------|-------|------|
| `mock_page` | function | Mock Playwright Page |
| `mock_context` | function | Mock BrowserContext |
| `mock_browser` | function | Mock Browser |
| `cleanup_sessions` | function | 测试后清理 sessions |
| `reset_global_state` | autouse | 重置模块级单例（config, daemon, loader registry） |
| `mock_backend` | function | ABC-level mock (spec=BrowserBackend) |
| `mock_page_handle` | function | ABC-level mock (spec=BrowserPageHandle) |

---

## 3. 测试分类详解

### 3.1 核心单元测试

#### 3.1.1 配置系统测试 (`test_config.py`)

- `TestSkillConfigDefaults` - 默认值验证
- `TestEnvOverrides` - 环境变量覆盖
- `TestYAMLOverrides` - YAML 配置覆盖
- `TestLoadConfigPriority` - 配置优先级链
- `TestCLIRemoteConstraint` - CLI/remote 约束

#### 3.1.2 StealthEnhancer 测试 (`test_stealth.py`)

- `TestPreActionDelays` - 操作前延迟（按类型差异化）
- `TestHumanType` - 人类打字模拟（50-250ms/字符, 5% typo）
- `TestRandomMouseMove` - 贝塞尔鼠标移动（20 步三次曲线）
- `TestHumanScroll` - 人类滚动行为（20% 回滚）
- `TestInjectTimingNoise` - 时间噪声注入（Date.now/performance.now）

#### 3.1.3 BrowserDaemon 测试 (`test_daemon.py`)

- `TestBrowserDaemonSingleton` - 单例模式
- `TestDaemonInitialState` - 初始状态
- `TestStatePersistence` - 状态持久化到 `~/.stealth-browser/daemon-state.json`
- `TestIdleMonitorControl` - 双条件空闲监控
- `TestSessionManagement` - 会话管理
- `TestDisconnect` / `TestShutdown` - 断开与清理

### 3.2 Pipeline 引擎测试 (v2.3)

#### 3.2.1 错误分类器 (`test_classifier.py`)

**ErrorCategory 枚举覆盖：**
- `SELECTOR_DRIFT` - 选择器漂移（元素存在但选择器失效）
- `TIMEOUT` - 操作超时
- `AUTH_FAILURE` - 认证失败（401/403）
- `NAVIGATION_ERROR` - 导航错误
- `EXTRACTION_ERROR` - 提取错误
- `UNKNOWN` - 未知错误

**测试要点：**
- 按异常类型精确匹配（`SelectorNotFoundError → SELECTOR_DRIFT`）
- 按消息内容启发式匹配（`401/403 → AUTH_FAILURE`，`timeout → TIMEOUT`）
- `category_description()` 返回面向用户的中文描述

#### 3.2.2 自动恢复策略 (`test_fallback.py`)

**per-category 恢复策略：**
- `SELECTOR_DRIFT` → re-snapshot 页面验证元素存在
- `TIMEOUT` → 增加超时后重试（1.5x 或默认 30s）
- `AUTH_FAILURE` → 标记 `_reauth_required`

**测试要点：**
- `_get_fallback_handler()` 动态解析支持 `unittest.mock.patch`
- 恢复成功返回 `FallbackResult.RECOVERED`
- 无法恢复抛出原始异常

#### 3.2.3 调试器 (`test_debugger.py`)

- `DebugSession` 创建与管理
- breakpoints 设置与触发
- step history 记录
- state inspection（变量/调用栈）
- 未知步骤自动跳过并记录错误（不崩溃）

#### 3.2.4 遥测统计 (`test_telemetry.py`)

- `record()` 写入 JSONL 格式
- `get_stats()` 全局和 per-adapter 聚合
- `get_recent()` 最近 N 条记录
- `clear()` 清空记录
- 非阻塞设计：telemetry 失败不影响 pipeline 执行

#### 3.2.5 模板引擎 (`test_template_errors.py`)

- 19 种过滤器正确性
- 算术表达式求值（含括号）
- 变量替换（`{{query}}`）
- 条件分支（`{% if %}`）
- 边界情况：空值、未定义变量、类型错误

### 3.3 StealthMiddleware 测试 (`test_stealth_middleware.py`)

**熔断器状态机：**
- CLOSED → 正常隐匿（failure_count < threshold）
- OPEN → 隐匿禁用（failure_count >= threshold）
- RESET → 新 session 重置

**操作分类：**
- stealth-wrapped: goto, click, fill, scroll（有 pre/post 延迟）
- passthrough: evaluate, title, url（零开销透传）

**关键验证点：**
- per-session 隔离（一个 session 的熔断不影响其他 session）
- 自动降级：连续失败后切换为透传模式
- 自动恢复：新 session 从 CLOSED 开始

### 3.4 探索模块测试

| 文件 | 测试内容 |
|------|---------|
| `test_explore_analysis.py` | DOM 结构分析、交互元素识别、表单检测 |
| `test_explore_cascade.py` | CSS 选择器生成、级联规则、唯一性保证 |
| `test_explore_synthesizer.py` | YAML 适配器合成、步骤推断、模板填充 |

### 3.5 集成测试套件 (`integration/`)

**3 层测试体系：**

| Tier | Marker | 前置条件 | 耗时 |
|------|--------|----------|------|
| **1: Mock** | (无) | 无 | ~1s |
| **2: Real Browser** | `@requires_browser` | CloakBrowser :19222 | ~10s |
| **3: API Server** | `@api` | FastAPI :8000 | ~5s |

**8 个集成测试文件：**

| 文件 | Tier | 内容 |
|------|------|------|
| `test_session_lifecycle.py` | 1-2 | create → navigate → snapshot → delete 完整生命周期 |
| `test_pipeline_execution.py` | 1-2 | YAML pipeline 执行 + SSRF 防护 + 数据转换 |
| `test_template_engine.py` | 1 | 表达式引擎边界测试 |
| `test_adapter_loading.py` | 1 | 适配器发现 + OpenCLI 兼容 + validator 校验 |
| `test_stealth_integrity.py` | 1-2 | 隐匿层结构完整性 + 熔断器 + 行为一致性 |
| `test_mode_matrix.py` | 1 | 8 种模式组合参数化（local×llm, local×agent, extension×llm, ...） |
| `test_security_boundaries.py` | 1-2 | Session 隔离 + 注入防护 + JS 阻断 |
| `test_skill_scenarios.py` | 1-2 | Skill 级别端到端场景 |

### 3.6 安全测试

| 文件 | 测试内容 |
|------|---------|
| `test_security_hardening.py` | 11 类安全漏洞修复验证（SSRF/XSS/注入/IDOR 等） |
| `test_auth_ownership.py` | API Key 所有权验证 + Session 隔离 |

### 3.7 场景测试 (`test_scenario_*.py`)

需要真实浏览器的 7 个场景：

| 场景 | 文件 | 内容 | 前置条件 |
|------|------|------|---------|
| 1 | `test_scenario_1_cli_local_basic.py` | CLI 基本原子操作 | CloakBrowser |
| 2 | `test_scenario_2_cli_local_full_task.py` | CLI 完整任务流程 | CloakBrowser |
| 3 | `test_scenario_3_api_local_agent.py` | API Agent 自主执行 | FastAPI |
| 4 | `test_scenario_4_cli_remote_gateway.py` | CLI 远程网关 | Gateway |
| 5 | `test_scenario_5_api_remote_gateway.py` | API 远程网关 | Gateway |
| 6 | `test_scenario_6_anti_detection.py` | 反检测能力验证 | CloakBrowser |
| 7 | `test_scenario_7_token_optimization.py` | Token 优化验证 | CloakBrowser/FastAPI |

---

## 4. 运行指南

### 4.1 快速命令

```bash
# === 核心单元测试（无需浏览器，秒级） ===
pytest tests/unit/test_config.py tests/stealth/test_stealth.py tests/browser/test_daemon.py \
       tests/unit/test_controller.py tests/unit/test_adapter_validation.py -v

# === Pipeline 引擎测试（无需浏览器） ===
pytest tests/unit/test_classifier.py tests/unit/test_fallback.py tests/unit/test_debugger.py \
       tests/unit/test_telemetry.py tests/unit/test_template_errors.py -v

# === 探索模块测试（无需浏览器） ===
pytest tests/unit/test_explore_analysis.py tests/unit/test_explore_cascade.py \
       tests/unit/test_explore_synthesizer.py -v

# === StealthMiddleware 测试（无需浏览器） ===
pytest tests/stealth/test_stealth_middleware.py -v

# === 安全测试（无需浏览器） ===
pytest tests/unit/test_security_hardening.py tests/unit/test_auth_ownership.py -v

# === 集成测试（Tier 1: Mock，无需服务） ===
pytest tests/integration/ -m "not slow and not api and not llm" -v

# === 集成测试（Tier 1-2: 含浏览器） ===
pytest tests/integration/ -m "not llm" -v

# === 反检测验证（需 CloakBrowser） ===
pytest tests/browser/test_anti_detection.py -v

# === 场景测试（需真实浏览器） ===
pytest tests/scenarios/ -v
```

### 4.2 完整测试套件

```bash
# 所有非场景测试（排除慢测试和需要真实服务的测试）
pytest tests/ -v --ignore=tests/e2e -m "not slow and not manual" \
       --ignore=tests/test_scenario_*.py

# 包含集成测试（需 CloakBrowser）
pytest tests/ -v -m "not slow and not manual" \
       --ignore=tests/e2e --ignore=tests/test_scenario_*.py

# 全量测试（需 CloakBrowser + FastAPI，~30min+）
pytest tests/ -v
```

### 4.3 按模块运行

```bash
# 仅中间件
pytest tests/stealth/test_stealth_middleware.py -v

# 仅 Pipeline 引擎
pytest tests/unit/test_classifier.py tests/unit/test_fallback.py tests/unit/test_debugger.py \
       tests/unit/test_telemetry.py -v

# 仅探索模块
pytest tests/unit/test_explore_*.py -v

# 仅安全测试
pytest tests/unit/test_security_hardening.py tests/unit/test_auth_ownership.py -v

# 仅集成测试
pytest tests/integration/ -v
```

### 4.4 环境准备

```bash
# 1. 激活虚拟环境
source .venv/bin/activate

# 2. 启动 CloakBrowser (集成/E2E/场景测试需要)
python -m cloakbrowser --remote-debugging-port=19222 --user-data-dir=/tmp/cb-test &

# 3. 验证 CDP
curl http://127.0.0.1:19222/json/version

# 4. (可选) 启动 FastAPI (远程/API 模式测试)
python -m uvicorn stealth_browser.api:app --host 127.0.0.1 --port 8000 &
```

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
        return {"key": "value"}

    @pytest.mark.asyncio
    async def test_my_feature(self, my_fixture):
        # Arrange
        data = my_fixture
        # Act
        result = await some_async_operation(data)
        # Assert
        assert result["status"] == "success"
```

### 5.2 Pipeline 测试模板

```python
class TestPipelineStep:
    """Pipeline 步骤测试"""

    @pytest.mark.asyncio
    async def test_step_success(self, mock_page_handle):
        """正常执行路径"""
        handle = mock_page_handle
        handle.goto.return_value = None
        handle.snapshot.return_value = {"elements": []}

        result = await execute_step(handle, {"action": "navigate", "url": "https://example.com"})
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_step_with_fallback(self, mock_page_handle):
        """失败 + fallback 恢复"""
        handle = mock_page_handle
        handle.goto.side_effect = SelectorNotFoundError("div.missing")

        result = await execute_step(handle, {...}, fail_fast=False)
        assert result["status"] == "recovered"
```

### 5.3 命名约定

| 类型 | 约定 | 示例 |
|------|------|------|
| 测试文件 | `test_<feature>.py` | `test_config.py`, `test_classifier.py` |
| 测试类 | `Test<Feature>` | `TestSkillConfig`, `TestErrorClassifier` |
| 测试方法 | `test_<scenario>` | `test_env_overrides`, `test_selector_drift_recovery` |
| Fixture | 描述性名称 | `mock_page`, `cleanup_sessions`, `reset_global_state` |

### 5.4 动态模块加载

```python
# 由于 stealth-browser 包名含连字符，需要动态加载
from helpers.skill_loader import load_skill_module

config = load_skill_module("config")
stealth = load_skill_module("stealth")
daemon = load_skill_module("daemon")
classifier = load_skill_module("pipeline.classifier")
```

### 5.5 全局状态重置（重要）

集成测试的 `conftest.py` 使用 `autouse` fixture 重置模块级单例：

```python
@pytest.fixture(autouse=True)
async def reset_global_state():
    """每个测试前重置全局状态"""
    from stealth_browser import main
    from stealth_browser.browser import daemon
    from stealth_browser.adapters import loader
    main._config = None
    main._middleware = None
    main._middleware_lock = asyncio.Lock()
    daemon.BrowserDaemon._instance = None
    loader._registry.clear()
```

---

## 6. 关键文件参考

| 文件 | 用途 | 关键类/函数 |
|------|------|-----------|
| `stealth_browser/config.py` | 配置系统 | `SkillConfig`, `load_config`, `detect_mode` |
| `stealth_browser/stealth/enhancer.py` | 隐匿增强（第6层） | `StealthEnhancer` |
| `stealth_browser/browser/daemon.py` | 浏览器守护 | `BrowserDaemon` |
| `stealth_browser/stealth/middleware.py` | 集中隐匿层（第7层） | `StealthMiddleware`, `_PerSessionCircuit` |
| `stealth_browser/browser/local.py` | 本地后端 | `LocalCDPBackend` |
| `stealth_browser/browser/remote.py` | 远程后端 | `RemoteAPIBackend` |
| `stealth_browser/browser/extension.py` | Chrome 扩展后端 | `ExtensionBackend` |
| `stealth_browser/pipeline/classifier.py` | 错误分类 | `ErrorCategory`, `classify_error` |
| `stealth_browser/pipeline/fallback.py` | 自动恢复 | `attempt_fallback`, `FallbackResult` |
| `stealth_browser/pipeline/debugger.py` | 调试器 | `DebugSession`, `debug_pipeline` |
| `stealth_browser/pipeline/telemetry.py` | 遥测 | `record`, `get_stats`, `clear` |
| `stealth_browser/pipeline/errors.py` | 类型化错误 | `PipelineError` 层次 |
| `stealth_browser/pipeline/executor.py` | 执行器入口 | `execute_pipeline` |
| `stealth_browser/explore/explorer.py` | 站点探索 | `explore_site` |
| `stealth_browser/adapters/validator.py` | 适配器校验 | `validate_adapter` |
| `stealth_browser/api.py` | FastAPI 端点 | 原子操作端点 |

---

## 7. 验证检查清单

### 7.1 功能验证

- [x] local llm 模式原子操作
- [x] local agent 模式任务执行
- [x] extension 模式 Chrome 连接
- [x] remote llm 模式原子操作 (需 API)
- [x] remote agent 模式任务执行 (需 API)
- [x] Pipeline YAML 适配器执行
- [x] 错误分类 + 自动恢复
- [x] 调试器单步执行
- [x] 站点探索 + 适配器合成

### 7.2 性能验证

- [x] Session 创建 < 3s
- [x] DOM Snapshot < 500ms
- [x] 点击/填充 < 1s
- [x] 5 并发 sessions 成功
- [x] Pipeline 执行无内存泄漏

### 7.3 反检测验证

- [x] `navigator.webdriver === false`
- [x] `__playwright__binding__ === undefined`
- [x] 无 `cdc_*` 变量
- [x] StealthMiddleware 熔断器 per-session 隔离
- [x] bot.sannysoft.com 得分 > 85

### 7.4 安全验证

- [x] API Key 认证有效
- [x] Session 所有权隔离
- [x] SSRF 防护（内网地址拦截）
- [x] XSS 防护（json.dumps 序列化）
- [x] CSS 选择器注入防护

### 7.5 Token 优化验证

- [x] DOM 压缩率 > 50%
- [x] Snapshot Token 估算有基准
- [x] 交互元素选择性提取

### 3.8 Real Browser Integration Tests (v2) — NEW

> **新增于 2026-04-05** | 替代 mock-only 集成测试，使用真实 CloakBrowser 验证完整栈

#### 3.8.1 概述

| 文件 | 测试数 | Marker | 描述 |
|------|--------|--------|------|
| `e2e/test_e2e_anti_detection.py` | ~12 | `requires_browser`, `manual` | 5 站点反检测 + Boss Zhipin + 差分测试 + scorecard |
| `e2e/test_e2e_pipeline.py` | 8 | `requires_browser` | Pipeline 真实 DOM 执行（导航/表单/滚动/错误/模板/遥测） |
| `e2e/test_e2e_mode_matrix.py` | 8 | `requires_browser` | 4 个真实模式组合 + 回退验证 + Docker 行为 |

**总计: ~28 个真实浏览器测试**（从原计划 50 个精简，去重后）

#### 3.8.2 Canary Sites（5 个检测向量）

| # | 站点 | 检测向量 | 风险等级 |
|---|------|---------|---------|
| 1 | `bot.sannysoft.com` | JS 属性：webdriver, chrome.runtime, permissions | 低（稳定） |
| 2 | `fingerprintjs.com/demo` | Canvas 指纹一致性 | 低（稳定） |
| 3 | `nowsecure.nl` | 行为分析信号、HeadlessChrome UA | 低（稳定） |
| 4 | Cloudflare 站点 | JS Challenge 处理能力 | 中（可能变化） |
| 5 | **Boss Zhipin (招聘)** | 生产目标：QR 登录页正常渲染 vs 白屏/跳转 | **高 (@pytest.mark.manual)** |

#### 3.8.3 测试结果分类

| 状态 | 含义 | 行为 |
|------|------|------|
| `PASS` | 完全通过 | 绿色 ✅ |
| `FAIL` | 代码 bug | 红色 ❌，需修复 |
| `DETECTED` | 被站点检测到自动化 | 黄色 ⚠️，记录诊断信息 |
| `BLOCKED` | 基础设施缺失 | 跳过（CloakBrowser 未安装等） |
| `FLAKY` | 间歇性失败 | 记录但不阻塞 |

#### 3.8.4 运行方式

```bash
# === 所有真实浏览器测试（有头模式，可看到浏览器窗口） ===
# 前置：确保 CloakBrowser 已安装（pip install cloakbrowser）
pytest tests/e2e/ -m requires_browser --headed -v

# === 仅反检测测试（最高优先级）===
pytest tests/e2e/test_e2e_anti_detection.py -m requires_browser --headed -v

# === 仅 Pipeline 测试 ===
pytest tests/e2e/test_e2e_pipeline.py -m requires_browser --headed -v

# === 仅模式矩阵测试 ===
pytest tests/e2e/test_e2e_mode_matrix.py -m requires_browser --headed -v

# === Headless 模式（CI/nightly，无显示器）===
pytest tests/e2e/ -m requires_browser --headless -v

# === 跳过 manual 标记的测试（Boss Zhipin 等）===
pytest tests/e2e/ -m requires_browser --headed -v -m "not manual"

# === 带 Docker Remote 测试（需要 docker compose up）===
RUN_DOCKER_TESTS=1 pytest tests/e2e/test_e2e_mode_matrix.py -m requires_browser --headed -v
```

#### 3.8.5 输出产物

每次运行生成：

```
tests/screenshots/
  └── 20260405-210255-zhipin-render.png      # Zhipin 渲染截图
  └── 20260405-210300-sannysoft.png          # sannysoft 检测截图
  └── ...                                      # 每个关键测试一张

tests/results/
  └── scorecard-20260405-210300.json             # JSON 格式评分卡
      {
        "timestamp": "...",
        "total": 12,
        "passed": 10,
        "detected": 1,
        "blocked": 0,
        "results": [...]
      }
```

**注意**: `tests/screenshots/` 和 `tests/results/` 在 `.gitignore` 中（不提交 PII 到 git）。

#### 3.8.6 故障排除

| 问题 | 原因 | 解决方案 |
|------|------|---------|
| All e2e tests skipped | CloakBrowser 未安装 / 端口 19222 被占 | `pip install cloakbrowser` 或关闭占用端口的进程 |
| Boss Zhipin 白屏 | IP 被封 / 检测逻辑更新 | 查看 screenshot 确认是白屏还是 captcha；换 IP 或代理 |
| TimeoutError | 网络慢 / WAF 拦截 | 测试已内置指数退避让 (30s→60s→120s) |
| Docker tests skipped | FastAPI Gateway 未运行 | 先 `docker compose up -d` 再运行 |

---

**文档版本**: v3.2
**创建日期**: 2026-04-04
**更新日期**: 2026-04-16 (新增 intervention detection + K8s lifecycle + CLI cache tests)
