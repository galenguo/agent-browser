# Agent Browser - Claude Code 开发指南

## 项目概述

Agent Browser 是一个 AI 驱动的反检测浏览器自动化平台，专为高防护网站设计。它结合了浏览器自动化与 AI 代理，实现智能的网页交互，同时规避检测系统。

**核心能力：**
- 工业级反检测（7层防护栈 + StealthMiddleware 熔断器）
- Pipeline 引擎 v2.3（YAML 适配器 + 错误分类 + 自动恢复 + 调试器 + 遥测）
- 站点探索模块（自动分析 DOM + 生成适配器）
- 多模式支持（CLI/API × LLM/Agent × Local/Extension/Remote）
- 多账号隔离（独立指纹、Cookie、代理）
- 灵活的部署模式（本地/Docker/分布式）

**典型应用场景：**
- 高防护网站数据采集（Boss直聘、淘宝、知乎、B站等）
- AI Agent 驱动的浏览器自动化
- Chrome Extension 自动化（继承用户登录状态）
- 反爬虫系统测试与评估

## 架构设计

### 7层反检测栈

| 层级 | 组件 | 功能 |
|------|------|------|
| 1 | CloakBrowser | C++ 编译级指纹伪装（33处补丁） |
| 2 | patchright | 驱动级 CDP 补丁（移除 `__playwright__binding__`） |
| 3 | rebrowser-patches | Runtime.Enable 泄漏修复（addBinding 模式） |
| 4 | 非标准端口 19222 | 绑定 127.0.0.1 混淆连接 |
| 5 | 持久化 CDP 会话 | BrowserDaemon 防止频繁 attach/detach |
| 6 | StealthEnhancer | 人类延迟 + 贝塞尔鼠标 + 逐字输入 |
| 7 | **StealthMiddleware** | **集中隐匿层：自动 pre/post 延迟 + 熔断器** |

### 三层架构

```
┌─────────────────────────────────────────────────────────────┐
│                     SKILL.md (facade)                        │
│          模式检测 + ReAct/Agent 路由                          │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                     main.py (API)                            │
│     _ensure_backend() 路由 + run_task() 智能模式             │
└─────────────┬───────────────────────┬───────────────────────┘
              │                       │
┌─────────────▼─────────┐ ┌──────────▼─────────┐ ┌────────────▼────────────┐
│   LocalCDPBackend     │ │  ExtensionBackend   │ │  RemoteAPIBackend       │
│   (CloakBrowser)      │ │  (Chrome Extension) │ │  (HTTP 传输适配器)       │
│  ├─ BrowserDaemon     │ │  ├─ WebSocket       │ │  ├─ aiohttp REST        │
│  ├─ StealthEnhancer   │ │  ├─ chrome.debugger│ │  ├─ X-API-Key 认证      │
│  └─ browser-use Agent │ │  └─ 自然指纹继承    │ │  └─ session_id 映射      │
└─────────────┬─────────┘ └──────────┬─────────┘ └────────────┬────────────┘
              │                      │                      │
              └──────────────────────┼──────────────────────┘
                                     │
┌────────────────────────────────────▼────────────────────────────────────┐
│                    StealthMiddleware (src/stealth/middleware.py)         │
│     pre/post 延迟 + 贝塞尔鼠标 + 人类打字 + 熔断器 (per-session)         │
└────────────────────────────────────────┬───────────────────────────────┘
                                     │
              ┌──────────────────────┼──────────────────────┐
              │                      │                      │
   ┌──────────▼──┐         ┌────────▼────────┐    ┌───────▼──────────┐
   │ BrowserDaemon│         │ Pipeline Engine  │    │ Explore Module   │
   │ (持久化连接) │         │ (v2.3)           │    │ (站点探索+生成)   │
   └─────────────┘         │ ├─ classifier    │    └──────────────────┘
                           │ ├─ fallback      │
                           │ ├─ debugger      │
                           │ └─ telemetry     │
                           └─────────────────┘
```

**核心设计原则：**
- **LocalCDPBackend 是唯一浏览器操作核心**：所有浏览器逻辑只实现一次
- **ExtensionBackend 是自然指纹替代方案**：操作用户真实 Chrome，无 Extension 时自动回退
- **RemoteAPIBackend 是 HTTP 传输层**：零业务逻辑，只做序列化/反序列化
- **StealthMiddleware 是集中隐匿层**：自动包装所有操作，熔断器防止级联失败
- **用户隔离**：每个用户独立的 session、profile、cookies、fingerprint
- **持久化会话**：BrowserDaemon 单例保持 CDP 连接跨 session 复用

### 模式矩阵

| 调用模式 | 浏览器模式 | 后端实现 | 智能模式 | 数据流 |
|---------|-----------|---------|---------|--------|
| CLI | local | LocalCDPBackend (daemon) | LLM | Agent → Python API → CDP |
| CLI | extension | ExtensionBackend (Chrome) | LLM | Agent → WS → chrome.debugger → CDP |
| CLI | local | LocalCDPBackend | Agent | Agent → run_task → browser-use → CDP |
| API | local | RemoteAPIBackend → localhost FastAPI | LLM/Agent | Agent → HTTP → FastAPI → CDP |
| API | remote | RemoteAPIBackend → Gateway → Docker | LLM/Agent | Agent → HTTP → Gateway → Docker CDP |

## 代码组织

### 目录结构

```
agent-browser/
├── src/                                  # 服务端源代码（FastAPI）
│   ├── api.py                            # FastAPI 入口点
│   ├── api_gateway.py                    # API 网关（多用户路由）
│   ├── models.py                         # 数据模型
│   ├── controller.py                     # 遗留控制器（向后兼容）
│   ├── cli_handler.py                    # CLI 处理器
│   ├── persistent_session.py             # 持久化会话
│   ├── proxy_pool.py                     # 代理池
│   ├── events.py                         # 事件系统
│   │
│   ├── browser/                          # 浏览器引擎层
│   │   ├── backends/
│   │   │   ├── __init__.py               # BrowserBackend + BrowserPageHandle ABC
│   │   │   ├── local.py                  # LocalCDPBackend（CloakBrowser）
│   │   │   ├── remote.py                 # RemoteAPIBackend（HTTP 传输）
│   │   │   └── extension.py              # ExtensionBackend（Chrome 扩展）
│   │   ├── daemon.py                     # BrowserDaemon 持久化单例
│   │   ├── stealth_launcher.py           # CloakBrowser 启动（第1-4层）
│   │   ├── human_behavior.py             # 类人行为参数
│   │   └── instance_pool.py              # 浏览器实例池
│   │
│   ├── stealth/                          # ★ 集中式隐匿层（第7层）
│   │   └── middleware.py                 # StealthMiddleware + 熔断器
│   │
│   ├── core/                             # 核心组件
│   │   ├── stealth_enhancer.py           # StealthEnhancer（第6层：贝塞尔鼠标等）
│   │   ├── stealth_actions.py            # 隐身动作覆写
│   │   ├── stealth_patches.js            # JS 注入补丁
│   │   ├── browser_controller.py         # 浏览器控制器
│   │   ├── session_manager.py            # 会话管理
│   │   └── action_tracer.py              # 动作追踪
│   │
│   ├── gateway/                          # API 网关模块
│   │   ├── api.py                        # Gateway REST 端点
│   │   ├── browser_pool.py               # 浏览器实例池
│   │   ├── key_store.py                  # API Key 存储
│   │   └── state.py                      # 网关状态
│   │
│   ├── cli/                              # CLI 模块
│   │   ├── main.py                       # CLI 入口
│   │   ├── commands.py                   # 命令定义
│   │   ├── session_manager.py            # CLI 会话管理
│   │   ├── session_store.py              # 文件持久化
│   │   └── output.py                     # 输出格式化
│   │
│   ├── llm/                              # LLM 抽象层
│   │   └── factory.py                    # LLM 工厂（OpenAI/Anthropic/GLM）
│   │
│   ├── agent/                            # Agent 层
│   │   └── runner.py                     # browser-use Agent 执行器
│   │
│   ├── session/                          # 会话管理层
│   │   ├── pool_manager.py               # 多用户会话池
│   │   ├── profile_manager.py            # 配置文件管理
│   │   └── session_manager.py            # 指纹-IP-Cookie 一致性
│   │
│   └── config/                           # 配置系统
│       └── manager.py                    # ConfigManager
│
├── skills/agent-browser/                 # Skill 包（Claude Code / OpenClaw）
│   ├── __init__.py                       # 顶层导出
│   ├── main.py                           # Facade API（模式路由）
│   ├── config.py                         # 配置系统（SkillConfig）
│   ├── daemon.py                         # BrowserDaemon（Skill 层封装）
│   ├── stealth.py                        # StealthEnhancer（Skill 层封装）
│   ├── controller.py                     # 遗留控制器（向后兼容）
│   ├── session_manager.py                # 会话管理器（Backend 包装）
│   ├── refs_generator.py                 # 元素引用生成
│   │
│   ├── backends/                         # 后端抽象层（重导出到 src/）
│   │   ├── __init__.py                   # BrowserBackend + BrowserPageHandle ABC
│   │   ├── local.py                      # LocalCDPBackend（核心实现）
│   │   └── remote.py                     # RemoteAPIBackend（HTTP 传输）
│   │
│   ├── intelligence/                     # 智能模式
│   │   ├── __init__.py                   # run_task() 路由
│   │   └── agent_runner.py               # browser-use Agent 执行器
│   │
│   ├── pipeline/                         # YAML Pipeline 引擎（v2.3）
│   │   ├── executor.py                   # 执行器（含 fallback/telemetry 集成）
│   │   ├── steps.py                      # 步骤实现（通过 StealthPageHandle 执行）
│   │   ├── template.py                   # 模板引擎（19 种过滤器）
│   │   ├── errors.py                     # 类型化错误层次（6 类异常）
│   │   ├── classifier.py                 # 错误分类器（ErrorCategory 枚举 + 启发式）
│   │   ├── fallback.py                   # 自动恢复策略（per error category）
│   │   ├── debugger.py                   # 单步调试器 + 断点 + 状态检查
│   │   ├── telemetry.py                  # JSONL 遥测统计（~/.agent-browser/telemetry.jsonl）
│   │   └── steps/                       # 步骤定义目录
│   │
│   ├── explore/                          # 站点探索模块
│   │   ├── explorer.py                   # 站点探索器
│   │   ├── analysis.py                   # DOM 结构分析
│   │   ├── cascade.py                    # 级联选择器生成
│   │   └── synthesizer.py                # YAML 适配器合成器
│   │
│   ├── adapters/                         # 站点适配器（零 token）
│   │   ├── loader.py                     # 适配器加载器
│   │   ├── runner.py                     # 适配器运行器
│   │   └── validator.py                  # YAML 校验器（5 项检查）
│   │
│   ├── desktop/                          # 桌面应用控制
│   │   ├── applescript.py               # AppleScript 交互
│   │   ├── cdp_discovery.py             # CDP 端点发现
│   │   └── runner.py                     # 桌面运行器
│   │
│   └── SKILL.md                          # Skill 文档
│
├── tests/                                # 测试套件
│   ├── conftest.py                       # 全局 fixtures
│   ├── helpers/                          # 测试工具（api_client, cli_runner, skill_loader）
│   ├── integration/                      # 集成测试（8 个文件）
│   ├── e2e/                              # 端到端测试
│   ├── test_stealth_middleware.py        # 中间件测试（19 个）
│   ├── test_classifier.py                # 分类器测试（16 个）
│   ├── test_fallback.py                  # 恢复策略测试（10 个）
│   ├── test_debugger.py                  # 调试器测试（16 个）
│   ├── test_telemetry.py                 # 遥测测试（16 个）
│   ├── test_explore_*.py                 # 探索模块测试
│   └── test_scenario_*.py                # 场景测试（7 个场景）
│
├── examples/                             # 示例脚本（6 个）
├── scripts/                              # 实用脚本
├── docker/                               # Docker 配置
└── docs/                                 # 文档
    ├── ARCHITECTURE.md                   # 架构设计
    ├── Agent-Browser 架构方案V4.md        # 详细架构方案
    ├── DEPLOYMENT.md                     # 部署指南
    ├── INSTALL.md                        # 安装指南
    ├── TEST_GUIDE.md                     # 测试说明
    └── archive/                          # 历史文档归档
```

### 关键文件说明

**Skill 核心层：**
- `main.py` - Facade API，所有操作的统一入口
  - `_ensure_backend()` - 模式检测 + 后端路由（local/extension/remote）
  - `run_task()` - Agent 模式任务提交
  - `debug_pipeline()` - Pipeline 调试入口
  - 原子操作：`create_session`, `snapshot`, `click`, `fill`, `scroll` 等

- `config.py` - 配置系统
  - `SkillConfig` dataclass - calling_mode, browser_mode, intelligence, daemon, stealth 设置
  - `detect_mode()` - 自动探测（localhost:8000/health → API 模式）
  - `load_config()` - 配置优先级：参数 → 环境变量 → YAML → 自动探测

**后端抽象层：**
- `backends/__init__.py` - 后端抽象
  - `BrowserBackend` ABC - connect, disconnect, create_session, delete_session, get_page
  - `BrowserPageHandle` ABC - goto, evaluate, mouse_wheel, mouse_move, keyboard_press, on, close

- `backends/local.py` - **LocalCDPBackend（唯一浏览器操作核心）**
  - CDP 连接 + 会话管理 + StealthEnhancer
  - `PlaywrightPageHandle` - Playwright Page 薄包装
  - Daemon 集成：持久连接 + 空闲断开

- `backends/remote.py` - **RemoteAPIBackend（HTTP 传输层）**
  - aiohttp REST 调用 + X-API-Key 认证
  - `RemotePageHandle` - 每个方法翻译为 HTTP 请求

- `src/browser/backends/extension.py` - **ExtensionBackend（Chrome 扩展）**
  - 通过 WebSocket 连接 Chrome Extension
  - 使用 `chrome.debugger` 操作用户真实浏览器
  - 自然指纹 + 继承登录状态
  - 无 Extension 时自动回退到 LocalCDPBackend

**Pipeline 引擎（v2.3）：**
- `pipeline/executor.py` - 执行器入口，fail_fast=False 时集成 fallback + telemetry
- `pipeline/steps.py` - 步骤实现，所有操作通过 StealthPageHandle 执行
- `pipeline/template.py` - 模板引擎，支持 19 种过滤器和算术表达式
- `pipeline/errors.py` - 类型化错误层次（6 类异常 + fix_hint 自动生成）
- `pipeline/classifier.py` - 错误分类器（ErrorCategory 枚举 + 启发式匹配）
- `pipeline/fallback.py` - 自动恢复策略（SELECTOR_DRIFT 重验证 / TIMEOUT 重试 / AUTH_FAILURE 标记）
- `pipeline/debugger.py` - 单步调试器（DebugSession + breakpoints + step history）
- `pipeline/telemetry.py` - JSONL 遥测统计（record/get_stats/get_recent/clear）

**站点探索模块：**
- `explore/explorer.py` - 站点探索器，自动遍历页面结构
- `explore/analysis.py` - DOM 结构分析（交互元素识别）
- `explore/cascade.py` - 级联 CSS 选择器生成
- `explore/synthesizer.py` - YAML 适配器自动合成

**智能模式层：**
- `intelligence/__init__.py` - `run_task()` 路由
- `intelligence/agent_runner.py` - browser-use Agent + stealth_actions + 分块执行

**隐匿增强：**
- `src/stealth/middleware.py` - **StealthMiddleware（第7层，集中隐匿层）**
  - `StealthPageHandle` 装饰器：按操作类型自动注入 pre/post action 延迟
  - `_PerSessionCircuit` 熔断器：per-session 状态机（CLOSED→OPEN，阈值=5）
  - 操作分类：stealth-wrapped (goto/click/fill/scroll) vs passthrough (evaluate/title/url)

- `daemon.py` (Skill 层) / `src/browser/daemon.py` (服务端) - BrowserDaemon 单例
  - `ensure_connected()` - 懒连接 + 自动重连
  - `create_context()` / `destroy_context()` - 会话管理
  - `_idle_monitor_loop()` - 双条件空闲断开

- `stealth.py` (Skill 层) / `src/core/stealth_enhancer.py` (服务端) - StealthEnhancer（第6层）
  - `pre_action()` - 按操作类型差异化延迟
  - `human_type()` - 50-250ms/字符 + 5% typo + 10% 长停顿
  - `random_mouse_move()` - 三次贝塞尔曲线 + 正弦波速度变化
  - `inject_timing_noise()` - Date.now/performance.now 偏移

**服务端新增模块（src/）：**
- `src/api_gateway.py` - API 网关，多用户路由 + API Key 认证
- `src/gateway/` - Gateway 子系统（api, browser_pool, key_store, state）
- `src/cli/` - CLI 子系统（main, commands, session_manager, session_store, output）
- `src/llm/factory.py` - LLM 工厂，支持 OpenAI/Anthropic/GLM 多提供商
- `src/persistent_session.py` - 持久化会话跨进程复用
- `src/proxy_pool.py` - 代理池管理
- `src/events.py` - 事件总线

## 开发规范

### 命名约定

**文件名：** snake_case
```python
stealth_launcher.py
pool_manager.py
local.py  # backends/
```

**类名：** PascalCase
```python
class LocalCDPBackend:
class BrowserDaemon:
class StealthEnhancer:
class StealthMiddleware:
class ExtensionBackend:
class PipelineExecutor:
class ErrorClassifier:
```

**函数/方法：** snake_case
```python
async def create_session():
async def _ensure_backend():  # 私有方法前缀 _
```

**变量：** snake_case
```python
session_id = "xxx"
_backend = None  # 模块级私有变量前缀 _
```

**常量：** UPPER_SNAKE_CASE
```python
CDP_PORT = 19222
MAX_SESSIONS = 10
```

### 类型提示

**必须使用类型提示：**
```python
from typing import Optional, Dict, List

async def create_session(
    cdp_url: str = None,
    mode: str = None,
) -> str:
    pass

class LocalCDPBackend:
    _sessions: Dict[str, LocalSession]
    _daemon: Optional["BrowserDaemon"]
```

### Async/Await 模式

**广泛使用异步编程：**
```python
# 异步函数
async def connect():
    await daemon.ensure_connected()

# 后台任务
asyncio.create_task(idle_monitor_loop())
```

### 错误处理

**使用自定义异常（Pipeline 引擎 v2.2 引入的类型化错误层次）：**
```python
from pipeline.errors import (
    PipelineError,          # 基类
    AdapterLoadError,       # 适配器加载失败
    AdapterValidationError,  # 适配器 YAML 校验失败
    PipelineStepError,      # 步骤执行错误
    StepTimeoutError,       # 步骤超时
    SelectorNotFoundError,  # 选择器未找到
    URLError,               # URL 错误
)

# 每个错误携带上下文：
# step_index, step_name, adapter_name, fix_hint
err.to_dict()  # 结构化输出
err.user_message  # 用户友好格式
```

## 配置管理

### 环境变量

```bash
# 调用模式
AGENT_BROWSER_CALLING_MODE=cli          # cli | api
AGENT_BROWSER_BROWSER_MODE=local        # local | extension | remote
AGENT_BROWSER_INTELLIGENCE=llm          # llm | agent

# 连接配置
AGENT_BROWSER_CDP_URL=http://127.0.0.1:19222
AGENT_BROWSER_API_URL=http://localhost:8000
AGENT_BROWSER_API_KEY=xxx

# Daemon 配置
AGENT_BROWSER_DAEMON_ENABLED=true
AGENT_BROWSER_DAEMON_IDLE_TIMEOUT=1800

# 隐匿配置
AGENT_BROWSER_STEALTH_ENABLED=true
AGENT_BROWSER_STEALTH_MODE=full           # full | vanilla

# LLM 配置（Agent 模式 / Pipeline 引擎）
LLM_PROVIDER=openai                     # openai | anthropic
LLM_MODEL=gpt-4                         # 支持 glm-5-turbo 等
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.openai.com/v1
ANTHROPIC_API_KEY=sk-ant-xxx
```

### 配置优先级

1. 显式参数（`create_session(mode="api")`）
2. 环境变量（`AGENT_BROWSER_CALLING_MODE`）
3. YAML 配置（`~/.agent-browser/config.yaml`）
4. 自动探测（localhost:8000/health）
5. 硬编码默认（CLI + local）

### 自动探测逻辑

```python
async def detect_mode() -> SkillConfig:
    # 1. 尝试 API 模式
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("http://localhost:8000/health", timeout=2) as resp:
                if resp.status == 200:
                    return SkillConfig(calling_mode="api")
    except:
        pass

    # 2. 检测本地 CDP
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("http://127.0.0.1:19222/json/version", timeout=2) as resp:
                if resp.status == 200:
                    return SkillConfig(calling_mode="cli")
    except:
        pass

    # 3. 默认 CLI
    return SkillConfig()
```

## 常见开发任务

### 添加新的原子操作

1. 在 `BrowserPageHandle` ABC 中定义接口（`backends/__init__.py`）
2. 在 `PlaywrightPageHandle` 中实现（`backends/local.py`）
3. 在 `ExtensionPageHandle` 中实现（`src/browser/backends/extension.py`）
4. 在 `RemotePageHandle` 中添加 HTTP 映射（`backends/remote.py`）
5. 在 `main.py` 中暴露 API
6. 在 `__init__.py` 中导出

### 添加新的 FastAPI 端点

1. 在 `src/api.py` 中添加端点
2. 在 `RemotePageHandle` 中添加对应的 HTTP 调用

### 添加新的 Pipeline 步骤

1. 在 `pipeline/steps.py` 中添加步骤实现（通过 StealthPageHandle 执行）
2. 在 `pipeline/template.py` 中注册步骤模板（如需要变量替换）
3. 在 `adapters/validator.py` 的 STEPS registry 中注册（自动检测）
4. 在 `pipeline/errors.py` 中添加对应的错误类型（如需要）
5. 在 `pipeline/classifier.py` 中添加启发式分类规则（如需要）

### 增强 StealthMiddleware

**关键文件：** `src/stealth/middleware.py`

```python
# 新增操作类型映射
delay_map["new_action"] = (0.3, 0.8)
```

**同步更新：** `intelligence/agent_runner.py` 中的 `stealth_actions`

### 添加新的站点适配器

1. 手动：在 `adapters/{site}/` 下创建 YAML 文件
2. 自动：使用 `explore()` 分析目标站点 → `synthesize()` 生成适配器 YAML

### 添加新的浏览器后端

1. 在 `src/browser/backends/` 创建新后端文件
2. 实现 `BrowserBackend` 和 `BrowserPageHandle` ABC
3. 在 `skills/agent-browser/backends/__init__.py` 注册
4. 在 `main.py` 的 `_ensure_backend()` 中添加路由分支
5. 更新 `config.py` 的 `browser_mode` 枚举

## 重要注意事项

### 反检测敏感性

**不要破坏反检测功能：**
- 不要修改 CDP 端口（19222）
- 不要移除 CloakBrowser 启动参数
- 不要频繁 attach/detach CDP 会话（使用 Daemon）
- 不要在浏览器中注入明显的自动化标记
- 不要绕过 StealthMiddleware（它是集中隐匿层，绕过会导致检测信号不一致）

### Backend 抽象

**保持 LocalCDPBackend 为唯一浏览器操作核心：**
- 所有浏览器操作逻辑只在 `src/browser/backends/local.py` 实现
- RemoteAPIBackend 只做 HTTP 序列化，零业务逻辑
- ExtensionBackend 通过 chrome.debugger 代理，不重新实现操作逻辑
- FastAPI 服务端内部运行 LocalCDPBackend

### Pipeline 引擎注意事项

- 适配器 YAML 必须通过 `validator.py` 的 5 项检查才能加载
- `fail_fast=True` 时错误立即抛出；`fail_fast=False` 时先尝试 fallback
- 遥测写入是非阻塞的，不影响 pipeline 执行性能
- 调试器断点命中时返回状态字典，不返回数据

### 资源管理

**BrowserDaemon 生命周期：**
- 首次 `ensure_connected()` 时懒连接
- 双条件断开：无活跃 session 且 超过 idle_timeout
- 状态持久化到 `~/.agent-browser/daemon-state.json`

**StealthMiddleware 熔断器：**
- per-session 作用域（非全局），避免一个 session 影响其他 session
- 阈值默认 5 次连续失败后 OPEN（禁用该 session 的隐匿）
- 新 session 自动 RESET（failure_count = 0）

### 中文文档

- README.md 使用中文
- 代码注释主要是中文
- 代码本身使用英文（变量名、函数名、类名）

## 技术栈参考

**核心依赖：**
- `playwright` / `patchright` - 浏览器自动化
- `browser-use==0.12.2` - AI agent 框架
- `langchain-openai` / `langchain-anthropic` - LLM 集成
- `fastapi` + `uvicorn` - REST API
- `aiohttp` - HTTP 客户端（RemoteAPIBackend）
- `cloakbrowser==0.3.18` - 反检测 Chromium（安装在 `.venv`，C++ 编译级指纹伪装 33 处补丁）

**CloakBrowser 安装信息：**
- 包名：`cloakbrowser`
- 版本：`0.3.18`
- 安装位置：`.venv/lib/python3.13/site-packages`
- 依赖：`httpx`, `playwright`
- 启动方式：需通过 CloakBrowser 启动浏览器（非普通 Chrome），才能激活第 1 层反检测
- CDP 端口：`127.0.0.1:19222`

## 相关文档

- `README.md` - 项目概述和快速开始
- `skills/agent-browser/SKILL.md` - Skill 使用文档
- `docs/ARCHITECTURE.md` - 架构设计
- `docs/Agent-Browser 架构方案V4.md` - 详细架构方案
- `docs/DEPLOYMENT.md` - 部署指南
- `docs/INSTALL.md` - 安装指南
- `docs/TEST_GUIDE.md` - 测试说明
- `CHANGELOG.md` - 版本历史
- `AUTORESEARCH.md` - 自主优化实验规则

---

**最后更新：** 2026-04-05
