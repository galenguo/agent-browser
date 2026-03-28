# Agent Browser - Claude Code 开发指南

## 项目概述

Agent Browser 是一个 AI 驱动的反检测浏览器自动化平台，专为高防护网站设计。它结合了浏览器自动化与 AI 代理，实现智能的网页交互，同时规避检测系统。

**核心能力：**
- 工业级反检测（5层防护栈）
- 多账号隔离（独立指纹、Cookie、代理）
- AI Agent 驱动的智能自动化
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
| 5 | 持久化 CDP 会话 | 防止频繁 attach/detach 循环 |

### 分层架构

```
┌─────────────────────────────────────────┐
│         FastAPI API Layer               │  src/api.py
│  (REST endpoints for session/task mgmt) │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│      Session Management Layer           │  src/session/
│  (Multi-user isolation, resource limits) │  - pool_manager.py
└─────────────────┬───────────────────────┘  - profile_manager.py
                  │                           - session_manager.py
┌─────────────────▼───────────────────────┐
│       Browser Engine Layer              │  src/browser/
│  (Instance pool, stealth launcher)      │  - stealth_launcher.py
└─────────────────┬───────────────────────┘  - instance_pool.py
                  │                           - human_behavior.py
┌─────────────────▼───────────────────────┐
│      Anti-Detection Stack               │
│  (CloakBrowser + patchright + patches)  │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────▼───────────────────────┐
│          Agent Layer                    │  src/agent/
│  (browser-use AI agent integration)     │  - runner.py
└─────────────────────────────────────────┘
```

**核心设计原则：**
- **用户隔离**：每个用户独立的 session、profile、cookies、fingerprint
- **资源限制**：最大并发会话数、空闲超时、端口分配
- **持久化会话**：单个 CDP 连接贯穿任务生命周期（避免检测）
- **行为模拟**：类人鼠标/滚动/输入模式

## 代码组织

### 目录结构

```
agent-browser/
├── src/                          # 主要源代码
│   ├── api.py                    # FastAPI 入口点
│   ├── models.py                 # 数据模型（Pydantic）
│   ├── proxy_pool.py             # 代理池管理
│   ├── persistent_session.py     # CDP 会话持久化工具
│   ├── browser/                  # 浏览器引擎层
│   │   ├── stealth_launcher.py   # CloakBrowser 启动器
│   │   ├── instance_pool.py      # 浏览器实例池
│   │   └── human_behavior.py     # 类人行为模拟
│   ├── session/                  # 会话管理层
│   │   ├── pool_manager.py       # 会话池管理
│   │   ├── profile_manager.py    # 浏览器配置文件管理
│   │   └── session_manager.py    # 指纹-IP-Cookie 一致性
│   └── agent/                    # AI 代理层
│       └── runner.py             # browser-use Agent 运行器
├── tests/                        # 测试套件
├── scripts/                      # 实用脚本
├── docker/                       # Docker 配置
└── docs/                         # 文档
```

### 关键文件说明

**API 层：**
- `src/api.py` - FastAPI 应用入口，定义所有 REST 端点
  - 会话管理：创建/查询/删除会话
  - 任务管理：提交/查询任务状态
  - 健康检查端点

**会话管理层：**
- `src/session/pool_manager.py` - SessionPoolManager 类
  - 多用户隔离、资源限制、空闲清理
  - 核心方法：`create_session()`, `get_session()`, `delete_session()`
- `src/session/profile_manager.py` - ProfileManager 类
  - 浏览器配置文件持久化、指纹生成
- `src/session/session_manager.py` - SessionProfileManager 类
  - 确保指纹-IP-Cookie 一致性

**浏览器引擎层：**
- `src/browser/stealth_launcher.py` - 启动 CloakBrowser
  - 配置反检测参数、CDP 端口、代理
  - 核心方法：`launch_stealth_browser()`
- `src/browser/instance_pool.py` - BrowserInstancePool 类
  - 支持本地和 Docker 模式
  - 实例复用、健康检查
- `src/browser/human_behavior.py` - HumanBehaviorSimulator 类
  - 随机鼠标移动、滚动、输入延迟

**Agent 层：**
- `src/agent/runner.py` - 集成 browser-use
  - 执行 AI 驱动的浏览器任务
  - 核心方法：`run_agent_task()`

**数据模型：**
- `src/models.py` - 所有 Pydantic 模型和自定义异常
  - `SessionCreateRequest`, `TaskSubmitRequest`
  - `ResourceExhaustedError`, `SessionNotFoundError`

## 开发规范

### 命名约定

**文件名：** snake_case
```python
stealth_launcher.py
pool_manager.py
profile_manager.py
```

**类名：** PascalCase
```python
class SessionPoolManager:
class BrowserInstancePool:
class PersistentCDPSession:
class HumanBehaviorSimulator:
```

**函数/方法：** snake_case
```python
async def create_session():
async def launch_stealth_browser():
def _load_proxies():  # 私有方法前缀 _
```

**变量：** snake_case
```python
session_id = "xxx"
browser_instance = None
_session_manager = None  # 模块级私有变量前缀 _
```

**常量：** UPPER_SNAKE_CASE
```python
CDP_PORT = 19222
HEALTH_CHECK_INTERVAL = 30
MAX_SESSIONS = 10
```

### 类型提示

**必须使用类型提示：**
```python
from typing import Optional, Dict, List, Literal

async def create_session(
    user_id: str,
    proxy: Optional[str] = None
) -> Dict[str, str]:
    pass

class SessionPoolManager:
    _sessions: Dict[str, UserSession]
    _max_sessions: int

    def get_session(self, session_id: str) -> Optional[UserSession]:
        pass
```

### Async/Await 模式

**广泛使用异步编程：**
```python
# 异步函数
async def initialize():
    await browser.start()

# 异步上下文管理器
async with session_manager.get_session(id) as session:
    await session.navigate(url)

# 后台任务
asyncio.create_task(health_check_loop())
```

### Dataclass 模式

**使用 @dataclass 定义数据模型：**
```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class UserSession:
    session_id: str
    user_id: str
    browser_instance: Optional[BrowserInstance] = None

    def __post_init__(self):
        # 验证逻辑
        if not self.session_id:
            raise ValueError("session_id required")
```

### 错误处理

**使用自定义异常：**
```python
# 定义在 src/models.py
class ResourceExhaustedError(Exception):
    """资源耗尽错误"""
    pass

class SessionNotFoundError(Exception):
    """会话未找到错误"""
    pass

# 使用
if len(self._sessions) >= self._max_sessions:
    raise ResourceExhaustedError("Max sessions reached")
```

### 日志记录

**使用标准 logging 模块：**
```python
import logging

logger = logging.getLogger(__name__)

logger.info(f"✅ Session created: {session_id}")
logger.warning(f"⚠️ Session idle timeout: {session_id}")
logger.error(f"❌ Browser launch failed: {error}")
```

## 配置管理

### 环境变量

在 `.env` 文件中配置（参考 `.env.example`）：

**LLM 配置：**
```bash
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.openai.com/v1
```

**部署模式：**
```bash
DEPLOYMENT_MODE=local          # local | docker-aio | docker-distributed
BROWSER_MODE=local             # local | docker
```

**资源限制：**
```bash
MAX_SESSIONS=10                # 最大并发会话数
IDLE_TIMEOUT_SECONDS=300       # 空闲超时（秒）
```

**浏览器配置：**
```bash
CDP_PORT=19222                 # CDP 端口（非标准端口）
CDP_BIND_ADDRESS=127.0.0.1     # CDP 绑定地址
HEADLESS=false                 # 是否无头模式
```

**存储配置：**
```bash
PROFILE_STORAGE=/path/to/profiles  # 配置文件存储路径
LOG_LEVEL=INFO                     # 日志级别
```

**代理配置：**
```bash
PROXY_LIST=http://proxy1:port,http://proxy2:port
PROXY_LIST_FILE=/path/to/proxies.txt
```

### 部署模式

**1. 本地开发模式：**
```bash
# 设置环境变量
export DEPLOYMENT_MODE=local
export BROWSER_MODE=local

# 启动 API
python -m uvicorn src.api:app --reload --port 8000
```

**2. Docker All-in-One 模式：**
```bash
# 构建镜像
docker build -f docker/Dockerfile -t agent-browser:latest .

# 启动容器
docker run -p 8000:8000 \
  -e OPENAI_API_KEY=sk-xxx \
  -v $(pwd)/docker/data/profiles:/app/profiles \
  agent-browser:latest
```

**3. Docker 分布式模式：**
```bash
# 使用 docker-compose
docker-compose -f docker/docker-compose.yml up -d
```

## 测试

### 测试组织

测试位于 `/tests/` 目录：

- `test_api.py` - API 端点测试
- `test_anti_detection.py` - 反检测验证测试
- `test_distributed.py` - 分布式部署测试
- `test_profile_manager.py` - 配置文件管理测试
- `test_persistent_profile.py` - 持久化会话测试
- `performance_test.py` - 性能基准测试
- `test_zhipin.py` - 真实场景集成测试（Boss直聘）

### 运行测试

**运行所有测试：**
```bash
pytest tests/
```

**运行特定测试：**
```bash
pytest tests/test_api.py
pytest tests/test_anti_detection.py -v
```

**运行性能测试：**
```bash
python tests/performance_test.py
python tests/quick_perf_test.py
```

### 测试框架

使用 pytest 与异步支持：
```python
import pytest
import httpx

@pytest.mark.asyncio
async def test_create_session():
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8000/sessions/create",
            json={"user_id": "test_user"}
        )
        assert response.status_code == 200
```

## 常见开发任务

### 添加新的 API 端点

1. 在 `src/models.py` 中定义请求/响应模型：
```python
@dataclass
class NewFeatureRequest:
    param1: str
    param2: Optional[int] = None
```

2. 在 `src/api.py` 中添加端点：
```python
@app.post("/new-feature")
async def new_feature(request: NewFeatureRequest):
    # 实现逻辑
    return {"status": "success"}
```

3. 在 `tests/test_api.py` 中添加测试

### 修改会话管理逻辑

主要文件：`src/session/pool_manager.py`

**示例：调整空闲超时逻辑**
```python
# 在 SessionPoolManager 类中
async def _idle_cleanup_loop(self):
    while True:
        await asyncio.sleep(60)  # 检查间隔
        for session_id, session in list(self._sessions.items()):
            if session.is_idle() and session.idle_time > self._idle_timeout:
                await self.delete_session(session_id)
```

### 增强反检测功能

**关键文件：**
- `src/browser/stealth_launcher.py` - 浏览器启动参数
- `src/browser/human_behavior.py` - 行为模拟

**⚠️ 重要：** 修改反检测功能时要格外小心，错误的配置可能导致检测失败。

**示例：添加新的行为模拟**
```python
# 在 HumanBehaviorSimulator 类中
async def simulate_reading(self, page):
    """模拟阅读行为"""
    # 随机滚动
    for _ in range(random.randint(2, 5)):
        await self.random_scroll(page)
        await asyncio.sleep(random.uniform(1.0, 3.0))
```

### 添加新的 Agent 能力

主要文件：`src/agent/runner.py`

**示例：添加自定义 Agent 任务**
```python
async def run_custom_agent_task(
    browser: Browser,
    task_description: str,
    custom_params: Dict
) -> Dict:
    agent = Agent(
        task=task_description,
        llm=get_llm(),
        browser=browser
    )
    result = await agent.run()
    return {"result": result}
```

### 使用浏览器配置文件

主要文件：`src/session/profile_manager.py`

**创建持久化配置文件：**
```python
profile_manager = ProfileManager(storage_path="/path/to/profiles")
profile = await profile_manager.create_profile(
    user_id="user123",
    fingerprint_config={...}
)
```

**加载现有配置文件：**
```python
profile = await profile_manager.load_profile(user_id="user123")
```

## 重要注意事项

### 🔒 反检测敏感性

**不要破坏反检测功能：**
- 不要修改 CDP 端口（19222）
- 不要移除 CloakBrowser 启动参数
- 不要频繁 attach/detach CDP 会话
- 不要在浏览器中注入明显的自动化标记

**验证反检测：**
```bash
# 运行反检测测试
pytest tests/test_anti_detection.py
```

### 🔐 会话隔离要求

**确保用户隔离：**
- 每个会话必须有独立的 browser profile
- 每个会话必须有独立的 fingerprint
- 每个会话必须有独立的 proxy（如果使用）
- 不要在会话之间共享 cookies 或 localStorage

### 💾 资源管理

**防止资源泄漏：**
- 始终在 `finally` 块中清理资源
- 使用异步上下文管理器
- 实现空闲超时机制
- 监控浏览器实例数量

**示例：**
```python
try:
    browser = await launch_browser()
    # 使用浏览器
finally:
    await browser.close()
```

### 📝 中文文档上下文

**项目文档主要使用中文：**
- README.md 是中文
- 代码注释主要是中文
- 日志消息使用中文和 emoji
- API 文档使用中文

**编写代码时：**
- 代码本身使用英文（变量名、函数名、类名）
- 注释和文档字符串可以使用中文
- 日志消息建议使用中文 + emoji 提高可读性

## 技术栈参考

**核心依赖：**
- `fastapi` - Web 框架
- `uvicorn[standard]` - ASGI 服务器
- `browser-use==0.12.2` - AI agent 浏览器自动化
- `cloakbrowser` - 反检测 Chromium
- `patchright` - Playwright fork with patches
- `rebrowser-playwright` - 额外的反检测补丁
- `langchain-anthropic` - Anthropic LLM 集成
- `langchain-openai` - OpenAI LLM 集成
- `docker` - Docker 客户端库
- `browserforge` - 指纹生成

**完整依赖列表：** 参见 `requirements.txt`

## 参考项目与生态系统

agent-browser 项目不是孤立存在的，它与多个开源项目有重要的依赖和集成关系。理解这些关系有助于开发者更好地使用和扩展 agent-browser。

### 生态系统关系图

```
┌─────────────────────────────────────────────────────────┐
│                    openclaw                             │
│         (个人 AI 助手框架 - TypeScript)                  │
│  统一网关连接 AI 模型和 25+ 消息渠道                      │
│  (WhatsApp, Telegram, Slack, Discord, etc.)            │
└────────────────────┬────────────────────────────────────┘
                     │ skill 插件集成
                     │
┌────────────────────▼────────────────────────────────────┐
│                agent-browser                            │
│         (反检测浏览器自动化平台 - Python)                 │
│  5层反检测栈 + 多用户会话隔离 + REST API                  │
└────────────────────┬────────────────────────────────────┘
                     │ 直接依赖
                     │
┌────────────────────▼────────────────────────────────────┐
│                 browser-use                             │
│         (AI 驱动的浏览器自动化库 - Python)                │
│  Agent/Browser/Tools 抽象 + LLM 集成                     │
└─────────────────────────────────────────────────────────┘

                     平行参考
┌─────────────────────────────────────────────────────────┐
│            agent-browser-clawdbot                       │
│         (快速浏览器自动化工具 - CLI)                      │
│  可访问性树快照 + 确定性元素引用（refs）                   │
└─────────────────────────────────────────────────────────┘
```

### browser-use - 核心依赖库

**项目地址：** https://github.com/browser-use/browser-use

**简介：**
browser-use 是一个 AI 驱动的浏览器自动化库，让 LLM 能够控制浏览器执行复杂任务。它提供了简洁的 Agent/Browser/Tools 抽象，支持多种 LLM 提供商（OpenAI、Anthropic、Google 等）。

**与 agent-browser 的关系：**
- **直接依赖**：agent-browser 在 `requirements.txt` 中指定了 `browser-use==0.12.2`
- **核心集成点**：`src/agent/runner.py` 使用 browser-use 的 Agent 类执行 AI 任务
- **分工明确**：
  - browser-use 提供：AI agent 能力、LLM 集成、浏览器控制抽象
  - agent-browser 增加：反检测栈、多用户隔离、REST API、生产部署

**关键 API 使用示例：**
```python
from browser_use import Agent, Browser
from langchain_openai import ChatOpenAI

# 在 src/agent/runner.py 中的典型用法
async def run_agent_task(
    browser: Browser,
    task: str,
    llm: ChatOpenAI
) -> Dict:
    agent = Agent(
        task=task,
        llm=llm,
        browser=browser
    )
    result = await agent.run()
    return {"result": result}
```

**browser-use 核心功能：**
- **Agent 系统**：自主规划和执行浏览器任务
- **多 LLM 支持**：ChatOpenAI、ChatAnthropic、ChatGoogle、ChatBrowserUse
- **自定义工具**：通过 `@tools.action` 装饰器扩展能力
- **CLI 工具**：`browser-use` 命令行工具用于快速测试
- **Claude Code Skill**：可作为 Claude Code 的 skill 使用

**文档链接：**
- 官方文档：https://docs.browser-use.com
- 云服务：https://cloud.browser-use.com
- 示例代码：https://github.com/browser-use/browser-use/tree/main/examples

**开发建议：**
- 查看 browser-use 的 examples 目录了解最佳实践
- 使用 browser-use 的 Tools 系统扩展 agent 能力
- 关注 browser-use 版本更新，及时升级以获得新功能

### openclaw - AI 助手框架

**项目地址：** https://github.com/openclaw/openclaw

**简介：**
openclaw 是一个个人 AI 助手框架，运行在本地设备上，作为 AI 模型和 25+ 消息渠道之间的统一网关。它采用插件架构，支持浏览器控制、shell 执行、多代理编排等能力。

**与 agent-browser 的关系：**
- **可选集成**：agent-browser 可以作为 openclaw 的 skill 插件
- **集成文件**：`skills/agent-browser/SKILL.md` 定义了 skill 接口
- **使用场景**：通过 openclaw 的多个消息渠道调用 agent-browser 能力

**openclaw 核心架构：**
- **单一网关模式**：一个长期运行的 Gateway 进程
- **统一 WebSocket API**：所有客户端和渠道通过 WebSocket 连接
- **插件系统**：
  - Channel 插件：添加消息平台（Matrix、Teams、Zalo 等）
  - Provider 插件：添加 AI 模型提供商
  - Memory 插件：可插拔的记忆后端
  - Skill 插件：自定义工具和能力

**agent-browser 作为 openclaw skill：**

1. **安装 skill：**
```bash
# 将 agent-browser skill 复制到 openclaw skills 目录
cp -r skills/agent-browser ~/.openclaw/skills/
```

2. **在 openclaw 中使用：**
```typescript
// openclaw 会自动加载 skill
// 用户可以通过任何连接的消息渠道调用
// 例如在 Telegram 中：
// "使用 agent-browser 帮我登录 Boss直聘"
```

3. **skill 配置：**
```markdown
# skills/agent-browser/SKILL.md
---
name: agent-browser
description: 反检测浏览器自动化，支持高防护网站
---

## 能力
- 创建隔离的浏览器会话
- 执行 AI 驱动的浏览器任务
- 绕过反爬虫检测系统
```

**openclaw 设计哲学：**
- **本地优先**：运行在用户自己的设备上，保护隐私
- **编排优先**：专注于 prompts、tools、protocols 和集成
- **安全第一**：skill 静态分析、权限控制、速率限制
- **强默认值**：开箱即用，但不限制扩展能力

**文档链接：**
- GitHub：https://github.com/openclaw/openclaw
- 插件开发：查看 openclaw 仓库的 `src/plugin-sdk/` 目录
- Skill 发布：https://clawhub.ai

**集成建议：**
- 将 agent-browser 作为 openclaw skill 可以通过多个渠道访问
- 使用 openclaw 的路由系统智能分发浏览器任务
- 利用 openclaw 的 memory 系统持久化会话状态

### agent-browser-clawdbot - 替代方案参考

**项目地址：** https://clawhub.ai/matrixy/agent-browser-clawdbot

**简介：**
agent-browser-clawdbot 是一个快速浏览器自动化工具，采用可访问性树快照 + 确定性元素引用（refs）的技术路线。它是 ClawHub 上的一个 skill，提供了与 agent-browser 不同的浏览器自动化方式。

**核心特点：**
- **快照-交互-重复循环**：
  1. 使用 `-i --json` 获取页面快照和元素 refs
  2. 解析 refs（如 `@e2`, `@e3`）
  3. 使用 refs 执行交互（click、fill、type 等）
  4. 页面变化后重新快照

- **确定性元素选择**：通过 refs 而非 CSS 选择器或 XPath
- **会话隔离**：通过 `--session` 参数支持并行测试
- **网络控制**：支持阻止或模拟 API 调用
- **多标签和 iframe 支持**

**与 agent-browser 的对比：**

| 特性 | agent-browser | agent-browser-clawdbot |
|------|---------------|------------------------|
| 技术路线 | AI agent 驱动（browser-use） | 可访问性树 + refs |
| 部署方式 | REST API 服务 | CLI 工具 |
| 反检测能力 | 5层反检测栈 | 基础反检测 |
| 多用户支持 | ✅ 会话池管理 | ❌ 单用户 |
| 适用场景 | 高防护网站、生产环境 | 快速原型、SPA 应用 |
| 学习曲线 | 中等（需要理解架构） | 低（CLI 直接使用） |

**使用示例：**
```bash
# 安装
npm install -g agent-browser

# 基本工作流
agent-browser open https://example.com
agent-browser state -i --json  # 获取元素 refs
agent-browser click @e5         # 点击元素
agent-browser fill @e3 "text"   # 填充表单
agent-browser screenshot page.png
agent-browser close
```

**何时使用 agent-browser-clawdbot：**
- 快速原型开发和测试
- 不需要反检测的场景
- 单用户脚本自动化
- 需要精确控制元素选择的场景

**何时使用 agent-browser：**
- 需要绕过反爬虫系统
- 多用户并发场景
- 生产环境部署
- 需要 REST API 集成

**文档链接：**
- ClawHub 页面：https://clawhub.ai/matrixy/agent-browser-clawdbot
- 安装：`npm install -g agent-browser`

### 技术栈对比总结

| 项目 | 语言 | 类型 | 核心价值 |
|------|------|------|----------|
| browser-use | Python | 库 | AI agent 浏览器自动化抽象 |
| agent-browser | Python | 服务 | 反检测 + 多用户 + 生产部署 |
| openclaw | TypeScript | 框架 | AI 助手网关 + 多渠道集成 |
| agent-browser-clawdbot | CLI | 工具 | 快速浏览器自动化原型 |

### 开发者建议

**学习路径：**
1. 先学习 browser-use 的基本用法和 API
2. 理解 agent-browser 如何在 browser-use 基础上增加反检测
3. 如果需要多渠道访问，研究 openclaw 集成
4. 参考 agent-browser-clawdbot 的 refs 方案作为备选

**扩展方向：**
- 在 `src/agent/runner.py` 中使用 browser-use 的 Tools 系统添加自定义能力
- 将 agent-browser 发布为 openclaw skill 到 ClawHub
- 结合 agent-browser-clawdbot 的 refs 方案优化元素选择
- 贡献反检测补丁回 browser-use 社区

**社区资源：**
- browser-use Discord：https://link.browser-use.com/discord
- openclaw GitHub Discussions：https://github.com/openclaw/openclaw/discussions
- ClawHub：https://clawhub.ai（发布和发现 skills）

## 相关文档

- `README.md` - 项目概述和快速开始
- `docs/ARCHITECTURE.md` - 详细架构设计
- `docs/API_COMPARISON.md` - API 版本对比
- `docs/DEPLOYMENT.md` - 部署指南
- `docker/BUILD.md` - Docker 构建说明

## 开发工作流

1. **设置开发环境：**
```bash
# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 文件
```

2. **本地开发：**
```bash
# 启动 API（热重载）
uvicorn src.api:app --reload --port 8000
```

3. **运行测试：**
```bash
# 运行所有测试
pytest tests/

# 运行特定测试
pytest tests/test_api.py -v
```

4. **构建 Docker 镜像：**
```bash
# All-in-One 镜像
docker build -f docker/Dockerfile -t agent-browser:latest .

# API 镜像
docker build -f docker/Dockerfile.api -t agent-browser-api:latest .

# Browser 镜像
docker build -f docker/Dockerfile.browser -t agent-browser-chromium:latest .
```

5. **部署：**
```bash
# Docker Compose
docker-compose -f docker/docker-compose.yml up -d
```

---

**最后更新：** 2026-03-23
