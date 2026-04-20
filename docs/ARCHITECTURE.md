# Stealth Browser 架构设计

## 概览

三层架构：Skill 层（模式路由）+ StealthMiddleware（集中隐匿）+ 后端层（LocalCDPBackend / ExtensionBackend / RemoteAPIBackend）+ 服务端（FastAPI + Gateway + SessionPoolManager）。

```
┌─────────────────────────────────────────────────────────────────┐
│                     SKILL.md (Facade)                            │
│          模式检测 + ReAct/Agent 路由                              │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│                     main.py (API)                                │
│     _ensure_backend() 路由 + run_task() 智能模式                 │
└─────────────┬───────────────────────────┬───────────────────────┘
              │                           │
┌─────────────▼──────────┐  ┌────────────▼──────────┐  ┌──────────▼────────────┐
│   LocalCDPBackend      │  │   ExtensionBackend    │  │  RemoteAPIBackend      │
│   (CloakBrowser)       │  │   (Chrome Extension)  │  │  (HTTP 传输适配器)      │
│  ├─ BrowserDaemon      │  │  ├─ WebSocket         │  │  ├─ aiohttp REST        │
│  ├─ StealthEnhancer    │  │  ├─ chrome.debugger   │  │  ├─ X-API-Key 认证      │
│  └─ browser-use Agent  │  │  └─ 自然指纹继承      │  │  └─ session_id 映射      │
└─────────────┬──────────┘  └────────────┬──────────┘  └──────────┬────────────┘
              │                      │                        │
              └──────────────────────┼────────────────────────┘
                                     │
┌────────────────────────────────────▼────────────────────────────────────┐
│                    StealthMiddleware (stealth_browser/stealth/middleware.py)         │
│     pre/post 延迟 + 贝塞尔鼠标 + 人类打字 + 熔断器 (per-session)         │
└────────────────────────────────────────┬───────────────────────────────┘
                                     │
                  ┌────────────────────┼────────────────────┐
                  │                    │                    │
       ┌─────────▼────────┐  ┌───────▼──────────┐  ┌─────▼────────────┐
       │  BrowserDaemon   │  │  Pipeline Engine  │  │  Explore Module   │
       │  (持久化连接)     │  │  (v2.3)           │  │  (站点探索+生成)   │
       └──────────────────┘  │  ├─ classifier    │  └──────────────────┘
                            │  ├─ fallback      │
                            │  ├─ debugger      │
                            │  └─ telemetry     │
                            └─────────────────┘
```

**核心设计原则：**
- **LocalCDPBackend 是唯一浏览器操作核心**：所有浏览器逻辑只实现一次
- **ExtensionBackend 是自然指纹替代方案**：操作用户真实 Chrome，无 Extension 时自动回退到 LocalCDPBackend
- **RemoteAPIBackend 是 HTTP 传输层**：零业务逻辑，只做序列化/反序列化
- **StealthMiddleware 是集中隐匿层**：自动包装所有浏览器操作，熔断器防止级联失败
- **FastAPI 服务端**：对外暴露 REST API，内部委托给 LocalCDPBackend
- **Gateway 模块**：多用户 API Key 认证 + 浏览器实例池管理

## 7 层反检测栈

| 层 | 组件 | 功能 | 实现位置 |
|---|------|------|----------|
| 1 | CloakBrowser | C++ 编译级指纹伪装（33 项补丁） | `stealth_browser/browser/stealth_launcher.py` |
| 2 | patchright | 驱动级 CDP 修补（移除 `__playwright__binding__`） | `stealth_browser/browser/stealth_launcher.py` |
| 3 | rebrowser-patches | Runtime.Enable 泄漏修复（addBinding 模式） | 环境变量 `REBROWSER_PATCHES_RUNTIME_FIX_MODE` |
| 4 | 非标准端口 19222 | 绑定 127.0.0.1，连接隐匿 | `stealth_browser/browser/stealth_launcher.py` |
| 5 | BrowserDaemon | 持久单 CDP 会话，禁止频繁 attach/detach | `stealth_browser/browser/daemon.py` |
| 6 | StealthEnhancer | 人类延迟 + 贝塞尔鼠标 + 逐字输入 + 定时器噪声 | `stealth_browser/stealth/enhancer.py` |
| 7 | **StealthMiddleware** | **集中隐匿层：自动 pre/post 延迟 + 熔断器** | `stealth_browser/stealth/middleware.py` |

## 模式矩阵

| 调用模式 | 浏览器模式 | 后端实现 | 智能模式 | 数据流 |
|---------|-----------|---------|---------|--------|
| CLI | local | LocalCDPBackend (daemon) | LLM | Agent → Python API → CDP |
| CLI | extension | ExtensionBackend (Chrome) | LLM | Agent → WS → chrome.debugger → CDP |
| CLI | local | LocalCDPBackend | Agent | Agent → run_task → browser-use → CDP |
| API | local | RemoteAPIBackend → localhost FastAPI | LLM/Agent | Agent → HTTP → FastAPI → CDP |
| API | remote | RemoteAPIBackend → Gateway → Docker | LLM/Agent | Agent → HTTP → Gateway → Docker CDP |

## 核心组件

### 1. 数据模型 (stealth_browser/models.py)

```python
class BrowserMode(str, Enum):
    LOCAL = "local"        # 本地 CloakBrowser
    EXTENSION = "extension" # Chrome Extension
    REMOTE = "remote"      # 远程 Docker

class BrowserInstance(BaseModel):
    instance_id: str
    mode: BrowserMode
    cdp_url: str
    profile_dir: str
    process: Optional[Any] = None
    container_id: Optional[str] = None

class UserSession:
    session_id: str
    user_id: str
    browser_instance: BrowserInstance
    tasks: Dict[str, Dict] = {}
    created_at: float
    last_activity: float
    task_lock: asyncio.Lock
```

### 2. 后端抽象层 (stealth_browser/browser/__init__.py)

```python
class BrowserBackend(ABC):
    """后端抽象基类"""
    async def connect(self): ...
    async def disconnect(self): ...
    async def create_session(self, session_id: str) -> BrowserPageHandle: ...
    async def delete_session(self, session_id: str): ...
    async def get_page(self, session_id: str) -> BrowserPageHandle: ...

class BrowserPageHandle(ABC):
    """页面句柄抽象"""
    async def goto(self, url: str): ...
    async def snapshot(self) -> dict: ...
    async def click(self, ref: str): ...
    async def fill(self, ref: str, text: str): ...
    async def scroll(self, direction: str, amount: int): ...
    async def evaluate(self, expression: str) -> Any: ...
    # ... 更多原子操作
```

### 2.1 LocalCDPBackend (stealth_browser/browser/local.py)

浏览器操作的唯一核心实现：

- `connect()` — 懒连接 CDP（如 CDP 不可达，自动启动 CloakBrowser）
- `create_session()` — 创建独立浏览器上下文 + Profile
- `get_page()` — 获取或创建 Playwright Page
- `snapshot()` — 注入 `data-ab-ref` 属性，返回元素列表
- `click()` / `fill()` — 通过 `[data-ab-ref="@eN"]` 精准定位元素
- Daemon 集成：持久连接 + 空闲断开

### 2.2 ExtensionBackend (stealth_browser/browser/extension.py)

Chrome Extension 后端，操作用户真实浏览器：

- 通过 WebSocket 连接本地 Chrome Extension
- 使用 `chrome.debugger` 协议附加到用户 Chrome 标签页
- 自然指纹（用户真实 Chromium，非 CloakBrowser 合成）
- 继承登录状态（cookies、session、localStorage）
- 无 Extension 时自动回退到 LocalCDPBackend

### 2.3 RemoteAPIBackend (stealth_browser/browser/remote.py)

零业务逻辑的 HTTP 传输层：

- 每个方法对应一个 FastAPI 端点的 HTTP 调用
- 支持 `X-API-Key` 认证头
- 将 `session_id` 映射到服务端会话

### 3. StealthMiddleware (stealth_browser/stealth/middleware.py)

第 7 层反检测，集中式隐匿中间件：

```python
class StealthMiddleware:
    """集中隐匿层：自动包装所有浏览器操作"""

    class CircuitState(Enum):
        CLOSED = "closed"   # 隐匿激活
        OPEN = "open"       # 隐匿禁用（连续失败）

    class _PerSessionCircuit:
        """per-session 熔断器"""
        threshold: int = 5       # 失败阈值
        failure_count: int = 0   # 当前失败次数
        state: CircuitState

    async def wrap(self, page_handle, action_type, fn, *args, **kwargs):
        """包装操作：pre 延迟 → 执行 → post 延迟"""
```

**操作分类：**

| 分类 | 操作 | pre 延迟 | post 延迟 |
|------|------|----------|-----------|
| stealth-wrapped | goto, click, fill, scroll | 0.5-1.5s / 0.1-0.3s | 0.3-1.0s |
| passthrough | evaluate, title, url | 0 | 0 |

**熔断器行为：**
- per-session 作用域（非全局），避免一个 session 影响其他 session
- 连续 5 次失败 → OPEN（禁用该 session 的隐匿，降级为透传）
- 新 session 自动 RESET（failure_count = 0）

### 4. Pipeline 引擎 v2.3 (stealth_browser/pipeline/)

YAML 声明式的适配器执行引擎：

```
┌─────────────────────────────────────────────────┐
│                Pipeline Executor                  │
│                                                   │
│  ┌─────────┐  ┌──────────┐  ┌────────────────┐  │
│  │ Template │→│  Steps   │→│  StealtHandle  │  │
│  │ Engine  │  │ (YAML)  │  │ (Middleware)   │  │
│  └─────────┘  └──────────┘  └───────┬────────┘  │
│                                      │           │
│                          ┌───────────┼───────────┐  │
│                          ▼           ▼           │  │
│                   ┌──────────────┐  ┌──────────┐  │  │
│                   │ Error Handler│  │Telemetry │  │  │
│                   │  ├─classifier│  │ (JSONL)  │  │  │
│                   │  ├─fallback  │  └──────────┘  │  │
│                   │  └─debugger  │               │  │
│                   └──────────────┘               │  │
└─────────────────────────────────────────────────┘
```

**子组件：**

| 组件 | 文件 | 功能 |
|------|------|------|
| 执行器 | `executor.py` | 入口，fail_fast 集成 fallback + telemetry |
| 步骤 | `steps.py` | navigate/click/fill/scroll/extract/type/select 等 |
| 模板 | `template.py` | 19 种过滤器 + 算术表达式 + 条件分支 |
| 错误 | `errors.py` | 6 类异常层次 + fix_hint 自动生成 |
| 分类器 | `classifier.py` | ErrorCategory 枚举 + 启发式匹配规则 |
| 恢复 | `fallback.py` | per-category 恢复策略（重验证/重试/标记） |
| 调试器 | `debugger.py` | 单步执行 + 断点 + step history + state inspection |
| 遥测 | `telemetry.py` | JSONL 统计 → `~/.stealth-browser/telemetry.jsonl` |

**错误分类体系：**

```python
class ErrorCategory(str, Enum):
    SELECTOR_DRIFT = "selector_drift"   # 选择器漂移
    TIMEOUT = "timeout"                 # 超时
    AUTH_FAILURE = "auth_failure"       # 认证失败
    NAVIGATION_ERROR = "navigation"     # 导航错误
    EXTRACTION_ERROR = "extraction"     # 提取错误
    UNKNOWN = "unknown"                 # 未知错误
```

### 5. 站点探索模块 (stealth_browser/explore/)

自动分析网站结构并生成 YAML 适配器：

```
目标网站 URL
     │
     ▼
┌─────────────┐   ┌──────────────┐   ┌───────────────┐
│  Explorer   │→  │   Analysis   │→  │   Cascade     │
│  (页面遍历)  │   │  (DOM 分析)  │   │ (选择器生成)  │
└─────────────┘   └──────────────┘   └───────┬───────┘
                                              │
                                              ▼
                                       ┌─────────────────┐
                                       │  Synthesizer    │
                                       │  (YAML 合成)    │
                                       └────────┬────────┘
                                                │
                                                ▼
                                       adapters/{site}.yaml
```

### 6. API 层 (stealth_browser/api/)

FastAPI REST API 服务，多租户会话管理：

| 文件 | 功能 |
|------|------|
| `app.py` | FastAPI 应用 + KeyManager 多 API Key 认证 |
| (SessionPoolManager) | 委托给 stealth_browser/session/pool_manager.py |

### 7. CLI 模块 (stealth_browser/cli/)

命令行接口：

| 文件 | 功能 |
|------|------|
| `main.py` | CLI 入口，命令分发 |
| `commands.py` | 命令定义（session/create/list/destroy 等） |
| `session_manager.py` | CLI 会话管理 |
| `session_store.py` | 文件系统持久化 |
| `output.py` | 输出格式化（JSON/table） |

### 8. LLM 工厂 (stealth_browser/llm/factory.py)

统一 LLM 创建接口：

```python
class LLMFactory:
    @staticmethod
    def create(provider="openai", model=None, ...):
        # 支持: openai, anthropic
        # 兼容: glm-5-turbo 等国产模型
        # 返回: browser-use ChatOpenAI 或 langchain ChatAnthropic
```

### 9. SessionPoolManager (stealth_browser/session/pool_manager.py)

**职责**：多用户会话隔离、Session 生命周期管理、任务调度、空闲超时回收。

```python
async def create_session(self, user_id: str, profile_config=None) -> tuple[str, Any]:
    """创建新会话，返回 (session_id, browser_node)"""

async def submit_task(self, session_id: str, task: str, llm_config: dict, max_steps: int) -> str:
    """提交任务到指定会话，返回 task_id"""

async def close_session(self, session_id: str):
    """关闭会话，释放资源"""
```

### 10. 共享状态层 (stealth_browser/state/store.py)

分布式协调的共享状态后端：

| 类 | 功能 |
|------|------|
| `StateStore` | 抽象基类，定义 hget/hset/allocate_pod/release_pod 等接口 |
| `K8sSharedState` | K8s ConfigMap 后端，CAS (Compare-And-Swap) 乐观并发控制 |
| `InMemoryStateStore` | 内存后端，单 replica / 本地开发用 |
| `create_state_store()` | 工厂函数，自动检测 K8s 环境选择后端 |

## 数据流

### 创建会话（CLI + local 模式）

```
1. 调用 create_session()
2. _ensure_backend() → 检测模式 → LocalCDPBackend
3. LocalCDPBackend.connect() → 检查 CDP 是否可达
4. 如不可达 → 自动启动 CloakBrowser（端口 19222）
5. playwright.connect_over_cdp() → 获取 Browser 对象
6. browser.new_context(user_data_dir=profile_dir) → 隔离 Session
7. StealthEnhancer.inject_timing_noise(page)
8. 返回 session_id
```

### 创建会话（CLI + extension 模式）

```
1. 调用 create_session(mode="extension")
2. _ensure_backend() → ExtensionBackend
3. desktop/cdp_discovery.py → 发现 Chrome Extension WebSocket
4. WebSocket 连接 Extension → chrome.debugger.attach
5. 返回 session_id（绑定到用户真实 Chrome 标签页）
6. 如无 Extension 可达 → 回退到 LocalCDPBackend
```

### 创建会话（API 模式）

```
1. 调用 RemoteAPIBackend.create_session()
2. POST /sessions/create（带 X-API-Key）
3. FastAPI → Gateway.key_store.verify(api_key)
4. Gateway → SessionPoolManager.create_session(user_id=api_key)
5. SessionPoolManager → BrowserInstancePool.allocate()
6. LocalCDPBackend（服务端）→ CDP 连接
7. 返回 session_id
```

### 元素操作（data-ab-ref 机制）

```
1. snapshot() → JS 注入 data-ab-ref="@e0", "@e1"... 到 DOM 元素
2. 返回 {elements: [{ref: "@e0", text: "...", role: "a"}, ...]}
3. click("@e0") → query_selector('[data-ab-ref="@e0"]')
4. StealthMiddleware.wrap() → pre_action("click") → 贝塞尔鼠标移动 → click → post_action("click")
5. 元素稳定：属性绑定在 DOM 节点上，不受 DOM 变动影响
```

### Pipeline 执行流程

```
1. 加载 adapters/{site}/{name}.yaml
2. validator.py → 5 项检查（必填字段/结构/step合法性/strategy/args类型）
3. template.render(context) → 变量替换 + 过滤器处理
4. executor.execute():
   for step in steps:
     try:
       StealthPageHandle.execute(step)
     except Exception as err:
       category = classifier.classify(err)
       if not fail_fast:
         result = fallback.handle(category, err, step, context)
         if result == FallbackResult.RECOVERED:
           continue  # 重试当前步骤
       raise  # 无法恢复或 fail_fast=True
5. telemetry.record(stats)  # 非阻塞
6. 返回结果
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

- **local 模式（CLI）**：BrowserDaemon 单例，每个 Session 独立 browser context
- **extension 模式（CLI）**：每个 Session 绑定到一个 Chrome 标签页
- **local 模式（API）**：FastAPI 内的 LocalCDPBackend，每个 Session 独立 context
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

- API Key 认证（`X-API-Key` 请求头）
- Session 所有权验证（API Key 作为 user_id，只能访问自己创建的 Session）
- 单租户模式（未配置 API Key 时跳过所有权检查，向后兼容）
- SSRF 防护（URL 白名单 + 内网地址拦截）
- CSS 选择器注入防护（`data-ab-ref` 属性 + `json.dumps()` 序列化）
- XSS 防护（文本内容通过 `json.dumps()` 安全转义后插入 JS）

### 隔离保证

- Profile 目录隔离（文件系统级别）
- 浏览器 Context 隔离（Playwright BrowserContext）
- Cookie 隔离（独立 Profile）
- 指纹隔离（CloakBrowser 随机化）
- 熔断器隔离（per-session，非全局）

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

### Daemon 生命周期

```python
# BrowserDaemon 双条件断开：
# 1. 无活跃 session（self._sessions 为空）
# 2. 超过 idle_timeout（默认 1800 秒）
# 两个条件同时满足才断开 CDP 连接
```

## 部署模式

### All-in-One 模式

```
┌─────────────────────────────────────┐
│         Docker Container            │
│  ┌──────────────────────────────┐   │
│  │  FastAPI + Gateway +          │   │
│  │  SessionPoolManager          │   │
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
│  │  FastAPI + Gateway +          │   │
│  │  SessionPoolManager          │   │
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
main.py → _ensure_backend()
    ↓
┌─────────────────────┬─────────────────────┐
│  LocalCDPBackend    │  ExtensionBackend    │
│  (CloakBrowser)     │  (Chrome Extension)  │
│         ↓            │         ↓            │
│  BrowserDaemon       │  chrome.debugger     │
│         ↓            │         ↓            │
│  CDP :19222          │  用户真实 Chrome       │
└─────────────────────┴─────────────────────┘
         ↓
StealthMiddleware (自动包装所有操作)
```

## 扩展性

- **All-in-One 模式**：单容器多会话（10-50 并发）
- **Distributed 模式**：多容器独立会话（50+ 并发）
- **Extension 模式**：零配置，利用用户现有浏览器
- **Pipeline 引擎**：YAML 声明式适配器，零 LLM 成本执行固定流程
- **Explore 模块**：自动生成适配器，降低适配器编写成本
- **未来扩展**：负载均衡、Prometheus 监控、自动扩缩容

## 已完成里程碑

### Phase 1: 核心框架
- 多用户会话隔离
- 本地浏览器模式（CLI 直连 + API 服务端）
- 向后兼容 API
- 7 层反检测栈

### Phase 2: 容器化部署
- Docker 浏览器模式
- 独立浏览器容器
- 跨容器通信（HTTP REST）

### Phase 3: 安全加固
- API Key 认证和 Session 所有权授权
- 元素稳定引用（data-ab-ref DOM 属性）
- 空闲回收安全保护（跳过活跃任务会话）
- 自动浏览器启动（CDP 健康检查 + 子进程）
- SSRF 防护 + XSS 防护 + 注入防护

### Phase 4: Pipeline 引擎 (v2.2-v2.3)
- 类型化错误层次（6 类异常 + fix_hint）
- YAML 适配器校验器（5 项检查）
- 模板引擎（19 种过滤器）
- 错误分类器 + 自动恢复策略
- 单步调试器 + 断点系统
- JSONL 遥测统计

### Phase 5: 探索与扩展
- 站点探索模块（DOM 分析 + 选择器生成 + 适配器合成）
- Chrome Extension 后端（自然指纹 + 登录继承）
- LLM 工厂（多提供商支持）
- CLI 模块完善
- Gateway 网关模块
- StealthMiddleware 集中隐匿层（第 7 层 + 熔断器）

### 待办
- [ ] 任务队列和优先级
- [ ] Prometheus 监控指标
- [ ] 适配器市场/共享平台

### Phase 6: 分布式部署 + 稳定性
- K8s Gateway API 路由 (Traefik + HTTPRoute)
- 共享状态层 (ConfigMap CAS + InMemory 双后端)
- 跨 Replica 会话恢复 (_recover_session)
- KeyManager 多 API Key 1-key-1-browser 绑定
- noVNC 网关代理 (b.stealth-browser.local)
- 周期性泄漏清理 + double allocation 防护
- SkillBrowser client (HTTP facade for Claude Code)
