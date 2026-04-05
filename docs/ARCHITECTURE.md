# Agent Browser 架构设计

## 概览

双层架构：Skill 层（LocalCDPBackend / RemoteAPIBackend）+ 服务端（FastAPI + SessionPoolManager）。

```
┌─────────────────────────────────────────────────────────────┐
│                     SKILL.md (Facade)                        │
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
                               │    FastAPI 服务端 (api.py)    │
                               │    SessionPoolManager         │
                               │    (内部运行 LocalCDPBackend) │
                               └──────────────────────────────┘
```

**核心设计原则：**
- **LocalCDPBackend 是唯一浏览器操作核心**：所有浏览器逻辑只实现一次
- **RemoteAPIBackend 是 HTTP 传输层**：零业务逻辑，只做序列化/反序列化
- **FastAPI 服务端**：对外暴露 REST API，内部委托给 LocalCDPBackend

## 6 层反检测栈

| 层 | 组件 | 功能 |
|---|------|------|
| 1 | CloakBrowser | C++ 编译级指纹伪装（33 项补丁） |
| 2 | patchright | 驱动级 CDP 修补（移除 `__playwright__binding__`） |
| 3 | rebrowser-patches | Runtime.Enable 泄漏修复（addBinding 模式） |
| 4 | 非标准端口 19222 | 绑定 127.0.0.1，连接隐匿 |
| 5 | BrowserDaemon | 持久单 CDP 会话，禁止频繁 attach/detach |
| 6 | StealthEnhancer | 人类延迟 + 贝塞尔鼠标 + 逐字输入 + 定时器噪声 |

## 模式矩阵

| 调用模式 | 浏览器模式 | 后端实现 | 智能模式 | 数据流 |
|---------|-----------|---------|---------|--------|
| CLI | local | LocalCDPBackend (daemon) | LLM | Agent → Python API → CDP |
| CLI | local | LocalCDPBackend | Agent | Agent → run_task → browser-use → CDP |
| API | local | RemoteAPIBackend → localhost FastAPI | LLM/Agent | Agent → HTTP → FastAPI → CDP |
| API | remote | RemoteAPIBackend → Gateway → Docker | LLM/Agent | Agent → HTTP → Gateway → Docker CDP |

## 核心组件

### 1. 数据模型 (src/models.py)

```python
class BrowserMode(str, Enum):
    LOCAL = "local"      # 本地浏览器
    DOCKER = "docker"    # Docker 容器浏览器

class BrowserInstance(BaseModel):
    instance_id: str
    mode: BrowserMode
    cdp_url: str         # ws://host:port
    profile_dir: str
    process: Optional[Any] = None      # 本地模式
    container_id: Optional[str] = None # Docker 模式

class UserSession:
    session_id: str
    user_id: str
    browser_instance: BrowserInstance
    tasks: Dict[str, Dict] = {}
    created_at: float
    last_activity: float
    task_lock: asyncio.Lock  # 防止空闲回收误删活跃任务
```

### 2. BrowserInstancePool (src/browser/instance_pool.py)

**职责**：管理浏览器实例生命周期，支持本地和 Docker 两种模式。

```python
async def allocate(self, session_id: str, profile_dir: str) -> BrowserInstance:
    """分配浏览器实例"""

async def release(self, session_id: str):
    """释放浏览器实例"""
```

### 3. SessionPoolManager (src/session/pool_manager.py)

**职责**：多用户会话隔离、Session 生命周期管理、任务调度、空闲超时回收。

```python
async def create_session(self, user_id: str, profile_config=None) -> tuple[str, Any]:
    """创建新会话，返回 (session_id, browser_node)"""

async def submit_task(self, session_id: str, task: str, llm_config: dict, max_steps: int) -> str:
    """提交任务到指定会话，返回 task_id"""

async def close_session(self, session_id: str):
    """关闭会话，释放资源"""
```

**空闲监控**（跳过有活跃任务的会话）：

```python
async def _idle_monitor(self):
    while True:
        await asyncio.sleep(60)
        for session_id, session in list(self.sessions.items()):
            if session.is_idle(self.idle_timeout):
                if session.task_lock.locked():
                    continue  # 有活跃任务，跳过
                await self.close_session(session_id)
```

### 4. API 层 (src/api.py)

**Session 管理 API**：

```python
POST   /sessions/create          # 创建会话
GET    /sessions/{session_id}    # 查询会话状态
DELETE /sessions/{session_id}    # 删除会话
GET    /sessions                 # 列出所有会话
```

**任务管理 API**：

```python
POST   /sessions/{session_id}/task              # 提交任务
GET    /sessions/{session_id}/tasks/{task_id}   # 查询任务状态
```

**原子操作 API（LLM ReAct 模式）**：

```python
GET/POST /sessions/{session_id}/snapshot  # 页面快照 + 元素 refs
POST     /sessions/{session_id}/navigate  # 导航
POST     /sessions/{session_id}/click     # 点击元素
POST     /sessions/{session_id}/fill      # 填充输入
POST     /sessions/{session_id}/scroll    # 滚动页面
POST     /sessions/{session_id}/back      # 后退
```

**向后兼容 API**：

```python
POST   /tasks           # 自动创建临时 Session
GET    /tasks/{task_id} # 查询任务状态
```

### 5. LocalCDPBackend (skills/agent-browser/backends/local.py)

浏览器操作的唯一核心实现：

- `connect()` — 懒连接 CDP（如 CDP 不可达，自动启动 CloakBrowser）
- `create_session()` — 创建独立浏览器上下文 + Profile
- `get_page()` — 获取或创建 Playwright Page
- `snapshot()` — 注入 `data-ab-ref` 属性，返回元素列表
- `click()` / `fill()` — 通过 `[data-ab-ref="@eN"]` 精准定位元素

### 6. RemoteAPIBackend (skills/agent-browser/backends/remote.py)

零业务逻辑的 HTTP 传输层：

- 每个方法对应一个 FastAPI 端点的 HTTP 调用
- 支持 `X-API-Key` 认证头
- 将 `session_id` 映射到服务端会话

## 数据流

### 创建会话（CLI 模式）

```
1. 调用 create_session()
2. LocalCDPBackend.connect() → 检查 CDP 是否可达
3. 如不可达 → 自动启动 CloakBrowser（端口 19222）
4. playwright.connect_over_cdp() → 获取 Browser 对象
5. browser.new_context(user_data_dir=profile_dir) → 隔离 Session
6. 返回 session_id
```

### 创建会话（API 模式）

```
1. 调用 RemoteAPIBackend.create_session()
2. POST /sessions/create（带 X-API-Key）
3. FastAPI → SessionPoolManager.create_session(user_id=api_key)
4. SessionPoolManager → BrowserInstancePool.allocate()
5. LocalCDPBackend（服务端）→ CDP 连接
6. 返回 session_id
```

### 元素操作（data-ab-ref 机制）

```
1. snapshot() → JS 注入 data-ab-ref="@e0", "@e1"... 到 DOM 元素
2. 返回 {elements: [{ref: "@e0", text: "...", role: "a"}, ...]}
3. click("@e0") → query_selector('[data-ab-ref="@e0"]')
4. 元素稳定：属性绑定在 DOM 节点上，不受 DOM 变动影响
```

### 空闲回收流程

```
1. [后台] _idle_monitor 每 60 秒检查
2. 遍历所有 sessions
3. 检查 last_activity 时间
4. 超过 idle_timeout 且 task_lock 未锁定 → 关闭会话
5. task_lock 已锁定（有活跃任务）→ 跳过，下次再检查
```

## 隔离机制

### Profile 隔离

每个 Session 独立 Profile 目录：

```
/data/profiles/
├── user001_abc123/    # Session 1
│   ├── Default/
│   └── cookies.db
├── user002_def456/    # Session 2
│   ├── Default/
│   └── cookies.db
```

### 浏览器实例隔离

- **本地模式（CLI）**：BrowserDaemon 单例，每个 Session 独立 browser context
- **本地模式（API）**：FastAPI 内的 LocalCDPBackend，每个 Session 独立 context
- **Docker 模式**：每个 Session 独立容器（独立进程）

### 任务隔离

```python
session.tasks = {
    "task_abc": {"status": "running", "current_step": 3},
    "task_def": {"status": "completed", "result": "..."},
}
```

## 安全性

### 访问控制（已实现）

- ✅ API Key 认证（`X-API-Key` 请求头）
- ✅ Session 所有权验证（API Key 作为 user_id，只能访问自己创建的 Session）
- ✅ 单租户模式（未配置 API Key 时跳过所有权检查，向后兼容）

### 隔离保证

- ✅ Profile 目录隔离（文件系统级别）
- ✅ 浏览器 Context 隔离（Playwright BrowserContext）
- ✅ Cookie 隔离（独立 Profile）
- ✅ 指纹隔离（CloakBrowser 随机化）

## 资源管理

### 并发限制

```python
MAX_SESSIONS = 10  # 最大并发会话数

if len(self.sessions) >= self.max_concurrent:
    raise ResourceExhaustedError("Max concurrent sessions reached")
```

### 超时回收

```python
IDLE_TIMEOUT_SECONDS = 1800  # 30 分钟

if session.is_idle(self.idle_timeout) and not session.task_lock.locked():
    await self.close_session(session_id)
```

## 部署模式

### All-in-One 模式

```
┌─────────────────────────────────────┐
│         Docker Container            │
│  ┌──────────────────────────────┐   │
│  │  FastAPI + SessionPoolManager│   │
│  └──────────────────────────────┘   │
│  ┌──────────────────────────────┐   │
│  │  BrowserInstancePool (local) │   │
│  └──────────────────────────────┘   │
│  ┌──────────────────────────────┐   │
│  │  CloakBrowser (CDP :19222)   │   │
│  └──────────────────────────────┘   │
└─────────────────────────────────────┘
```

### Distributed 模式

```
┌─────────────────────────────────────┐
│      API Container                  │
│  ┌──────────────────────────────┐   │
│  │  FastAPI + SessionPoolManager│   │
│  └──────────────────────────────┘   │
│  ┌──────────────────────────────┐   │
│  │ BrowserInstancePool (docker) │   │
│  └──────────────────────────────┘   │
└─────────────────────────────────────┘
              ↓ Docker API
┌─────────────────────────────────────┐
│   Browser Container (per Session)   │
│  - CloakBrowser                     │
│  - CDP :19222                       │
└─────────────────────────────────────┘
```

### CLI 本地模式（Skill 直连）

```
Agent（Claude Code）
    ↓
LocalCDPBackend
    ↓
BrowserDaemon（单例）
    ↓
CloakBrowser CDP :19222（持久连接）
```

## 扩展性

- **All-in-One 模式**：单容器多会话（10-50 并发）
- **Distributed 模式**：多容器独立会话（50+ 并发）
- **未来扩展**：负载均衡、Prometheus 监控、自动扩缩容

## 已完成里程碑

### Phase 1
- ✅ 多用户会话隔离
- ✅ 本地浏览器模式（CLI 直连 + API 服务端）
- ✅ 向后兼容 API

### Phase 2
- ✅ Docker 浏览器模式
- ✅ 独立浏览器容器
- ✅ 跨容器通信（HTTP REST）

### Phase 3
- ✅ API Key 认证和 Session 所有权授权
- ✅ 元素稳定引用（data-ab-ref DOM 属性）
- ✅ 空闲回收安全保护（跳过活跃任务会话）
- ✅ 自动浏览器启动（CDP 健康检查 + 子进程）
- [ ] 任务队列和优先级
- [ ] Prometheus 监控指标
- [ ] 多节点部署
