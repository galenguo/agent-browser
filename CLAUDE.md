# Agent Browser - Claude Code 开发指南

## 项目概述

Agent Browser 是一个 AI 驱动的反检测浏览器自动化平台，专为高防护网站设计。它结合了浏览器自动化与 AI 代理，实现智能的网页交互，同时规避检测系统。

**核心能力：**
- 工业级反检测（5层防护栈 + StealthEnhancer）
- 多模式支持（CLI/API × LLM/Agent）
- 多账号隔离（独立指纹、Cookie、代理）
- 灵活的部署模式（本地/Docker/分布式）

**典型应用场景：**
- 高防护网站数据采集（Boss直聘、淘宝等）
- AI Agent 驱动的浏览器自动化
- 反爬虫系统测试与评估

## 架构设计

### 5层反检测栈

| 层级 | 组件 | 功能 |
|------|------|------|
| 1 | CloakBrowser | C++ 编译级指纹伪装（33处补丁） |
| 2 | patchright | 驱动级 CDP 补丁（移除 `__playwright__binding__`） |
| 3 | rebrowser-patches | Runtime.Enable 泄漏修复（addBinding 模式） |
| 4 | 非标准端口 19222 | 绑定 127.0.0.1 混淆连接 |
| 5 | 持久化 CDP 会话 | BrowserDaemon 防止频繁 attach/detach |
| 6 | StealthEnhancer | 人类延迟 + 贝塞尔鼠标 + 逐字输入 |

### 双层架构

```
┌─────────────────────────────────────────────────────────────┐
│                     SKILL.md (facade)                        │
│          模式检测 + ReAct/Agent 路由                          │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                     main.py (API)                            │
│     _ensure_backend() 路由 + run_task() 智能模式             │
└─────────────┬───────────────────────────────┬───────────────┘
              │                               │
┌─────────────▼─────────────┐  ┌──────────────▼───────────────┐
│    LocalCDPBackend        │  │    RemoteAPIBackend          │
│    (本地 CDP 直连)         │  │    (HTTP 传输适配器)          │
│  ├─ BrowserDaemon 持久化   │  │  ├─ aiohttp REST 调用        │
│  ├─ StealthEnhancer       │  │  ├─ X-API-Key 认证           │
│  └─ browser-use Agent     │  │  └─ session_id 映射          │
└───────────────────────────┘  └──────────────┬───────────────┘
                                              │ HTTP
                               ┌──────────────▼───────────────┐
                               │    FastAPI 服务端             │
                               │    (内部运行 LocalCDPBackend) │
                               └──────────────────────────────┘
```

**核心设计原则：**
- **LocalCDPBackend 是唯一浏览器操作核心**：所有浏览器逻辑只实现一次
- **RemoteAPIBackend 是 HTTP 传输层**：零业务逻辑，只做序列化/反序列化
- **用户隔离**：每个用户独立的 session、profile、cookies、fingerprint
- **持久化会话**：BrowserDaemon 单例保持 CDP 连接跨 session 复用

### 模式矩阵

| 调用模式 | 浏览器模式 | 后端实现 | 智能模式 | 数据流 |
|---------|-----------|---------|---------|--------|
| CLI | local | LocalCDPBackend (daemon) | LLM | Agent → Python API → CDP |
| CLI | local | LocalCDPBackend | Agent | Agent → run_task → browser-use → CDP |
| API | local | RemoteAPIBackend → localhost FastAPI | LLM/Agent | Agent → HTTP → FastAPI → CDP |
| API | remote | RemoteAPIBackend → Gateway → Docker | LLM/Agent | Agent → HTTP → Gateway → Docker CDP |

## 代码组织

### 目录结构

```
agent-browser/
├── src/                              # 服务端源代码（FastAPI）
│   ├── api.py                        # FastAPI 入口点
│   ├── models.py                     # 数据模型
│   ├── browser/                      # 浏览器引擎层
│   ├── session/                      # 会话管理层
│   └── agent/                        # Agent 层
│
├── skills/agent-browser/             # Skill 包（Claude Code / OpenClaw）
│   ├── __init__.py                   # 顶层导出
│   ├── main.py                       # Facade API（模式路由）
│   ├── config.py                     # 配置系统（SkillConfig）
│   ├── daemon.py                     # BrowserDaemon 持久化单例
│   ├── stealth.py                    # StealthEnhancer 隐匿增强
│   ├── controller.py                 # 遗留控制器（向后兼容）
│   ├── session_manager.py            # 会话管理器（Backend 包装）
│   │
│   ├── backends/                     # 后端抽象层
│   │   ├── __init__.py               # BrowserBackend + BrowserPageHandle
│   │   ├── local.py                  # LocalCDPBackend（核心实现）
│   │   └── remote.py                 # RemoteAPIBackend（HTTP 传输）
│   │
│   ├── intelligence/                 # 智能模式
│   │   ├── __init__.py               # run_task() 路由
│   │   └── agent_runner.py           # browser-use Agent 执行器
│   │
│   ├── adapters/                     # 站点适配器（零 token）
│   ├── pipeline/                     # YAML pipeline 执行器
│   ├── explore/                      # 站点探索 + 适配器生成
│   ├── desktop/                      # 桌面应用控制
│   └── SKILL.md                      # Skill 文档
│
├── tests/                            # 测试套件
├── scripts/                          # 实用脚本
├── docker/                           # Docker 配置
└── docs/                             # 文档
```

### 关键文件说明

**Skill 核心层：**
- `main.py` - Facade API，所有操作的统一入口
  - `_ensure_backend()` - 模式检测 + 后端路由
  - `run_task()` - Agent 模式任务提交
  - 原子操作：`create_session`, `snapshot`, `click`, `fill`, `scroll` 等

- `config.py` - 配置系统
  - `SkillConfig` dataclass - calling_mode, browser_mode, intelligence, daemon 设置
  - `detect_mode()` - 自动探测（localhost:8000/health → API 模式）
  - `load_config()` - 配置优先级：参数 → 环境变量 → YAML → 自动探测

- `backends/__init__.py` - 后端抽象
  - `BrowserBackend` ABC - connect, disconnect, create_session, delete_session, get_page
  - `BrowserPageHandle` ABC - goto, evaluate, mouse_wheel, mouse_move, keyboard_press, on, close

- `backends/local.py` - **唯一浏览器操作核心**
  - `LocalCDPBackend` - CDP 连接 + 会话管理 + StealthEnhancer
  - `PlaywrightPageHandle` - Playwright Page 薄包装
  - Daemon 集成：持久连接 + 空闲断开

- `backends/remote.py` - HTTP 传输层
  - `RemoteAPIBackend` - aiohttp REST 调用 + 认证
  - `RemotePageHandle` - 每个方法翻译为 HTTP 请求

**智能模式层：**
- `intelligence/__init__.py` - `run_task()` 路由
- `intelligence/agent_runner.py` - browser-use Agent + stealth_actions + 分块执行

**隐匿增强：**
- `daemon.py` - BrowserDaemon 单例
  - `ensure_connected()` - 懒连接 + 自动重连
  - `create_context()` / `destroy_context()` - 会话管理
  - `_idle_monitor_loop()` - 双条件空闲断开

- `stealth.py` - StealthEnhancer
  - `pre_action()` - 按操作类型延迟
  - `human_type()` - 50-250ms/字符 + 5% typo
  - `random_mouse_move()` - 贝塞尔曲线
  - `inject_timing_noise()` - JS 定时器噪声

**服务端（src/）：**
- `src/api.py` - FastAPI REST 端点
- `src/session/pool_manager.py` - 多用户会话池
- `src/browser/stealth_launcher.py` - CloakBrowser 启动
- `src/agent/runner.py` - browser-use Agent 集成

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
class PlaywrightPageHandle:
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

**使用自定义异常：**
```python
class SessionNotFoundError(Exception):
    """会话未找到错误"""
    pass

if session_id not in self._sessions:
    raise SessionNotFoundError(f"Session {session_id} not found")
```

## 配置管理

### 环境变量

```bash
# 调用模式
AGENT_BROWSER_CALLING_MODE=cli     # cli | api
AGENT_BROWSER_BROWSER_MODE=local   # local | remote
AGENT_BROWSER_INTELLIGENCE=llm     # llm | agent

# 连接配置
AGENT_BROWSER_CDP_URL=http://127.0.0.1:19222
AGENT_BROWSER_API_URL=http://localhost:8000
AGENT_BROWSER_API_KEY=xxx

# Daemon 配置
AGENT_BROWSER_DAEMON_ENABLED=true
AGENT_BROWSER_DAEMON_IDLE_TIMEOUT=1800

# 隐匿配置
AGENT_BROWSER_STEALTH_ENABLED=true

# LLM 配置（Agent 模式）
AGENT_BROWSER_LLM_PROVIDER=openai
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.openai.com/v1
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
3. 在 `RemotePageHandle` 中添加 HTTP 映射（`backends/remote.py`）
4. 在 `main.py` 中暴露 API
5. 在 `__init__.py` 中导出

### 添加新的 FastAPI 端点

1. 在 `src/api.py` 中添加端点
2. 在 `RemotePageHandle` 中添加对应的 HTTP 调用

### 增强 StealthEnhancer

**关键文件：** `skills/agent-browser/stealth.py`

```python
async def new_behavior(self, page):
    """新的隐匿行为"""
    await asyncio.sleep(random.uniform(0.5, 1.5))
    # 实现逻辑...
```

**同步更新：** `intelligence/agent_runner.py` 中的 `stealth_actions`

### 添加新的站点适配器

1. 在 `adapters/{site}/` 下创建 YAML 文件
2. 或使用 `explore()` + `synthesize()` 自动生成

## 重要注意事项

### 🔒 反检测敏感性

**不要破坏反检测功能：**
- 不要修改 CDP 端口（19222）
- 不要移除 CloakBrowser 启动参数
- 不要频繁 attach/detach CDP 会话（使用 Daemon）
- 不要在浏览器中注入明显的自动化标记

### 🔐 Backend 抽象

**保持 LocalCDPBackend 为唯一核心：**
- 所有浏览器操作逻辑只在 `backends/local.py` 实现
- RemoteAPIBackend 只做 HTTP 序列化，零业务逻辑
- FastAPI 服务端内部运行 LocalCDPBackend

### 💾 资源管理

**BrowserDaemon 生命周期：**
- 首次 `ensure_connected()` 时懒连接
- 双条件断开：无活跃 session 且 超过 idle_timeout
- 状态持久化到 `~/.agent-browser/daemon-state.json`

### 📝 中文文档

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
- `cloakbrowser` - 反检测 Chromium

## 相关文档

- `README.md` - 项目概述和快速开始
- `skills/agent-browser/SKILL.md` - Skill 使用文档
- `docs/Agent-Browser 架构方案V4.md` - 详细架构设计
- `docs/DEPLOYMENT.md` - 部署指南

---

**最后更新：** 2026-04-03
