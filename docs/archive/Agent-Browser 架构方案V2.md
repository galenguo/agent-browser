# Agent-Browser 架构方案V2

## 一、架构概览

### 当前架构分析

现有系统是单一的 FastAPI + browser-use 自主 agent 架构：
- FastAPI 提供 REST API
- SessionPoolManager 管理多用户会话
- BrowserInstancePool 支持本地/Docker 浏览器
- browser-use Agent 自主执行任务（内置 LLM）

### 重构目标架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        接入层 (Entry Layer)                      │
├─────────────────────────────┬───────────────────────────────────┤
│      API 模式 (自主)         │         CLI 模式 (被动)            │
│  FastAPI + LLM + Agent      │    Click CLI + 原子命令            │
│  (现有架构增强)              │    (新增，依赖调用方 LLM)          │
└─────────────────────────────┴───────────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────────┐
│                   核心能力层 (Core Layer)                        │
│  - BrowserController (browser-use 原子能力封装)                 │
│  - SessionManager (会话管理)                                     │
│  - BrowserPool (浏览器实例池)                                    │
└─────────────────────────────┬───────────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────────┐
│                 浏览器管理层 (Browser Layer)                     │
├─────────────────────────────┬───────────────────────────────────┤
│      本地浏览器              │         远程浏览器                 │
│  CloakBrowser 进程           │    Docker/K8s Pod 容器             │
└─────────────────────────────┴───────────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────────┐
│              远程浏览器控制模块 (Remote Control)                 │
│  - API Key 认证                                                  │
│  - 浏览器资源调度                                                │
│  - 连接管理                                                      │
└─────────────────────────────────────────────────────────────────┘
```

## 二、核心设计决策

### 2.1 两种接入模式对比

| 维度 | API 模式 | CLI 模式 |
|------|---------|---------|
| **定位** | 自主 Agent 服务 | 被动工具集 |
| **LLM** | 内置（FastAPI 进程） | 外部（调用方提供） |
| **browser-use** | 完整 Agent（自主决策） | 原子能力（Controller 方法） |
| **接口** | REST API | CLI 命令 |
| **会话** | 服务端管理 | 客户端管理（或无状态） |
| **适用场景** | 独立部署、多用户 SaaS | MCP 集成、本地开发 |


### 2.2 browser-use 原子能力提取

browser-use 框架提供两层能力：

**高层：Agent（自主决策）**
- 完整的 LLM 驱动循环
- 自动规划和执行
- 适合 API 模式

**底层：Controller + BrowserSession（原子操作）**
- 页面导航：`goto()`, `go_back()`, `go_forward()`
- 元素交互：`click()`, `input_text()`, `scroll_to_element()`
- 内容提取：`extract_content()`, `get_dom()`, `screenshot()`
- 页面状态：`wait_for_element()`, `get_url()`, `get_title()`
- 标签管理：`new_page()`, `switch_page()`, `close_page()`

**CLI 模式策略：**
- 封装 BrowserSession 的原子方法为 CLI 命令
- 每个命令对应一个原子操作
- 返回结构化 JSON 输出（便于 LLM 解析）

### 2.3 远程浏览器控制模块定位

**设计决策：作为独立的认证中间层**

```
┌──────────────────────────────────────────────────────────┐
│          Remote Browser Gateway (独立服务)               │
│  - API Key 验证                                          │
│  - 浏览器资源池管理                                       │
│  - 连接代理（CDP URL 分发）                              │
│  - 使用统计和限流                                         │
└──────────────────┬───────────────────────────────────────┘
                   │
        ┌──────────┴──────────┐
        │                     │
┌───────▼────────┐   ┌────────▼────────┐
│  API 模式调用   │   │  CLI 模式调用    │
│  (FastAPI)     │   │  (Click CLI)    │
└────────────────┘   └─────────────────┘
```

**职责边界：**
- Remote Gateway：认证、资源分配、连接管理
- API/CLI 模式：业务逻辑、任务执行
- 两者通过 CDP URL + Token 通信

**实现方式：**
- 独立 FastAPI 服务（端口 8001）
- 提供 `/allocate` 端点（返回 CDP URL + Token）
- 提供 `/release` 端点（释放资源）
- API/CLI 模式通过环境变量配置 Gateway 地址


## 三、CLI 模式详细设计

### 3.1 CLI 命令架构

**命令分组：**

```bash
agent-browser
├── session          # 会话管理
│   ├── create       # 创建会话
│   ├── list         # 列出会话
│   ├── info         # 查看会话详情
│   └── destroy      # 销毁会话
├── navigate         # 导航操作
│   ├── goto         # 跳转 URL
│   ├── back         # 后退
│   ├── forward      # 前进
│   └── refresh      # 刷新
├── interact         # 交互操作
│   ├── click        # 点击元素
│   ├── input        # 输入文本
│   ├── scroll       # 滚动
│   └── select       # 选择下拉框
├── extract          # 内容提取
│   ├── text         # 提取文本
│   ├── dom          # 获取 DOM
│   ├── screenshot   # 截图
│   └── elements     # 查找元素
└── page             # 页面管理
    ├── new          # 新建标签页
    ├── switch       # 切换标签页
    ├── close        # 关闭标签页
    └── list         # 列出所有标签页
```

### 3.2 基于 browser-use 的原子命令实现

**核心实现策略：**
1. 每个 CLI 命令对应 browser-use 的一个原子方法
2. 通过 BrowserSession 直接调用（不经过 Agent）
3. 返回 JSON 格式输出

**示例命令映射：**

```python
# CLI: agent-browser navigate goto --url https://example.com --session sess_123
# 实现：
async def goto(session_id: str, url: str):
    browser_session = get_session(session_id)
    page = browser_session.current_page
    await page.goto(url)
    return {"status": "success", "url": page.url}

# CLI: agent-browser interact click --selector "#button" --session sess_123
# 实现：
async def click(session_id: str, selector: str):
    browser_session = get_session(session_id)
    page = browser_session.current_page
    element = await page.query_selector(selector)
    await element.click()
    return {"status": "success", "selector": selector}

# CLI: agent-browser extract text --selector ".content" --session sess_123
# 实现：
async def extract_text(session_id: str, selector: str):
    browser_session = get_session(session_id)
    page = browser_session.current_page
    element = await page.query_selector(selector)
    text = await element.inner_text()
    return {"status": "success", "text": text}
```


### 3.3 会话管理方式

**两种会话模式：**

**模式 A：有状态会话（推荐）**
```bash
# 创建会话
agent-browser session create --name my-session --browser local
# 输出：{"session_id": "sess_abc123", "cdp_url": "http://localhost:19222"}

# 使用会话执行操作
agent-browser navigate goto --session sess_abc123 --url https://example.com
agent-browser interact click --session sess_abc123 --selector "#login"

# 销毁会话
agent-browser session destroy --session sess_abc123
```

**模式 B：无状态命令（简化）**
```bash
# 每次命令自动创建临时会话
agent-browser navigate goto --url https://example.com --browser remote --cdp-url http://remote:19222
# 命令结束后自动清理
```

**会话存储：**
- 本地模式：JSON 文件 `~/.agent-browser/sessions.json`
- 远程模式：内存存储（CLI 进程生命周期）

### 3.4 输出格式设计

**统一 JSON 输出：**
```json
{
  "status": "success|error",
  "data": {
    "url": "https://example.com",
    "title": "Example Domain",
    "elements": [...]
  },
  "metadata": {
    "session_id": "sess_abc123",
    "timestamp": 1234567890,
    "step_count": 5
  },
  "error": null
}
```

**步骤跟踪：**
```json
{
  "status": "success",
  "data": {"text": "Hello World"},
  "trace": {
    "step": 3,
    "action": "extract_text",
    "selector": ".content",
    "duration_ms": 120
  }
}
```


## 四、模块分层设计

### 4.1 核心能力层 (Core Layer)

**新增模块：BrowserController**

```python
# src/core/browser_controller.py
class BrowserController:
    """browser-use 原子能力封装，供 API 和 CLI 共用"""
    
    def __init__(self, browser_session: BrowserSession):
        self.session = browser_session
        self.page = browser_session.current_page
    
    # 导航
    async def goto(self, url: str) -> dict:
        await self.page.goto(url)
        return {"url": self.page.url, "title": await self.page.title()}
    
    async def go_back(self) -> dict:
        await self.page.go_back()
        return {"url": self.page.url}
    
    # 交互
    async def click(self, selector: str) -> dict:
        await self.page.click(selector)
        return {"selector": selector}
    
    async def input_text(self, selector: str, text: str) -> dict:
        await self.page.fill(selector, text)
        return {"selector": selector, "text": text}
    
    # 提取
    async def extract_text(self, selector: str) -> dict:
        element = await self.page.query_selector(selector)
        text = await element.inner_text() if element else None
        return {"selector": selector, "text": text}
    
    async def get_dom(self, simplified: bool = True) -> dict:
        # 使用 browser-use 的 DOM 压缩能力
        dom = await self.session.get_state()
        return {"dom": dom}
    
    async def screenshot(self, full_page: bool = False) -> dict:
        screenshot_bytes = await self.page.screenshot(full_page=full_page)
        return {"screenshot": screenshot_bytes, "format": "png"}
```

**职责：**
- 封装 browser-use 的原子操作
- 提供统一的返回格式
- API 和 CLI 模式共享此层


### 4.2 会话管理层重构

**统一会话接口：**

```python
# src/core/session_manager.py
class UnifiedSessionManager:
    """统一的会话管理，支持 API 和 CLI 模式"""
    
    def __init__(self, mode: Literal["api", "cli"]):
        self.mode = mode
        self.sessions: Dict[str, SessionContext] = {}
        self.browser_pool = BrowserInstancePool()
    
    async def create_session(
        self,
        session_id: str,
        browser_mode: Literal["local", "remote"],
        cdp_url: Optional[str] = None,
    ) -> SessionContext:
        """创建会话（API 和 CLI 共用）"""
        if browser_mode == "local":
            instance = await self.browser_pool.allocate_local(session_id)
            cdp_url = instance.cdp_url
        else:
            # 远程模式：使用提供的 CDP URL
            instance = RemoteBrowserInstance(cdp_url=cdp_url)
        
        browser_session = BrowserSession(
            browser_profile=BrowserProfile(cdp_url=cdp_url, is_local=True)
        )
        
        controller = BrowserController(browser_session)
        
        context = SessionContext(
            session_id=session_id,
            browser_instance=instance,
            browser_session=browser_session,
            controller=controller,
        )
        
        self.sessions[session_id] = context
        return context
    
    async def get_session(self, session_id: str) -> SessionContext:
        """获取会话"""
        if session_id not in self.sessions:
            raise SessionNotFoundError(f"Session {session_id} not found")
        return self.sessions[session_id]
    
    async def destroy_session(self, session_id: str):
        """销毁会话"""
        context = self.sessions.pop(session_id, None)
        if context:
            await context.browser_session.close()
            await self.browser_pool.release(context.browser_instance)

@dataclass
class SessionContext:
    """会话上下文"""
    session_id: str
    browser_instance: BrowserInstance
    browser_session: BrowserSession
    controller: BrowserController
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
```


### 4.3 CLI 层实现

**CLI 入口：**

```python
# src/cli/commands.py
import click
import json
import asyncio
from core.session_manager import UnifiedSessionManager

session_mgr = UnifiedSessionManager(mode="cli")

@click.group()
def cli():
    """Agent Browser CLI"""
    pass

# ===== 会话管理 =====
@cli.group()
def session():
    """会话管理"""
    pass

@session.command('create')
@click.option('--name', required=True)
@click.option('--browser', type=click.Choice(['local', 'remote']), default='local')
@click.option('--cdp-url', help='远程浏览器 CDP URL')
def session_create(name, browser, cdp_url):
    """创建会话"""
    result = asyncio.run(_create_session(name, browser, cdp_url))
    click.echo(json.dumps(result, ensure_ascii=False))

async def _create_session(name, browser, cdp_url):
    context = await session_mgr.create_session(name, browser, cdp_url)
    return {
        "status": "success",
        "data": {
            "session_id": context.session_id,
            "cdp_url": context.browser_instance.cdp_url
        }
    }

# ===== 导航操作 =====
@cli.group()
def navigate():
    """导航操作"""
    pass

@navigate.command('goto')
@click.option('--session', required=True)
@click.option('--url', required=True)
def navigate_goto(session, url):
    """跳转到 URL"""
    result = asyncio.run(_goto(session, url))
    click.echo(json.dumps(result, ensure_ascii=False))

async def _goto(session_id, url):
    context = await session_mgr.get_session(session_id)
    data = await context.controller.goto(url)
    return {"status": "success", "data": data}
```


### 4.4 API 层重构

**API 层增强（保持向后兼容）：**

```python
# src/api.py (重构后)
from core.session_manager import UnifiedSessionManager
from core.browser_controller import BrowserController

# 使用统一会话管理器
session_mgr = UnifiedSessionManager(mode="api")

@app.post("/sessions/create")
async def create_session(request: CreateSessionRequest):
    """创建会话（使用统一管理器）"""
    context = await session_mgr.create_session(
        session_id=f"{request.user_id}_{uuid4().hex[:8]}",
        browser_mode=request.browser_mode,
    )
    return {
        "session_id": context.session_id,
        "cdp_url": context.browser_instance.cdp_url
    }

@app.post("/sessions/{session_id}/task")
async def submit_task(session_id: str, request: SubmitTaskRequest):
    """提交任务（使用 browser-use Agent）"""
    context = await session_mgr.get_session(session_id)
    
    # API 模式：使用完整 Agent
    llm = create_llm(request.llm_config)
    agent = Agent(
        task=request.task,
        llm=llm,
        browser_session=context.browser_session,
        max_actions_per_step=5,
    )
    
    task_id = f"task_{uuid4().hex[:8]}"
    asyncio.create_task(_run_agent(session_id, task_id, agent))
    
    return {"task_id": task_id, "status": "running"}
```

**关键点：**
- API 模式继续使用 browser-use Agent（自主决策）
- CLI 模式使用 BrowserController（原子操作）
- 两者共享 UnifiedSessionManager 和 BrowserPool


## 五、远程浏览器控制模块设计

### 5.1 架构定位

**独立服务模式（推荐）：**

```
┌─────────────────────────────────────────────────────────┐
│  Remote Browser Gateway (端口 8001)                     │
│  - API Key 认证                                         │
│  - 浏览器资源池（Docker/K8s）                           │
│  - 连接分发                                             │
└─────────────────┬───────────────────────────────────────┘
                  │ HTTP API
        ┌─────────┴─────────┐
        │                   │
┌───────▼────────┐  ┌───────▼────────┐
│ API 模式       │  │ CLI 模式       │
│ (端口 8000)    │  │ (本地进程)     │
└────────────────┘  └────────────────┘
```

### 5.2 Gateway API 设计

```python
# src/gateway/api.py
from fastapi import FastAPI, Header, HTTPException
from typing import Optional

app = FastAPI(title="Remote Browser Gateway")

# API Key 存储（生产环境用数据库）
API_KEYS = {
    "key_abc123": {"user": "alice", "quota": 10},
    "key_def456": {"user": "bob", "quota": 5},
}

@app.post("/allocate")
async def allocate_browser(
    x_api_key: str = Header(..., alias="X-API-Key")
) -> dict:
    """分配浏览器资源"""
    # 验证 API Key
    if x_api_key not in API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    user_info = API_KEYS[x_api_key]
    
    # 检查配额
    if user_info["quota"] <= 0:
        raise HTTPException(status_code=429, detail="Quota exceeded")
    
    # 分配浏览器实例
    instance = await browser_pool.allocate(user=user_info["user"])
    
    # 生成访问 Token
    token = generate_token(instance.instance_id, x_api_key)
    
    return {
        "instance_id": instance.instance_id,
        "cdp_url": instance.cdp_url,
        "token": token,
        "expires_in": 3600
    }

@app.post("/release")
async def release_browser(
    instance_id: str,
    x_api_key: str = Header(..., alias="X-API-Key")
):
    """释放浏览器资源"""
    await browser_pool.release(instance_id)
    return {"status": "released"}
```


### 5.3 Gateway 与 API/CLI 的集成

**API 模式集成：**

```python
# src/api.py
GATEWAY_URL = os.getenv("BROWSER_GATEWAY_URL")  # http://gateway:8001
GATEWAY_API_KEY = os.getenv("BROWSER_GATEWAY_KEY")

async def create_session_with_gateway(user_id: str):
    """通过 Gateway 创建远程浏览器会话"""
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{GATEWAY_URL}/allocate",
            headers={"X-API-Key": GATEWAY_API_KEY}
        ) as resp:
            data = await resp.json()
            cdp_url = data["cdp_url"]
            token = data["token"]
    
    # 使用分配的 CDP URL 创建会话
    context = await session_mgr.create_session(
        session_id=f"{user_id}_{uuid4().hex[:8]}",
        browser_mode="remote",
        cdp_url=cdp_url
    )
    return context
```

**CLI 模式集成：**

```bash
# 通过 Gateway 分配浏览器
export BROWSER_GATEWAY_URL=http://gateway:8001
export BROWSER_GATEWAY_KEY=key_abc123

agent-browser session create --name my-session --browser remote --use-gateway
# CLI 内部调用 Gateway API 获取 CDP URL
```

### 5.4 认证和安全

**API Key 管理：**
- 存储：Redis/PostgreSQL
- 格式：`key_<random_32_chars>`
- 权限：用户级别、配额限制

**Token 机制：**
- 短期 Token（1小时）用于 CDP 连接
- JWT 格式，包含 instance_id 和 user_id
- Gateway 验证 Token 有效性


## 六、关键技术实现

### 6.1 步骤跟踪和反馈

**实现方式：**

```python
# src/core/tracer.py
class ActionTracer:
    """操作跟踪器"""
    
    def __init__(self):
        self.steps = []
        self.current_step = 0
    
    def record_step(self, action: str, params: dict, result: dict):
        """记录步骤"""
        self.current_step += 1
        step = {
            "step": self.current_step,
            "action": action,
            "params": params,
            "result": result,
            "timestamp": time.time()
        }
        self.steps.append(step)
        return step
    
    def get_trace(self) -> list:
        """获取完整轨迹"""
        return self.steps

# 集成到 BrowserController
class BrowserController:
    def __init__(self, browser_session: BrowserSession):
        self.session = browser_session
        self.tracer = ActionTracer()
    
    async def goto(self, url: str) -> dict:
        result = await self.page.goto(url)
        step = self.tracer.record_step("goto", {"url": url}, {"status": "success"})
        return {"url": self.page.url, "trace": step}
```

**CLI 输出示例：**
```json
{
  "status": "success",
  "data": {"url": "https://example.com"},
  "trace": {
    "step": 3,
    "action": "goto",
    "timestamp": 1234567890
  }
}
```


### 6.2 Token 优化策略

**DOM 压缩（browser-use 内置）：**
- 使用 browser-use 的 DOM 简化能力
- 移除不可见元素、样式、脚本
- 保留交互元素和文本内容

**选择性内容提取：**
```python
async def extract_content(self, selector: str, extract_type: str = "text"):
    """选择性提取，避免返回完整 DOM"""
    if extract_type == "text":
        return await self.extract_text(selector)
    elif extract_type == "html":
        element = await self.page.query_selector(selector)
        return await element.inner_html()
    elif extract_type == "attributes":
        element = await self.page.query_selector(selector)
        return await element.get_attributes()
```

**增量更新：**
- CLI 模式：只返回变化的部分
- 使用 diff 算法比较 DOM 变化

### 6.3 反检测能力保持

**5 层防护栈保持不变：**
1. CloakBrowser（C++ 编译级）
2. patchright（驱动级 CDP 补丁）
3. rebrowser-patches（Runtime 泄漏修复）
4. 非标准端口 19222
5. 持久化 CDP 会话

**CLI 模式特殊考虑：**
- 保持长连接：会话模式避免频繁创建/销毁
- 行为模拟：在 CLI 命令间添加随机延迟
- 指纹一致性：同一会话使用相同 profile

```python
# src/core/stealth.py
class StealthEnhancer:
    """反检测增强"""
    
    async def add_human_delay(self, action_type: str):
        """添加类人延迟"""
        delays = {
            "click": (0.1, 0.3),
            "input": (0.05, 0.15),
            "scroll": (0.2, 0.5)
        }
        min_delay, max_delay = delays.get(action_type, (0.1, 0.2))
        await asyncio.sleep(random.uniform(min_delay, max_delay))
```


### 6.4 高性能设计

**连接池复用：**
```python
# src/core/connection_pool.py
class CDPConnectionPool:
    """CDP 连接池"""
    
    def __init__(self, max_connections: int = 50):
        self.pool = {}
        self.max_connections = max_connections
    
    async def get_connection(self, cdp_url: str):
        """获取或创建连接"""
        if cdp_url not in self.pool:
            pw = await async_playwright().start()
            browser = await pw.chromium.connect_over_cdp(cdp_url)
            self.pool[cdp_url] = (pw, browser)
        return self.pool[cdp_url]
```

**并发控制：**
- API 模式：每个会话独立任务队列
- CLI 模式：单会话串行执行
- 浏览器池：限制最大并发实例数

**缓存策略：**
- DOM 缓存：相同页面避免重复获取
- 元素定位缓存：缓存 selector 查询结果


## 七、实现路径建议

### 7.1 Phase 1: 核心能力层重构（2-3 周）

**目标：提取 browser-use 原子能力**

1. 创建 `src/core/browser_controller.py`
   - 封装 browser-use 原子方法
   - 统一返回格式
   - 添加步骤跟踪

2. 重构 `src/core/session_manager.py`
   - 统一 API 和 CLI 的会话管理
   - 支持本地/远程浏览器模式

3. 测试验证
   - 单元测试：每个原子方法
   - 集成测试：会话生命周期

**交付物：**
- BrowserController 类（15+ 原子方法）
- UnifiedSessionManager 类
- 测试覆盖率 > 80%


### 7.2 Phase 2: CLI 模式实现（2-3 周）

**目标：实现完整 CLI 命令集**

1. 创建 CLI 框架
   - `src/cli/commands.py`：命令定义
   - `src/cli/output.py`：JSON 输出格式化
   - `src/cli/session_store.py`：本地会话存储

2. 实现命令组
   - session 组：create, list, info, destroy
   - navigate 组：goto, back, forward, refresh
   - interact 组：click, input, scroll, select
   - extract 组：text, dom, screenshot, elements
   - page 组：new, switch, close, list

3. 集成测试
   - E2E 测试：完整任务流程
   - MCP 集成测试

**交付物：**
- 20+ CLI 命令
- 完整文档和示例
- MCP 集成指南


### 7.3 Phase 3: 远程浏览器 Gateway（1-2 周）

**目标：实现独立的浏览器资源管理服务**

1. 创建 Gateway 服务
   - `src/gateway/api.py`：FastAPI 服务
   - `src/gateway/auth.py`：API Key 认证
   - `src/gateway/pool.py`：浏览器资源池

2. 集成到 API/CLI
   - API 模式：通过 Gateway 分配远程浏览器
   - CLI 模式：`--use-gateway` 选项

3. 部署配置
   - Docker Compose 配置
   - K8s Deployment 配置

**交付物：**
- Gateway 服务（独立部署）
- API Key 管理界面
- 部署文档


### 7.4 Phase 4: API 模式增强（1 周）

**目标：重构 API 模式使用统一核心层**

1. 重构 `src/api.py`
   - 使用 UnifiedSessionManager
   - 保持向后兼容
   - 添加新端点（原子操作）

2. 可选：API 模式支持原子操作
   - `POST /sessions/{id}/action/goto`
   - `POST /sessions/{id}/action/click`
   - 供高级用户精细控制

**交付物：**
- 重构后的 API（向后兼容）
- 新增原子操作端点（可选）


## 八、目录结构（重构后）

```
agent-browser/
├── src/
│   ├── core/                          # 核心能力层（新增）
│   │   ├── browser_controller.py      # browser-use 原子能力封装
│   │   ├── session_manager.py         # 统一会话管理
│   │   ├── tracer.py                  # 步骤跟踪
│   │   └── stealth.py                 # 反检测增强
│   ├── api/                           # API 模式（重构）
│   │   ├── main.py                    # FastAPI 入口
│   │   ├── endpoints.py               # REST 端点
│   │   └── models.py                  # 请求/响应模型
│   ├── cli/                           # CLI 模式（新增）
│   │   ├── commands.py                # CLI 命令定义
│   │   ├── output.py                  # 输出格式化
│   │   └── session_store.py           # 本地会话存储
│   ├── gateway/                       # 远程浏览器 Gateway（新增）
│   │   ├── api.py                     # Gateway API
│   │   ├── auth.py                    # 认证管理
│   │   └── pool.py                    # 资源池管理
│   ├── browser/                       # 浏览器层（保持）
│   │   ├── stealth_launcher.py
│   │   ├── instance_pool.py
│   │   └── human_behavior.py
│   └── models.py                      # 数据模型
├── tests/
│   ├── test_core/                     # 核心层测试
│   ├── test_cli/                      # CLI 测试
│   └── test_api/                      # API 测试
└── docs/
    ├── CLI_GUIDE.md                   # CLI 使用指南
    ├── API_GUIDE.md                   # API 使用指南
    └── GATEWAY_GUIDE.md               # Gateway 部署指南
```


## 九、关键接口设计

### 9.1 BrowserController 接口

```python
class BrowserController:
    """browser-use 原子能力封装"""
    
    # 导航
    async def goto(self, url: str) -> dict
    async def go_back(self) -> dict
    async def go_forward(self) -> dict
    async def refresh(self) -> dict
    
    # 交互
    async def click(self, selector: str, index: int = 0) -> dict
    async def input_text(self, selector: str, text: str) -> dict
    async def scroll(self, direction: str, amount: int) -> dict
    async def select_option(self, selector: str, value: str) -> dict
    
    # 提取
    async def extract_text(self, selector: str) -> dict
    async def extract_html(self, selector: str) -> dict
    async def get_dom(self, simplified: bool = True) -> dict
    async def screenshot(self, full_page: bool = False) -> dict
    async def find_elements(self, selector: str) -> dict
    
    # 页面管理
    async def new_page(self, url: Optional[str] = None) -> dict
    async def switch_page(self, index: int) -> dict
    async def close_page(self, index: int) -> dict
    async def list_pages(self) -> dict
    
    # 状态查询
    async def get_url(self) -> dict
    async def get_title(self) -> dict
    async def wait_for_element(self, selector: str, timeout: int = 5000) -> dict
```


### 9.2 UnifiedSessionManager 接口

```python
class UnifiedSessionManager:
    """统一会话管理器"""
    
    async def create_session(
        self,
        session_id: str,
        browser_mode: Literal["local", "remote"],
        cdp_url: Optional[str] = None,
        profile_dir: Optional[str] = None,
    ) -> SessionContext
    
    async def get_session(self, session_id: str) -> SessionContext
    
    async def list_sessions(self) -> List[SessionContext]
    
    async def destroy_session(self, session_id: str) -> None
    
    async def get_controller(self, session_id: str) -> BrowserController
```

### 9.3 Gateway API 接口

```python
# POST /allocate
Request:
  Headers: X-API-Key: key_abc123
Response:
  {
    "instance_id": "browser_abc123",
    "cdp_url": "http://10.0.1.5:19222",
    "token": "jwt_token_here",
    "expires_in": 3600
  }

# POST /release
Request:
  Headers: X-API-Key: key_abc123
  Body: {"instance_id": "browser_abc123"}
Response:
  {"status": "released"}

# GET /status
Response:
  {
    "total_instances": 10,
    "active_instances": 7,
    "available_instances": 3
  }
```


## 十、CLI 命令完整列表

### 会话管理
```bash
agent-browser session create --name <name> [--browser local|remote] [--cdp-url <url>]
agent-browser session list
agent-browser session info --session <id>
agent-browser session destroy --session <id>
```

### 导航操作
```bash
agent-browser navigate goto --session <id> --url <url>
agent-browser navigate back --session <id>
agent-browser navigate forward --session <id>
agent-browser navigate refresh --session <id>
```

### 交互操作
```bash
agent-browser interact click --session <id> --selector <css>
agent-browser interact input --session <id> --selector <css> --text <text>
agent-browser interact scroll --session <id> --direction up|down --amount <px>
agent-browser interact select --session <id> --selector <css> --value <value>
```

### 内容提取
```bash
agent-browser extract text --session <id> --selector <css>
agent-browser extract html --session <id> --selector <css>
agent-browser extract dom --session <id> [--simplified]
agent-browser extract screenshot --session <id> [--full-page]
agent-browser extract elements --session <id> --selector <css>
```

### 页面管理
```bash
agent-browser page new --session <id> [--url <url>]
agent-browser page switch --session <id> --index <n>
agent-browser page close --session <id> --index <n>
agent-browser page list --session <id>
```


## 十一、使用场景示例

### 场景 1：API 模式（自主 Agent）

```bash
# 创建会话
curl -X POST http://localhost:8000/sessions/create \
  -H "Content-Type: application/json" \
  -d '{"user_id": "alice", "browser_mode": "local"}'

# 提交任务（Agent 自主执行）
curl -X POST http://localhost:8000/sessions/alice_abc123/task \
  -H "Content-Type: application/json" \
  -d '{
    "task": "在 Boss 直聘搜索 Python 开发岗位，提取前 5 个结果",
    "llm_provider": "openai",
    "llm_model": "gpt-4o-mini",
    "max_steps": 30
  }'
```

### 场景 2：CLI 模式（MCP 集成）

```bash
# 创建会话
agent-browser session create --name job-search --browser local
# 输出：{"status": "success", "data": {"session_id": "job-search"}}

# 导航到网站
agent-browser navigate goto --session job-search --url https://www.zhipin.com

# 输入搜索关键词
agent-browser interact input --session job-search --selector "#search-input" --text "Python开发"

# 点击搜索按钮
agent-browser interact click --session job-search --selector "#search-btn"

# 提取结果
agent-browser extract text --session job-search --selector ".job-list .job-item"

# 销毁会话
agent-browser session destroy --session job-search
```


### 场景 3：远程浏览器 Gateway

```bash
# Gateway 分配浏览器
curl -X POST http://gateway:8001/allocate \
  -H "X-API-Key: key_abc123"
# 返回：{"cdp_url": "http://10.0.1.5:19222", "token": "jwt_token"}

# CLI 使用远程浏览器
agent-browser session create --name remote-session \
  --browser remote \
  --cdp-url http://10.0.1.5:19222

# 执行操作...

# 释放浏览器
curl -X POST http://gateway:8001/release \
  -H "X-API-Key: key_abc123" \
  -d '{"instance_id": "browser_abc123"}'
```


## 十二、技术风险和缓解策略

### 风险 1：browser-use 版本兼容性

**风险：** browser-use 更新可能破坏原子方法接口

**缓解：**
- 锁定 browser-use 版本（requirements.txt）
- 创建适配层隔离变化
- 定期测试新版本兼容性

### 风险 2：CLI 模式性能

**风险：** 每次命令启动 Python 进程开销大

**缓解：**
- 使用会话模式减少启动次数
- 考虑守护进程模式（可选）
- 优化导入时间（延迟导入）

### 风险 3：远程浏览器网络延迟

**风险：** 远程 CDP 连接延迟影响性能

**缓解：**
- 使用内网部署减少延迟
- 批量操作减少往返次数
- 添加超时和重试机制


## 十三、代码复用策略

### API 模式与 CLI 模式共享

**共享层：**
- `core/browser_controller.py` - 原子操作
- `core/session_manager.py` - 会话管理
- `browser/` - 浏览器启动和管理
- `models.py` - 数据模型

**独立层：**
- `api/` - FastAPI + Agent 自主决策
- `cli/` - Click CLI + 原子命令
- `gateway/` - 独立认证服务

**复用率：** 约 70% 代码共享


## 十四、总结与建议

### 架构优势

1. **清晰的职责分离**
   - API 模式：自主 Agent，适合独立部署
   - CLI 模式：原子工具，适合 MCP 集成
   - Gateway：独立认证，统一资源管理

2. **高度代码复用**
   - 核心能力层共享（BrowserController + SessionManager）
   - 减少维护成本
   - 统一行为和反检测能力

3. **灵活的部署选项**
   - 本地浏览器：开发和测试
   - 远程浏览器：生产环境
   - Gateway：多租户 SaaS

### 关键设计亮点

1. **browser-use 原子能力提取**
   - 直接使用 BrowserSession 和 Playwright API
   - 绕过 Agent 层，避免 LLM 依赖
   - 保持反检测能力

2. **统一会话管理**
   - API 和 CLI 共享同一套会话逻辑
   - 支持本地和远程浏览器
   - 一致的生命周期管理

3. **独立 Gateway 服务**
   - 解耦认证和业务逻辑
   - 灵活的资源调度
   - 易于扩展和监控

### 实施建议

1. **优先级**
   - Phase 1（核心层）是基础，必须先完成
   - Phase 2（CLI）是核心需求，优先级高
   - Phase 3（Gateway）可后续迭代

2. **向后兼容**
   - 保持现有 API 端点不变
   - 新功能通过新端点提供
   - 逐步迁移用户

3. **测试策略**
   - 单元测试：每个原子方法
   - 集成测试：完整任务流程
   - E2E 测试：真实网站场景


---

## 十五、时序图 - 不同场景的交互流程

### 场景 1：API 模式 - 本地浏览器自主任务执行

```
用户 -> API Server -> SessionManager -> BrowserPool -> CloakBrowser -> Agent -> LLM
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘

详细流程：

┌─────┐   ┌──────────┐   ┌────────────────┐   ┌─────────────┐   ┌──────────────┐   ┌────────┐
│User │   │API Server│   │SessionManager  │   │BrowserPool  │   │CloakBrowser  │   │ Agent  │
└──┬──┘   └────┬─────┘   └───────┬────────┘   └──────┬──────┘   └──────┬───────┘   └───┬────┘
   │           │                 │                    │                  │               │
   │ POST /sessions/create       │                    │                  │               │
   ├──────────>│                 │                    │                  │               │
   │           │ create_session()│                    │                  │               │
   │           ├────────────────>│                    │                  │               │
   │           │                 │ allocate_local()   │                  │               │
   │           │                 ├───────────────────>│                  │               │
   │           │                 │                    │ launch_browser() │               │
   │           │                 │                    ├─────────────────>│               │
   │           │                 │                    │                  │ (启动进程)    │
   │           │                 │                    │                  │ CDP:19222     │
   │           │                 │                    │<─────────────────┤               │
   │           │                 │<───────────────────┤ cdp_url          │               │
   │           │                 │ create_controller()│                  │               │
   │           │                 │ (BrowserController)│                  │               │
   │           │<────────────────┤ SessionContext     │                  │               │
   │<──────────┤ {session_id}    │                    │                  │               │
   │           │                 │                    │                  │               │
   │ POST /sessions/{id}/task    │                    │                  │               │
   ├──────────>│                 │                    │                  │               │
   │           │ get_session()   │                    │                  │               │
   │           ├────────────────>│                    │                  │               │
   │           │<────────────────┤ SessionContext     │                  │               │
   │           │                 │                    │                  │               │
   │           │ create_agent()  │                    │                  │               │
   │           ├─────────────────────────────────────────────────────────────────────────>│
   │           │                 │                    │                  │               │
   │<──────────┤ {task_id}       │                    │                  │               │
   │           │                 │                    │                  │               │
   │           │ [后台执行]      │                    │                  │               │
   │           │                 │                    │                  │  agent.run()  │
   │           │                 │                    │                  │<──────────────┤
   │           │                 │                    │                  │  goto()       │
   │           │                 │                    │                  │  click()      │
   │           │                 │                    │                  │  extract()    │
   │           │                 │                    │                  │───────────────>│
   │           │                 │                    │                  │               │ LLM 决策
   │           │                 │                    │                  │<──────────────┤ 下一步
   │           │                 │                    │                  │               │
   │ GET /sessions/{id}/tasks/{task_id}              │                  │               │
   ├──────────>│                 │                    │                  │               │
   │<──────────┤ {status, result}│                    │                  │               │
```

**关键点：**
- API Server 使用 browser-use 的完整 Agent（自主决策）
- Agent 内部循环调用 LLM 规划下一步操作
- 用户只需提交任务描述，无需关心执行细节

---

### 场景 2：CLI 模式 - 本地浏览器原子命令执行

```
外部 LLM Agent -> CLI -> SessionManager -> BrowserController -> BrowserSession -> Playwright
│                                                                                         │
└─────────────────────────────────────────────────────────────────────────────────────────┘

详细流程：

┌──────────┐   ┌─────┐   ┌────────────────┐   ┌──────────────────┐   ┌───────────────┐   ┌───────────┐
│External  │   │ CLI │   │SessionManager  │   │BrowserController │   │BrowserSession │   │Playwright │
│LLM Agent │   │     │   │                │   │                  │   │               │   │           │
└────┬─────┘   └──┬──┘   └───────┬────────┘   └────────┬─────────┘   └───────┬───────┘   └─────┬─────┘
     │            │              │                      │                     │                 │
     │ 决策：创建会话             │                      │                     │                 │
     ├───────────>│              │                      │                     │                 │
     │            │ session create --name s1 --browser local                 │                 │
     │            ├─────────────>│                      │                     │                 │
     │            │              │ create_session()     │                     │                 │
     │            │              │ (分配浏览器实例)      │                     │                 │
     │            │              │ create_controller()  │                     │                 │
     │            │              ├─────────────────────>│                     │                 │
     │            │              │                      │ new BrowserSession()│                 │
     │            │              │                      ├────────────────────>│                 │
     │            │              │                      │                     │ connect_cdp()   │
     │            │              │                      │                     ├────────────────>│
     │            │              │                      │                     │<────────────────┤
     │            │              │<─────────────────────┤ controller          │                 │
     │            │<─────────────┤ {session_id: "s1"}   │                     │                 │
     │<───────────┤ JSON output  │                      │                     │                 │
     │            │              │                      │                     │                 │
     │ 决策：导航到 URL           │                      │                     │                 │
     ├───────────>│              │                      │                     │                 │
     │            │ navigate goto --session s1 --url https://example.com     │                 │
     │            ├─────────────>│                      │                     │                 │
     │            │              │ get_session("s1")    │                     │                 │
     │            │              ├─────────────────────>│                     │                 │
     │            │              │                      │ goto(url)           │                 │
     │            │              │                      ├────────────────────>│                 │
     │            │              │                      │                     │ page.goto()     │
     │            │              │                      │                     ├────────────────>│
     │            │              │                      │                     │<────────────────┤
     │            │              │                      │ record_step()       │                 │
     │            │              │                      │ (ActionTracer)      │                 │
     │            │              │<─────────────────────┤ {url, title, trace} │                 │
     │            │<─────────────┤ JSON output          │                     │                 │
     │<───────────┤              │                      │                     │                 │
     │            │              │                      │                     │                 │
     │ 决策：点击元素             │                      │                     │                 │
     ├───────────>│              │                      │                     │                 │
     │            │ interact click --session s1 --selector "#button"         │                 │
     │            ├─────────────>│                      │                     │                 │
     │            │              ├─────────────────────>│                     │                 │
     │            │              │                      │ click(selector)     │                 │
     │            │              │                      ├────────────────────>│                 │
     │            │              │                      │                     │ page.click()    │
     │            │              │                      │                     ├────────────────>│
     │            │              │                      │                     │<────────────────┤
     │            │              │                      │ record_step()       │                 │
     │            │              │<─────────────────────┤ {selector, trace}   │                 │
     │            │<─────────────┤ JSON output          │                     │                 │
     │<───────────┤              │                      │                     │                 │
     │            │              │                      │                     │                 │
     │ 决策：提取内容             │                      │                     │                 │
     ├───────────>│              │                      │                     │                 │
     │            │ extract text --session s1 --selector ".content"          │                 │
     │            ├─────────────>│                      │                     │                 │
     │            │              ├─────────────────────>│                     │                 │
     │            │              │                      │ extract_text()      │                 │
     │            │              │                      ├────────────────────>│                 │
     │            │              │                      │                     │ query_selector()│
     │            │              │                      │                     ├────────────────>│
     │            │              │                      │                     │ inner_text()    │
     │            │              │                      │                     ├────────────────>│
     │            │              │                      │                     │<────────────────┤
     │            │              │                      │ record_step()       │                 │
     │            │              │<─────────────────────┤ {text, trace}       │                 │
     │            │<─────────────┤ JSON output          │                     │                 │
     │<───────────┤              │                      │                     │                 │
     │ 解析结果，决策下一步       │                      │                     │                 │
```

**关键点：**
- 外部 LLM Agent（如 Claude、GPT）负责决策
- CLI 提供原子命令，每次返回结构化 JSON
- BrowserController 直接调用 browser-use 的 BrowserSession（不经过 Agent）
- ActionTracer 记录每步操作，便于调试和审计

---

### 场景 3：API 模式 - 远程浏览器 + Gateway 认证

```
用户 -> API Server -> Gateway -> Docker/K8s -> CloakBrowser
│                                                          │
└──────────────────────────────────────────────────────────┘

详细流程：

┌─────┐   ┌──────────┐   ┌────────────────┐   ┌─────────┐   ┌──────────────┐   ┌──────────────┐
│User │   │API Server│   │SessionManager  │   │Gateway  │   │Docker/K8s    │   │CloakBrowser  │
└──┬──┘   └────┬─────┘   └───────┬────────┘   └────┬────┘   └──────┬───────┘   └──────┬───────┘
   │           │                 │                  │                │                  │
   │ POST /sessions/create (browser_mode=remote)   │                │                  │
   ├──────────>│                 │                  │                │                  │
   │           │ create_session()│                  │                │                  │
   │           ├────────────────>│                  │                │                  │
   │           │                 │ POST /allocate   │                │                  │
   │           │                 │ (X-API-Key: xxx) │                │                  │
   │           │                 ├─────────────────>│                │                  │
   │           │                 │                  │ 验证 API Key   │                  │
   │           │                 │                  │ 检查配额       │                  │
   │           │                 │                  │                │                  │
   │           │                 │                  │ docker run ... │                  │
   │           │                 │                  ├───────────────>│                  │
   │           │                 │                  │                │ 启动容器         │
   │           │                 │                  │                ├─────────────────>│
   │           │                 │                  │                │                  │ (启动)
   │           │                 │                  │                │                  │ CDP:19222
   │           │                 │                  │                │<─────────────────┤
   │           │                 │                  │<───────────────┤ container_id     │
   │           │                 │                  │ 生成 Token     │                  │
   │           │                 │                  │ (JWT)          │                  │
   │           │                 │<─────────────────┤                │                  │
   │           │                 │ {cdp_url, token, instance_id}     │                  │
   │           │                 │                  │                │                  │
   │           │                 │ create_controller()               │                  │
   │           │                 │ (使用 cdp_url)   │                │                  │
   │           │<────────────────┤ SessionContext   │                │                  │
   │<──────────┤ {session_id, cdp_url}              │                │                  │
   │           │                 │                  │                │                  │
   │ POST /sessions/{id}/task    │                  │                │                  │
   ├──────────>│                 │                  │                │                  │
   │           │ get_session()   │                  │                │                  │
   │           ├────────────────>│                  │                │                  │
   │           │ create_agent()  │                  │                │                  │
   │           │ (连接到 cdp_url)│                  │                │                  │
   │           │                 │                  │                │                  │
   │           │ [Agent 执行任务，通过 CDP 控制远程浏览器]            │                  │
   │           │                 │                  │                │<─────────────────┤
   │           │                 │                  │                │  CDP 命令        │
   │           │                 │                  │                ├─────────────────>│
   │           │                 │                  │                │                  │
   │ DELETE /sessions/{id}       │                  │                │                  │
   ├──────────>│                 │                  │                │                  │
   │           │ destroy_session()                  │                │                  │
   │           ├────────────────>│                  │                │                  │
   │           │                 │ POST /release    │                │                  │
   │           │                 │ (instance_id)    │                │                  │
   │           │                 ├─────────────────>│                │                  │
   │           │                 │                  │ docker stop    │                  │
   │           │                 │                  ├───────────────>│                  │
   │           │                 │                  │                │ 停止容器         │
   │           │                 │                  │                ├─────────────────>│
   │           │                 │                  │<───────────────┤                  │
   │           │                 │<─────────────────┤ {status: released}                │
   │           │<────────────────┤                  │                │                  │
   │<──────────┤ {status: deleted}                  │                │                  │
```

**关键点：**
- Gateway 负责认证、资源分配、容器生命周期管理
- API Server 只关心业务逻辑，通过 CDP URL 连接远程浏览器
- Gateway 生成短期 Token（JWT），增强安全性
- 支持多租户隔离和配额管理

---

### 场景 4：CLI 模式 - 远程浏览器 + Gateway 认证

```
外部 LLM Agent -> CLI -> Gateway -> Docker/K8s -> CloakBrowser
│                                                            │
└────────────────────────────────────────────────────────────┘

详细流程：

┌──────────┐   ┌─────┐   ┌────────────────┐   ┌─────────┐   ┌──────────────┐   ┌──────────────┐
│External  │   │ CLI │   │SessionManager  │   │Gateway  │   │Docker/K8s    │   │CloakBrowser  │
│LLM Agent │   │     │   │                │   │         │   │              │   │              │
└────┬─────┘   └──┬──┘   └───────┬────────┘   └────┬────┘   └──────┬───────┘   └──────┬───────┘
     │            │              │                  │                │                  │
     │ 决策：创建远程会话         │                  │                │                  │
     ├───────────>│              │                  │                │                  │
     │            │ session create --name s1 --browser remote --use-gateway            │
     │            │ (环境变量: GATEWAY_URL, GATEWAY_KEY)              │                  │
     │            ├─────────────>│                  │                │                  │
     │            │              │ POST /allocate   │                │                  │
     │            │              │ (X-API-Key: xxx) │                │                  │
     │            │              ├─────────────────>│                │                  │
     │            │              │                  │ 验证 API Key   │                  │
     │            │              │                  │ 检查配额       │                  │
     │            │              │                  │ docker run ... │                  │
     │            │              │                  ├───────────────>│                  │
     │            │              │                  │                │ 启动容器         │
     │            │              │                  │                ├─────────────────>│
     │            │              │                  │                │<─────────────────┤
     │            │              │                  │<───────────────┤                  │
     │            │              │<─────────────────┤ {cdp_url, token, instance_id}     │
     │            │              │                  │                │                  │
     │            │              │ create_session() │                │                  │
     │            │              │ (browser_mode=remote, cdp_url)    │                  │
     │            │              │ 保存 instance_id │                │                  │
     │            │<─────────────┤ {session_id, cdp_url}             │                  │
     │<───────────┤ JSON output  │                  │                │                  │
     │            │              │                  │                │                  │
     │ 决策：执行操作             │                  │                │                  │
     ├───────────>│              │                  │                │                  │
     │            │ navigate goto --session s1 --url https://example.com               │
     │            ├─────────────>│                  │                │                  │
     │            │              │ get_session()    │                │                  │
     │            │              │ controller.goto()│                │                  │
     │            │              │ (通过 CDP 连接)  │                │                  │
     │            │              │                  │                │<─────────────────┤
     │            │              │                  │                │  CDP 命令        │
     │            │              │                  │                ├─────────────────>│
     │            │<─────────────┤ JSON output      │                │                  │
     │<───────────┤              │                  │                │                  │
     │            │              │                  │                │                  │
     │ 决策：销毁会话             │                  │                │                  │
     ├───────────>│              │                  │                │                  │
     │            │ session destroy --session s1    │                │                  │
     │            ├─────────────>│                  │                │                  │
     │            │              │ destroy_session()│                │                  │
     │            │              │ POST /release    │                │                  │
     │            │              │ (instance_id)    │                │                  │
     │            │              ├─────────────────>│                │                  │
     │            │              │                  │ docker stop    │                  │
     │            │              │                  ├───────────────>│                  │
     │            │              │                  │                │ 停止容器         │
     │            │              │                  │                ├─────────────────>│
     │            │              │                  │<───────────────┤                  │
     │            │              │<─────────────────┤ {status: released}                │
     │            │<─────────────┤ JSON output      │                │                  │
     │<───────────┤              │                  │                │                  │
```

**关键点：**
- CLI 通过环境变量配置 Gateway 地址和 API Key
- 创建会话时自动调用 Gateway 分配远程浏览器
- 销毁会话时自动释放资源
- 外部 LLM Agent 无需关心浏览器资源管理细节

---

### 场景 5：核心能力层 - BrowserController 原子操作执行

```
调用方 (API/CLI) -> BrowserController -> BrowserSession -> Playwright -> CloakBrowser
│                                                                                      │
└──────────────────────────────────────────────────────────────────────────────────────┘

详细流程（以 click 操作为例）：

┌─────────┐   ┌──────────────────┐   ┌───────────────┐   ┌───────────┐   ┌──────────────┐
│Caller   │   │BrowserController │   │BrowserSession │   │Playwright │   │CloakBrowser  │
│(API/CLI)│   │                  │   │               │   │           │   │              │
└────┬────┘   └────────┬─────────┘   └───────┬───────┘   └─────┬─────┘   └──────┬───────┘
     │                 │                     │                   │                │
     │ click(selector) │                     │                   │                │
     ├────────────────>│                     │                   │                │
     │                 │ 1. 添加人类延迟    │                   │                │
     │                 │ (StealthEnhancer)  │                   │                │
     │                 │ await sleep(0.1~0.3)                   │                │
     │                 │                     │                   │                │
     │                 │ 2. 获取当前页面    │                   │                │
     │                 │ page = session.current_page            │                │
     │                 │                     │                   │                │
     │                 │ 3. 查找元素        │                   │                │
     │                 │ page.query_selector(selector)          │                │
     │                 ├────────────────────>│                   │                │
     │                 │                     │ CDP: DOM.querySelector            │
     │                 │                     ├──────────────────>│                │
     │                 │                     │                   │ 查找 DOM 节点  │
     │                 │                     │                   ├───────────────>│
     │                 │                     │                   │<───────────────┤
     │                 │                     │<──────────────────┤ node_id        │
     │                 │<────────────────────┤ element           │                │
     │                 │                     │                   │                │
     │                 │ 4. 模拟鼠标移动    │                   │                │
     │                 │ (HumanBehaviorSimulator)               │                │
     │                 │ random_mouse_move() │                   │                │
     │                 ├────────────────────>│                   │                │
     │                 │                     │ CDP: Input.dispatchMouseEvent      │
     │                 │                     ├──────────────────>│                │
     │                 │                     │                   │ 移动鼠标       │
     │                 │                     │                   ├───────────────>│
     │                 │                     │                   │<───────────────┤
     │                 │<────────────────────┤                   │                │
     │                 │                     │                   │                │
     │                 │ 5. 执行点击        │                   │                │
     │                 │ element.click()     │                   │                │
     │                 ├────────────────────>│                   │                │
     │                 │                     │ CDP: Input.dispatchMouseEvent      │
     │                 │                     │ (mousePressed + mouseReleased)     │
     │                 │                     ├──────────────────>│                │
     │                 │                     │                   │ 点击事件       │
     │                 │                     │                   ├───────────────>│
     │                 │                     │                   │<───────────────┤
     │                 │                     │<──────────────────┤                │
     │                 │<────────────────────┤                   │                │
     │                 │                     │                   │                │
     │                 │ 6. 记录步骤        │                   │                │
     │                 │ tracer.record_step()                   │                │
     │                 │ {action: "click", selector, timestamp} │                │
     │                 │                     │                   │                │
     │                 │ 7. 返回结果        │                   │                │
     │<────────────────┤ {status: "success", selector, trace}   │                │
     │                 │                     │                   │                │
```

**关键点：**
- BrowserController 封装了反检测增强（人类延迟、鼠标移动）
- 直接使用 browser-use 的 BrowserSession 和 Playwright API
- ActionTracer 记录每步操作，便于审计和调试
- 所有操作通过 CDP 协议与浏览器通信

---

### 场景 6：会话管理 - 统一会话生命周期

```
调用方 -> UnifiedSessionManager -> BrowserPool -> BrowserInstance -> CloakBrowser
│                                                                               │
└───────────────────────────────────────────────────────────────────────────────┘

详细流程：

┌─────────┐   ┌────────────────────┐   ┌─────────────┐   ┌─────────────────┐   ┌──────────────┐
│Caller   │   │UnifiedSessionMgr   │   │BrowserPool  │   │BrowserInstance  │   │CloakBrowser  │
│(API/CLI)│   │                    │   │             │   │                 │   │              │
└────┬────┘   └──────────┬─────────┘   └──────┬──────┘   └────────┬────────┘   └──────┬───────┘
     │                   │                    │                    │                    │
     │ create_session()  │                    │                    │                    │
     │ (session_id, browser_mode, cdp_url)    │                    │                    │
     ├──────────────────>│                    │                    │                    │
     │                   │                    │                    │                    │
     │                   │ 1. 检查会话是否存在│                    │                    │
     │                   │ if session_id in sessions: raise Error │                    │
     │                   │                    │                    │                    │
     │                   │ 2. 分配浏览器实例  │                    │                    │
     │                   │ if browser_mode == "local":            │                    │
     │                   │   allocate_local() │                    │                    │
     │                   ├───────────────────>│                    │                    │
     │                   │                    │ 检查可用实例       │                    │
     │                   │                    │ if available:      │                    │
     │                   │                    │   return existing  │                    │
     │                   │                    │ else:              │                    │
     │                   │                    │   launch_new()     │                    │
     │                   │                    ├───────────────────>│                    │
     │                   │                    │                    │ launch_browser()   │
     │                   │                    │                    ├───────────────────>│
     │                   │                    │                    │                    │ (启动)
     │                   │                    │                    │                    │ CDP:19222
     │                   │                    │                    │<───────────────────┤
     │                   │                    │<───────────────────┤ instance           │
     │                   │<───────────────────┤ instance           │                    │
     │                   │                    │                    │                    │
     │                   │ 3. 创建 BrowserSession                  │                    │
     │                   │ session = BrowserSession(              │                    │
     │                   │   browser_profile=BrowserProfile(      │                    │
     │                   │     cdp_url=instance.cdp_url           │                    │
     │                   │   )                                    │                    │
     │                   │ )                  │                    │                    │
     │                   │                    │                    │                    │
     │                   │ 4. 创建 BrowserController              │                    │
     │                   │ controller = BrowserController(session)│                    │
     │                   │                    │                    │                    │
     │                   │ 5. 创建 SessionContext                 │                    │
     │                   │ context = SessionContext(              │                    │
     │                   │   session_id=session_id,               │                    │
     │                   │   browser_instance=instance,           │                    │
     │                   │   browser_session=session,             │                    │
     │                   │   controller=controller,               │                    │
     │                   │   created_at=time.time()               │                    │
     │                   │ )                  │                    │                    │
     │                   │                    │                    │                    │
     │                   │ 6. 保存会话        │                    │                    │
     │                   │ sessions[session_id] = context         │                    │
     │                   │                    │                    │                    │
     │                   │ 7. 启动监控任务    │                    │                    │
     │                   │ asyncio.create_task(                   │                    │
     │                   │   _monitor_session(session_id)         │                    │
     │                   │ )                  │                    │                    │
     │                   │                    │                    │                    │
     │<──────────────────┤ SessionContext     │                    │                    │
     │                   │                    │                    │                    │
     │ ... 使用会话 ...  │                    │                    │                    │
     │                   │                    │                    │                    │
     │ destroy_session() │                    │                    │                    │
     ├──────────────────>│                    │                    │                    │
     │                   │ 1. 获取会话        │                    │                    │
     │                   │ context = sessions.pop(session_id)     │                    │
     │                   │                    │                    │                    │
     │                   │ 2. 关闭 BrowserSession                 │                    │
     │                   │ await context.browser_session.close()  │                    │
     │                   │                    │                    │                    │
     │                   │ 3. 释放浏览器实例  │                    │                    │
     │                   │ release(instance)  │                    │                    │
     │                   ├───────────────────>│                    │                    │
     │                   │                    │ 决策：保留或关闭   │                    │
     │                   │                    │ if idle_count > threshold:             │
     │                   │                    │   close_instance() │                    │
     │                   │                    ├───────────────────>│                    │
     │                   │                    │                    │ browser.close()    │
     │                   │                    │                    ├───────────────────>│
     │                   │                    │                    │                    │ (关闭)
     │                   │                    │                    │<───────────────────┤
     │                   │                    │<───────────────────┤                    │
     │                   │<───────────────────┤                    │                    │
     │<──────────────────┤ {status: "destroyed"}                  │                    │
```

**关键点：**
- UnifiedSessionManager 统一管理 API 和 CLI 模式的会话
- BrowserPool 负责浏览器实例的分配和复用
- 支持本地和远程两种浏览器模式
- 自动监控会话健康状态和空闲超时

---

### 场景 7：Gateway 服务 - 浏览器资源池管理

```
客户端 (API/CLI) -> Gateway -> Docker/K8s -> 浏览器容器池
│                                                        │
└────────────────────────────────────────────────────────┘

详细流程：

┌─────────┐   ┌─────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│Client   │   │Gateway  │   │AuthManager   │   │BrowserPool   │   │Docker/K8s    │
│(API/CLI)│   │         │   │              │   │              │   │              │
└────┬────┘   └────┬────┘   └──────┬───────┘   └──────┬───────┘   └──────┬───────┘
     │             │                │                  │                  │
     │ POST /allocate               │                  │                  │
     │ (X-API-Key: key_abc123)      │                  │                  │
     ├────────────>│                │                  │                  │
     │             │ 1. 验证 API Key│                  │                  │
     │             ├───────────────>│                  │                  │
     │             │                │ 查询数据库/Redis │                  │
     │             │                │ if not exists:   │                  │
     │             │                │   return 401     │                  │
     │             │                │ if quota <= 0:   │                  │
     │             │                │   return 429     │                  │
     │             │<───────────────┤ {user_id, quota} │                  │
     │             │                │                  │                  │
     │             │ 2. 分配浏览器实例                 │                  │
     │             │ allocate(user_id)                 │                  │
     │             ├──────────────────────────────────>│                  │
     │             │                │                  │ 检查可用实例     │
     │             │                │                  │ if available:    │
     │             │                │                  │   return existing│
     │             │                │                  │ else:            │
     │             │                │                  │   create_new()   │
     │             │                │                  ├─────────────────>│
     │             │                │                  │ docker run \     │
     │             │                │                  │   --name browser_xxx \
     │             │                │                  │   -p 19222:19222 \
     │             │                │                  │   cloakbrowser   │
     │             │                │                  │                  │ (启动容器)
     │             │                │                  │<─────────────────┤
     │             │                │                  │ container_id     │
     │             │                │                  │ 等待健康检查     │
     │             │                │                  │ (CDP 连接测试)   │
     │             │<──────────────────────────────────┤ instance         │
     │             │                │                  │                  │
     │             │ 3. 生成访问 Token                 │                  │
     │             │ token = jwt.encode({              │                  │
     │             │   "instance_id": instance.id,     │                  │
     │             │   "user_id": user_id,             │                  │
     │             │   "exp": now + 3600               │                  │
     │             │ })             │                  │                  │
     │             │                │                  │                  │
     │             │ 4. 更新配额    │                  │                  │
     │             │ update_quota() │                  │                  │
     │             ├───────────────>│                  │                  │
     │             │                │ quota -= 1       │                  │
     │             │<───────────────┤                  │                  │
     │             │                │                  │                  │
     │             │ 5. 记录分配日志│                  │                  │
     │             │ log_allocation(user_id, instance_id, timestamp)      │
     │             │                │                  │                  │
     │<────────────┤ {instance_id, cdp_url, token, expires_in}           │
     │             │                │                  │                  │
     │ ... 使用浏览器 ...           │                  │                  │
     │             │                │                  │                  │
     │ POST /release                │                  │                  │
     │ (instance_id: browser_xxx)   │                  │                  │
     ├────────────>│                │                  │                  │
     │             │ 1. 验证 API Key│                  │                  │
     │             ├───────────────>│                  │                  │
     │             │<───────────────┤                  │                  │
     │             │                │                  │                  │
     │             │ 2. 释放实例    │                  │                  │
     │             │ release(instance_id)              │                  │
     │             ├──────────────────────────────────>│                  │
     │             │                │                  │ 决策：保留或销毁 │
     │             │                │                  │ if reusable:     │
     │             │                │                  │   mark_available │
     │             │                │                  │ else:            │
     │             │                │                  │   destroy()      │
     │             │                │                  ├─────────────────>│
     │             │                │                  │ docker stop      │
     │             │                │                  │ docker rm        │
     │             │                │                  │<─────────────────┤
     │             │<──────────────────────────────────┤                  │
     │             │                │                  │                  │
     │             │ 3. 更新配额    │                  │                  │
     │             │ update_quota() │                  │                  │
     │             ├───────────────>│                  │                  │
     │             │                │ quota += 1       │                  │
     │             │<───────────────┤                  │                  │
     │             │                │                  │                  │
     │<────────────┤ {status: "released"}             │                  │
     │             │                │                  │                  │
     │             │ [后台任务]     │                  │                  │
     │             │ _cleanup_expired_instances()      │                  │
     │             │ (定期清理超时未释放的实例)        │                  │
```

**关键点：**
- Gateway 作为独立服务，解耦认证和资源管理
- 支持 API Key 认证和配额管理
- 浏览器实例池支持复用，提高资源利用率
- 生成短期 JWT Token，增强安全性
- 后台任务定期清理过期实例

---

### 场景 8：反检测能力 - 5 层防护栈协作

```
BrowserController -> StealthEnhancer -> CloakBrowser -> patchright -> rebrowser-patches
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘

详细流程（以页面导航为例）：

┌──────────────────┐   ┌─────────────────┐   ┌──────────────┐   ┌───────────┐   ┌──────────────┐
│BrowserController │   │StealthEnhancer  │   │CloakBrowser  │   │patchright │   │rebrowser-    │
│                  │   │                 │   │              │   │           │   │patches       │
└────────┬─────────┘   └────────┬────────┘   └──────┬───────┘   └─────┬─────┘   └──────┬───────┘
         │                      │                    │                 │                │
         │ goto(url)            │                    │                 │                │
         ├─────────────────────>│                    │                 │                │
         │                      │                    │                 │                │
         │                      │ 1. 添加人类延迟   │                 │                │
         │                      │ await sleep(random.uniform(0.5, 1.5))                │
         │                      │                    │                 │                │
         │                      │ 2. 随机鼠标移动   │                 │                │
         │                      │ (模拟真实用户行为)│                 │                │
         │                      │                    │                 │                │
         │                      │ 3. 执行导航       │                 │                │
         │                      │ page.goto(url)     │                 │                │
         │                      ├───────────────────>│                 │                │
         │                      │                    │                 │                │
         │                      │                    │ 【第1层：C++ 编译级伪装】        │
         │                      │                    │ - 修改 navigator.webdriver = false
         │                      │                    │ - 伪装 Chrome 指纹（33处补丁）   │
         │                      │                    │ - 移除自动化特征               │
         │                      │                    │                 │                │
         │                      │                    │ CDP: Page.navigate              │
         │                      │                    ├────────────────>│                │
         │                      │                    │                 │                │
         │                      │                    │                 │ 【第2层：驱动级 CDP 补丁】
         │                      │                    │                 │ - 移除 __playwright__binding__
         │                      │                    │                 │ - 清理 CDP 泄漏标记           │
         │                      │                    │                 │                │
         │                      │                    │                 │ CDP 命令       │
         │                      │                    │                 ├───────────────>│
         │                      │                    │                 │                │
         │                      │                    │                 │                │ 【第3层：Runtime 泄漏修复】
         │                      │                    │                 │                │ - 修复 Runtime.Enable 泄漏
         │                      │                    │                 │                │ - addBinding 模式优化
         │                      │                    │                 │                │
         │                      │                    │                 │                │ 【第4层：非标准端口】
         │                      │                    │                 │                │ - CDP 端口 19222（非 9222）
         │                      │                    │                 │                │ - 绑定 127.0.0.1 混淆连接
         │                      │                    │                 │                │
         │                      │                    │                 │                │ 【第5层：持久化 CDP 会话】
         │                      │                    │                 │                │ - 单一 CDP 连接贯穿任务
         │                      │                    │                 │                │ - 避免频繁 attach/detach
         │                      │                    │                 │                │
         │                      │                    │                 │<───────────────┤
         │                      │                    │<────────────────┤                │
         │                      │<───────────────────┤                 │                │
         │                      │                    │                 │                │
         │                      │ 4. 等待页面加载   │                 │                │
         │                      │ (随机延迟)        │                 │                │
         │                      │ await sleep(random.uniform(1.0, 2.0))                │
         │                      │                    │                 │                │
         │<─────────────────────┤ {url, title}       │                 │                │
         │                      │                    │                 │                │
```

**5 层防护栈详解：**

1. **第 1 层：CloakBrowser（C++ 编译级伪装）**
   - 修改 Chromium 源码，33 处补丁
   - `navigator.webdriver = false`
   - 伪装 Chrome 指纹（User-Agent、Plugins、WebGL）
   - 移除自动化特征（`window.chrome.runtime`）

2. **第 2 层：patchright（驱动级 CDP 补丁）**
   - Playwright fork，移除 `__playwright__binding__`
   - 清理 CDP 协议中的自动化标记
   - 优化 CDP 命令序列

3. **第 3 层：rebrowser-patches（Runtime 泄漏修复）**
   - 修复 `Runtime.Enable` 导致的泄漏
   - 优化 `addBinding` 模式
   - 移除 DevTools 检测特征

4. **第 4 层：非标准端口 19222**
   - 使用 19222 而非标准 9222 端口
   - 绑定 127.0.0.1 混淆连接来源
   - 减少端口扫描检测风险

5. **第 5 层：持久化 CDP 会话**
   - 单一 CDP 连接贯穿整个任务生命周期
   - 避免频繁 attach/detach 循环（检测特征）
   - 保持浏览器进程稳定运行

**关键点：**
- 5 层防护栈协同工作，提供工业级反检测能力
- StealthEnhancer 在应用层添加人类行为模拟
- 所有层级对 API 和 CLI 模式透明，无需额外配置

---

### 场景 9：Token 优化 - DOM 压缩与选择性提取

```
BrowserController -> DOMCompressor -> browser-use -> Playwright -> 浏览器
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘

详细流程（以内容提取为例）：

┌──────────────────┐   ┌──────────────┐   ┌───────────────┐   ┌───────────┐   ┌─────────┐
│BrowserController │   │DOMCompressor │   │browser-use    │   │Playwright │   │Browser  │
│                  │   │              │   │               │   │           │   │         │
└────────┬─────────┘   └──────┬───────┘   └───────┬───────┘   └─────┬─────┘   └────┬────┘
         │                    │                    │                 │              │
         │ extract_content()  │                    │                 │              │
         │ (selector, type)   │                    │                 │              │
         ├───────────────────>│                    │                 │              │
         │                    │                    │                 │              │
         │                    │ 1. 获取完整 DOM   │                 │              │
         │                    │ get_state()        │                 │              │
         │                    ├───────────────────>│                 │              │
         │                    │                    │ page.content()  │              │
         │                    │                    ├────────────────>│              │
         │                    │                    │                 │ 获取 HTML    │
         │                    │                    │                 ├─────────────>│
         │                    │                    │                 │<─────────────┤
         │                    │                    │                 │ 完整 HTML    │
         │                    │                    │                 │ (可能 100KB+)│
         │                    │                    │<────────────────┤              │
         │                    │<───────────────────┤ raw_html        │              │
         │                    │                    │                 │              │
         │                    │ 2. DOM 压缩       │                 │              │
         │                    │ (browser-use 内置) │                 │              │
         │                    │ - 移除不可见元素   │                 │              │
         │                    │ - 移除 <style>     │                 │              │
         │                    │ - 移除 <script>    │                 │              │
         │                    │ - 简化属性         │                 │              │
         │                    │ - 保留交互元素     │                 │              │
         │                    │                    │                 │              │
         │                    │ 压缩后 DOM         │                 │              │
         │                    │ (约 10-20KB)       │                 │              │
         │                    │                    │                 │              │
         │                    │ 3. 选择性提取     │                 │              │
         │                    │ if type == "text": │                 │              │
         │                    │   extract_text_only()                │              │
         │                    │   (仅文本，约 1-5KB)                 │              │
         │                    │ elif type == "elements":             │              │
         │                    │   extract_elements(selector)         │              │
         │                    │   (仅匹配元素)     │                 │              │
         │                    │ elif type == "simplified_dom":       │              │
         │                    │   return compressed_dom              │              │
         │                    │                    │                 │              │
         │<───────────────────┤ {data, size_bytes} │                 │              │
         │                    │                    │                 │              │
         │ 4. 记录 Token 使用│                    │                 │              │
         │ tracer.record_step(│                    │                 │              │
         │   action="extract",│                    │                 │              │
         │   token_saved=90%  │                    │                 │              │
         │ )                  │                    │                 │              │
         │                    │                    │                 │              │
```

**Token 优化策略对比：**

| 提取方式 | 原始大小 | 压缩后大小 | Token 节省 | 适用场景 |
|---------|---------|-----------|-----------|---------|
| 完整 HTML | 100KB | 100KB | 0% | 调试、完整分析 |
| 压缩 DOM | 100KB | 15KB | 85% | 通用场景 |
| 纯文本 | 100KB | 3KB | 97% | 内容提取 |
| 选择性元素 | 100KB | 1KB | 99% | 精确提取 |

**实现细节：**

```python
# src/core/dom_compressor.py
class DOMCompressor:
    """DOM 压缩器，基于 browser-use 能力"""

    async def compress_dom(self, html: str) -> str:
        """压缩 DOM"""
        # 使用 browser-use 的内置压缩
        # 移除不可见元素、样式、脚本
        compressed = await self.browser_session.get_state()
        return compressed

    async def extract_text_only(self, selector: str) -> str:
        """仅提取文本（最省 Token）"""
        elements = await self.page.query_selector_all(selector)
        texts = [await el.inner_text() for el in elements]
        return "\n".join(texts)

    async def extract_elements(self, selector: str) -> list:
        """提取匹配元素（结构化）"""
        elements = await self.page.query_selector_all(selector)
        return [
            {
                "tag": await el.evaluate("el => el.tagName"),
                "text": await el.inner_text(),
                "attrs": await el.evaluate("el => Object.fromEntries([...el.attributes].map(a => [a.name, a.value]))")
            }
            for el in elements
        ]
```

**关键点：**
- 利用 browser-use 内置的 DOM 压缩能力
- 根据场景选择合适的提取方式
- 平均节省 85-99% 的 Token
- 对 API 和 CLI 模式透明

---

### 时序图总结

以上 9 个时序图覆盖了 agent-browser 重构后的核心场景：

1. **场景 1**：API 模式 + 本地浏览器 + 自主 Agent
2. **场景 2**：CLI 模式 + 本地浏览器 + 原子命令
3. **场景 3**：API 模式 + 远程浏览器 + Gateway 认证
4. **场景 4**：CLI 模式 + 远程浏览器 + Gateway 认证
5. **场景 5**：BrowserController 原子操作执行流程
6. **场景 6**：UnifiedSessionManager 会话生命周期管理
7. **场景 7**：Gateway 浏览器资源池管理
8. **场景 8**：5 层反检测防护栈协作
9. **场景 9**：DOM 压缩与 Token 优化

**模块交互关系总结：**

```
┌─────────────────────────────────────────────────────────────────┐
│                        接入层                                    │
│  ┌──────────────────┐              ┌──────────────────┐         │
│  │   API 模式       │              │   CLI 模式       │         │
│  │  (自主 Agent)    │              │  (原子命令)      │         │
│  └────────┬─────────┘              └────────┬─────────┘         │
└───────────┼────────────────────────────────┼───────────────────┘
            │                                │
            └────────────┬───────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────────┐
│                     核心能力层                                   │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  UnifiedSessionManager (统一会话管理)                    │  │
│  │  - 创建/销毁会话                                         │  │
│  │  - 本地/远程浏览器模式                                   │  │
│  │  - 会话监控和超时                                        │  │
│  └──────────────────┬───────────────────────────────────────┘  │
│                     │                                           │
│  ┌──────────────────▼───────────────────────────────────────┐  │
│  │  BrowserController (原子操作封装)                        │  │
│  │  - navigate: goto, back, forward, refresh                │  │
│  │  - interact: click, input, scroll, select                │  │
│  │  - extract: text, dom, screenshot, elements              │  │
│  │  - page: new, switch, close, list                        │  │
│  └──────────────────┬───────────────────────────────────────┘  │
│                     │                                           │
│  ┌──────────────────▼───────────────────────────────────────┐  │
│  │  StealthEnhancer (反检测增强)                            │  │
│  │  - 人类延迟、鼠标移动、行为模拟                          │  │
│  └──────────────────┬───────────────────────────────────────┘  │
│                     │                                           │
│  ┌──────────────────▼───────────────────────────────────────┐  │
│  │  ActionTracer (步骤跟踪)                                 │  │
│  │  - 记录每步操作、时间戳、参数、结果                      │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────┬───────────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────────┐
│                   浏览器管理层                                   │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  BrowserPool (浏览器实例池)                              │  │
│  │  - 本地实例分配/复用                                     │  │
│  │  - 远程实例连接                                          │  │
│  │  - 健康检查和清理                                        │  │
│  └──────────────────┬───────────────────────────────────────┘  │
│                     │                                           │
│         ┌───────────┴───────────┐                               │
│         │                       │                               │
│  ┌──────▼──────────┐   ┌────────▼────────┐                     │
│  │ LocalBrowser    │   │ RemoteBrowser   │                     │
│  │ Instance        │   │ Instance        │                     │
│  └──────┬──────────┘   └────────┬────────┘                     │
└─────────┼─────────────────────────┼───────────────────────────┘
          │                         │
          │                         │
┌─────────▼─────────┐     ┌─────────▼─────────────────────────────┐
│  CloakBrowser     │     │  Gateway (远程浏览器控制)             │
│  (本地进程)       │     │  - API Key 认证                       │
│  - CDP: 19222     │     │  - 资源分配和配额                     │
│  - 5层反检测      │     │  - Docker/K8s 容器管理                │
└───────────────────┘     │  - Token 生成和验证                   │
                          └───────────────────────────────────────┘
```

**数据流向：**

1. **API 模式**：用户 → API Server → SessionManager → BrowserController → browser-use Agent → LLM → Playwright → CloakBrowser
2. **CLI 模式**：外部 LLM → CLI → SessionManager → BrowserController → Playwright → CloakBrowser
3. **远程浏览器**：API/CLI → Gateway → Docker/K8s → CloakBrowser（容器）

**关键设计优势：**

- **职责清晰**：接入层、核心层、浏览器层各司其职
- **代码复用**：API 和 CLI 共享 70% 核心代码
- **灵活部署**：支持本地/远程、单机/分布式
- **安全可控**：Gateway 独立认证、Token 机制、配额管理
- **高性能**：连接池复用、DOM 压缩、并发控制
- **可观测**：ActionTracer 记录每步操作，便于调试和审计

---

