# Agent Browser

AI 驱动的反检测浏览器自动化平台，支持多模式、多用户隔离、灵活部署。

## 项目概述

Agent Browser 是一个基于 FastAPI + browser-use 的浏览器自动化系统，专为高防护网站设计。核心特性：

- **CloakBrowser 引擎**：Chromium + C++ 级指纹伪装（33 项补丁）
- **6 层反检测栈**：编译级指纹 → 驱动级 CDP 修补 → 运行时泄漏修复 → 连接隐匿 → 持久会话 → 行为模拟
- **多模式支持**：CLI/API × LLM/Agent 灵活组合
- **多用户隔离**：每个用户独立 Session、Profile、Cookie、指纹

## 架构

```
┌─────────────────────────────────────────────────────────────────┐
│                     SKILL.md (Facade)                            │
│          模式检测 + ReAct/Agent 路由                              │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│                      main.py (API)                               │
│       _ensure_backend() 路由 + run_task() 智能模式               │
└───────────────┬─────────────────────────────────┬───────────────┘
                │                                 │
┌───────────────▼───────────────┐  ┌──────────────▼───────────────┐
│      LocalCDPBackend          │  │      RemoteAPIBackend        │
│      (本地 CDP 直连)           │  │      (HTTP 传输适配器)        │
│  ├─ BrowserDaemon 持久化      │  │  ├─ aiohttp REST 调用        │
│  ├─ StealthEnhancer 隐匿增强  │  │  ├─ X-API-Key 认证           │
│  └─ browser-use Agent         │  │  └─ session_id 映射          │
└───────────────────────────────┘  └──────────────┬───────────────┘
                                                  │ HTTP
                                   ┌──────────────▼───────────────┐
                                   │      FastAPI 服务端           │
                                   │  (内部运行 LocalCDPBackend)   │
                                   │         ↓                    │
                                   │  ┌───────────────────────┐   │
                                   │  │ Gateway + Docker      │   │
                                   │  │ (remote browser mode) │   │
                                   │  └───────────────────────┘   │
                                   └──────────────────────────────┘
```

### 6 层反检测栈

| 层 | 组件 | 功能 |
|---|------|------|
| 1 | CloakBrowser | C++ 编译级指纹伪装（33 项补丁） |
| 2 | patchright | 驱动级 CDP 修补（移除 `__playwright__binding__`） |
| 3 | rebrowser-patches | Runtime.Enable 泄漏修复（addBinding 模式） |
| 4 | 非标准端口 19222 | 绑定 127.0.0.1，连接隐匿 |
| 5 | BrowserDaemon | 持久单 CDP 会话，禁止频繁 attach/detach |
| 6 | StealthEnhancer | 人类延迟 + 贝塞尔鼠标 + 逐字输入 + 定时器噪声 |

### 模式矩阵

| 调用模式 | 浏览器模式 | 后端实现 | 智能模式 | 数据流 |
|---------|-----------|---------|---------|--------|
| CLI | local | LocalCDPBackend (daemon) | LLM | Agent → Python API → CDP |
| CLI | local | LocalCDPBackend | Agent | Agent → run_task → browser-use → CDP |
| API | local | RemoteAPIBackend → localhost FastAPI | LLM/Agent | Agent → HTTP → FastAPI → CDP |
| API | remote | RemoteAPIBackend → Gateway → Docker | LLM/Agent | Agent → HTTP → Gateway → Docker CDP |

## 快速开始

### 一键安装（推荐）

```bash
# 克隆仓库
git clone https://github.com/your-org/agent-browser.git
cd agent-browser

# 运行安装脚本
./scripts/install.sh
```

### 环境要求

- Python 3.11+
- Docker（可选，用于容器化部署）

### 本地开发

```bash
cd agent-browser

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 设置 OPENAI_API_KEY 等

# 启动 API 服务
cd src && python -m uvicorn api:app --host 0.0.0.1 --port 8000 --reload
```

### Docker 部署

```bash
# All-in-One 模式
docker-compose -f docker/docker-compose.yml --profile all-in-one up -d

# 分布式模式
docker-compose -f docker/docker-compose.yml --profile distributed up -d
```

## Skill 使用（Claude Code / OpenClaw）

### LLM ReAct 模式（原子操作）

外部 LLM 通过 ReAct 循环控制每一步：

```python
from agent_browser import create_session, delete_session, open_page, snapshot, click, fill

# 创建会话
sid = await create_session()

# ReAct 循环
await open_page(sid, "https://example.com")
snap = await snapshot(sid)  # {url, title, elements: [{ref, text, role}]}

# 分析 snap["elements"] 找到目标元素
for el in snap["elements"]:
    if "搜索" in el.get("text", ""):
        await fill(sid, el["ref"], "关键词")
    if "提交" in el.get("text", ""):
        await click(sid, el["ref"])

# 清理
await delete_session(sid)
```

### Agent 模式（自主执行）

内置 browser-use Agent 自主完成整个任务：

```python
from agent_browser import create_session, delete_session, run_task

sid = await create_session()
result = await run_task(
    sid,
    task="访问百度搜索 AI coding，提取前5条结果",
    intelligence="agent",
    max_steps=10,
)
await delete_session(sid)

# result = {"status": "completed", "result": "...", "steps": 8}
```

### 适配器模式（零 LLM 成本）

```python
from agent_browser import run_adapter

# 直接执行预录制 pipeline
results = await run_adapter("baidu", "search", query="AI coding", limit=5)
```

## API 参考

### Session 管理

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/sessions/create` | 创建新会话 |
| GET | `/sessions/{session_id}` | 查询会话状态 |
| DELETE | `/sessions/{session_id}` | 删除会话 |

### 任务管理

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/sessions/{session_id}/task` | 提交 Agent 任务 |
| GET | `/sessions/{session_id}/tasks/{task_id}` | 查询任务状态 |

### 原子操作（LLM 模式）

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/sessions/{session_id}/snapshot` | 获取页面快照 + 元素 refs |
| POST | `/sessions/{session_id}/click` | 点击元素 |
| POST | `/sessions/{session_id}/fill` | 填充输入框 |
| POST | `/sessions/{session_id}/scroll` | 滚动页面 |

## 配置参考

### Skill 配置（skills/agent-browser/）

| 环境变量 | 默认值 | 说明 |
|---------|-------|------|
| `AGENT_BROWSER_CALLING_MODE` | `cli` | 调用模式 (cli/api) |
| `AGENT_BROWSER_BROWSER_MODE` | `local` | 浏览器模式 (local/remote) |
| `AGENT_BROWSER_INTELLIGENCE` | `llm` | 智能模式 (llm/agent) |
| `AGENT_BROWSER_CDP_URL` | `http://127.0.0.1:19222` | CDP 地址 |
| `AGENT_BROWSER_API_URL` | `http://localhost:8000` | FastAPI 地址 |
| `AGENT_BROWSER_DAEMON_ENABLED` | `true` | 启用 Daemon 持久化 |
| `AGENT_BROWSER_DAEMON_IDLE_TIMEOUT` | `1800` | Daemon 空闲超时（秒） |
| `AGENT_BROWSER_STEALTH_ENABLED` | `true` | 启用隐匿增强 |

### 服务端配置（src/）

| 环境变量 | 默认值 | 说明 |
|---------|-------|------|
| `OPENAI_API_KEY` | — | OpenAI API Key |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI API 基地址 |
| `MAX_SESSIONS` | `10` | 最大并发会话数 |
| `IDLE_TIMEOUT_SECONDS` | `1800` | 会话空闲超时（秒） |
| `CDP_PORT` | `19222` | CDP 调试端口 |
| `HEADLESS` | `false` | 是否无头模式 |

## 项目结构

```
agent-browser/
├── src/                              # 服务端源代码（FastAPI）
│   ├── api.py                        # FastAPI 入口
│   ├── browser/                      # 浏览器引擎层
│   ├── session/                      # 会话管理层
│   └── agent/                        # Agent 层
│
├── skills/agent-browser/             # Skill 包（Claude Code / OpenClaw）
│   ├── __init__.py                   # 顶层导出
│   ├── main.py                       # Facade API
│   ├── config.py                     # 配置系统
│   ├── daemon.py                     # BrowserDaemon
│   ├── stealth.py                    # StealthEnhancer
│   ├── backends/                     # 后端抽象
│   │   ├── __init__.py               # BrowserBackend ABC
│   │   ├── local.py                  # LocalCDPBackend
│   │   └── remote.py                 # RemoteAPIBackend
│   ├── intelligence/                 # 智能模式
│   │   ├── __init__.py               # run_task()
│   │   └── agent_runner.py           # browser-use 执行器
│   ├── adapters/                     # 站点适配器
│   ├── pipeline/                     # YAML pipeline
│   ├── explore/                      # 站点探索
│   ├── desktop/                      # 桌面控制
│   └── SKILL.md                      # Skill 文档
│
├── tests/                            # 测试套件
├── scripts/                          # 实用脚本
├── docker/                           # Docker 配置
└── docs/                             # 文档
```

## 测试

```bash
# 反检测测试
python tests/test_anti_detection.py

# API 端点测试
python tests/test_api.py

# 性能测试
python tests/performance_test.py
```

## 已知问题与最佳实践

### browser-use Agent 已知问题

1. **`evaluate()` action**：browser-use 0.12.2 有 pydantic schema 验证 bug，任务 prompt 中应禁止使用
2. **LLM 90s 超时**：复杂页面截图导致推理超时，建议控制 prompt 长度
3. **iframe DOM 失效**：iframe 内 DOM 元素 ID 在面板打开后失效

### 最佳实践

- 任务 prompt 中明确禁止 `evaluate()`
- 优先用 `click(coordinate_x, coordinate_y)` 而非 `click(index=N)`
- 用 `extract()` 提取内容比截图识别更可靠
- 使用 Daemon 持久化连接避免频繁 attach/detach

## 使用场景

- **高防护网站数据采集**：Boss 直聘、淘宝等有多层反爬的站点
- **AI Agent 自动化交互**：LLM 驱动的类人浏览器操作
- **多账号隔离管理**：每个用户独立指纹、Cookie、代理
- **反检测测试验证**：评估网站反爬系统的检测能力

## 相关文档

- [CLAUDE.md](./CLAUDE.md) - Claude Code 开发指南
- [SKILL.md](./skills/agent-browser/SKILL.md) - Skill 使用文档
- [架构方案V4](./docs/Agent-Browser%20架构方案V4.md) - 详细架构设计
- [部署文档](./docs/DEPLOYMENT.md) - 部署指南
