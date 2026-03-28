# Agent Browser

AI 驱动的反检测浏览器自动化平台，支持多用户隔离、灵活部署。

## 项目概述

Agent Browser 是一个基于 FastAPI + browser-use 的浏览器自动化系统，专为高防护网站设计。核心特性：

- **CloakBrowser 引擎**：Chromium + C++ 级指纹伪装（33 项补丁）
- **5 层反检测栈**：编译级指纹 → 驱动级 CDP 修补 → 运行时泄漏修复 → 连接隐匿 → 持久会话
- **多用户隔离**：每个用户独立 Session、Profile、Cookie、指纹
- **灵活部署**：本地开发 / Docker All-in-One / Docker 分布式

## 架构

```
┌─────────────────────────────────────────────────────────┐
│  FastAPI API (:8000)                                     │
│  POST /sessions/create  →  GET /sessions  →  DELETE      │
│  POST /sessions/{id}/task  →  GET /tasks/{id}            │
└──────────────────┬──────────────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────────────┐
│  SessionPoolManager                                      │
│  多用户隔离 · 资源限制 · 空闲回收 · 健康检查              │
└──────────────────┬──────────────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────────────┐
│  BrowserInstancePool                                     │
│  ┌─────────────────────────────────────────┐             │
│  │ CloakBrowser (Chromium)                 │             │
│  │ CDP 协议 + browser-use Agent            │             │
│  └─────────────────────────────────────────┘             │
└─────────────────────────────────────────────────────────┘
```

### 5 层反检测栈（Chromium）

| 层 | 组件 | 功能 |
|---|------|------|
| 1 | CloakBrowser | C++ 编译级指纹伪装（33 项补丁） |
| 2 | patchright | 驱动级 CDP 修补（移除 `__playwright__binding__`） |
| 3 | rebrowser-patches | Runtime.Enable 泄漏修复（addBinding 模式） |
| 4 | 非标准端口 19222 | 绑定 127.0.0.1，连接隐匿 |
| 5 | 持久单 CDP 会话 | 禁止频繁 attach/detach |

## 快速开始

### 一键安装（推荐）

```bash
# 克隆仓库
git clone https://github.com/your-org/agent-browser.git
cd agent-browser

# 运行安装脚本
./scripts/install.sh
```

安装脚本会自动：
- 检测操作系统和架构（macOS/Linux, x64/arm64）
- 安装必要的依赖（Python、Docker 等）
- 提供交互式菜单选择部署模式
- 配置环境变量
- 启动服务

详细安装指南请参考 [INSTALL.md](./docs/INSTALL.md)。

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
cd src && python -m uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```

### Docker All-in-One

```bash
# 使用脚本部署
./scripts/deploy-docker.sh --mode aio

# 或使用 docker-compose
cd docker
docker-compose --profile all-in-one up -d

# 访问
# API: http://localhost:8000
# noVNC: http://localhost:6080/vnc.html
```

### Docker 分布式

```bash
# 使用脚本部署
./scripts/deploy-docker.sh --mode distributed

# 或使用 docker-compose
cd docker
export HOST_PROFILE_PATH=$(pwd)/data/profiles
docker-compose --profile distributed up -d
```

### Kubernetes 部署

```bash
# 使用原生 YAML
./scripts/deploy-k8s.sh --mode aio --registry registry.example.com

# 或使用 Helm Chart
helm install agent-browser ./helm/agent-browser \
  -f helm/agent-browser/values-aio.yaml \
  --set secrets.anthropicApiKey=your-key \
  --set secrets.openaiApiKey=your-key \
  --namespace agent-browser \
  --create-namespace
```

详细部署指南请参考：
- [安装文档](./docs/INSTALL.md)
- [部署文档](./docs/DEPLOYMENT.md)

## 双引擎支持

### CloakBrowser (Chromium) — 默认

- browser-use Agent 通过 CDP 连接
- DOM 压缩 + 结构化 action + 多模型支持
- 适合需要 AI Agent 智能交互的场景

```bash
curl -X POST http://localhost:8000/sessions/create \
  -H "Content-Type: application/json" \
  -d '{"user_id": "alice", "browser_type": "chromium"}'
```

## API 参考

### Session 管理

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/sessions/create` | 创建新会话 |
| GET | `/sessions/{session_id}` | 查询会话状态 |
| DELETE | `/sessions/{session_id}` | 删除会话 |
| GET | `/sessions` | 列出所有会话 |

### 任务管理

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/sessions/{session_id}/task` | 提交任务到指定会话 |
| GET | `/sessions/{session_id}/tasks/{task_id}` | 查询任务状态 |

### 向后兼容（旧版 API）

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/tasks` | 自动创建临时 Session 并执行任务 |
| GET | `/tasks/{task_id}` | 查询任务状态 |

### 健康检查

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/health` | 服务健康状态 |

### 请求示例

**创建会话**
```json
POST /sessions/create
{
  "user_id": "alice",
  "browser_type": "chromium",
  "profile_config": {}
}
```

**提交任务**
```json
POST /sessions/alice_a1b2c3d4/task
{
  "task": "在 zhipin.com 搜索 Python 开发岗位，提取前 5 个结果",
  "model": "gpt-4o-mini",
  "max_steps": 30
}
```

## 配置参考

| 环境变量 | 默认值 | 说明 |
|---------|-------|------|
| `OPENAI_API_KEY` | — | OpenAI API Key |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI API 基地址 |
| `DEPLOYMENT_MODE` | `all-in-one` | 部署模式 |
| `BROWSER_MODE` | `local` | 浏览器模式 (`local` / `docker`) |
| `MAX_SESSIONS` | `10` | 最大并发会话数 |
| `IDLE_TIMEOUT_SECONDS` | `1800` | 会话空闲超时（秒） |
| `CDP_PORT` | `19222` | CDP 调试端口 |
| `CDP_BIND_ADDRESS` | `127.0.0.1` | CDP 绑定地址 |
| `HEADLESS` | `false` | 是否无头模式 |
| `PROFILE_STORAGE` | `/data/profiles` | Profile 存储路径 |
| `LOG_LEVEL` | `info` | 日志级别 |
| `PROXY_LIST` | — | 代理列表（逗号分隔） |
| `PROXY_LIST_FILE` | — | 代理列表文件路径（JSON） |
| `HOST_PROFILE_PATH` | — | 宿主机 profile 路径（分布式模式） |
| `DEBUG_CONTAINERS` | `false` | 保留崩溃容器用于调试 |

## 项目结构

```
agent-browser/
├── src/
│   ├── api.py                          # FastAPI 入口
│   ├── models.py                       # 数据模型
│   ├── proxy_pool.py                   # 代理池管理
│   ├── persistent_session.py           # CDP 持久化工具
│   ├── browser/                        # 浏览器引擎层
│   │   ├── stealth_launcher.py         #   CloakBrowser 启动
│   │   ├── instance_pool.py            #   浏览器实例池
│   │   └── human_behavior.py           #   行为模拟
│   ├── session/                        # 会话管理层
│   │   ├── pool_manager.py             #   会话池管理
│   │   ├── profile_manager.py          #   Profile 管理
│   │   └── session_manager.py          #   指纹-IP-Cookie 一致性
│   └── agent/                          # Agent 层
│       └── runner.py                   #   browser-use Agent 运行器
├── tests/
├── scripts/
├── docker/
│   ├── Dockerfile                      #   All-in-One
│   ├── Dockerfile.api                  #   API 容器
│   ├── Dockerfile.browser              #   Chromium 浏览器容器
│   └── docker-compose.yml
├── docs/
├── requirements.txt
└── .env.example
```

## 已知问题与最佳实践

### browser-use Agent 已知问题

1. **`evaluate()` action**：browser-use 0.12.2 有 pydantic schema 验证 bug，任务 prompt 中应禁止使用
2. **LLM 90s 超时**：复杂页面截图导致推理超时，建议控制 prompt 长度、用 `extract()` 替代截图分析
3. **iframe DOM 失效**：iframe 内 DOM 元素 ID 在面板打开后失效，避免打开详情面板

### 最佳实践

- 任务 prompt 中明确禁止 `evaluate()`
- 优先用 `click(coordinate_x, coordinate_y)` 而非 `click(index=N)`
- 用 `extract()` 提取内容比截图识别更可靠
- 弹窗处理前置（高防护站点频繁弹窗）
- 非交互环境用 `asyncio.sleep` 替代 `input()`

## 测试

```bash

# 反检测测试
python tests/test_anti_detection.py

# API 端点测试
python tests/test_api.py

# 分布式模式测试
python tests/test_distributed.py

# 性能测试
python tests/performance_test.py

# OpenClaw E2E 场景测试（需 openclaw gateway 运行）
bash scripts/test_openclaw_e2e.sh
```

## OpenClaw Skill 集成

agent-browser 提供 OpenClaw skill，让 AI agent 通过自然语言控制浏览器自动化。

**安���路径：** `~/.openclaw/skills/agent-browser/SKILL.md`

**工作流：**
```
用户消息 → OpenClaw agent → SKILL.md 工作流
    → bash: curl → FastAPI (:8000) REST API
    → FastAPI → Docker 浏览器容器
    → message: 反馈 VNC URL、进度
    → sessions_yield: 等待用户操作（扫码等）
```

**特性：**
- 分块执行循环（max_steps=6，75s 轮询超时）
- 卡住检测（超时/空结果/重复）
- 用户干预流程（VNC 桌面链接 + sessions_yield 暂停）
- 进度主动汇报

**E2E 测试：**
```bash
# 前提：FastAPI (localhost:8000) + OpenClaw gateway 已运行
bash scripts/test_openclaw_e2e.sh
```

测试覆盖 5 个场景（Docker 基础、HttpBin 验证、多轮交互、独立 Session UUID、独立 Session IP）。

## 使用场景

- **高防护网站数据采集**：Boss 直聘、淘宝等有多层反爬的站点
- **AI Agent 自动化交互**：LLM 驱动的类人浏览器操作
- **多账号隔离管理**：每个用户独立指纹、Cookie、代理
- **反检测测试验证**：评估网站反爬系统的检测能力
