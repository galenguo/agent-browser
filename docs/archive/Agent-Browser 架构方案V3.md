# Stealth-Browser 架构方案V3

## 一、架构图解读

### 你的架构图核心要素

```
用户 → External LLM Agent → CLI/API Server → browser-use SDK组件 → 浏览器
                              ↓
                            Gateway (远程浏览器管理)
```

**关键组件：**
1. **External LLM Agent**：外部 LLM（如 Claude、GPT）负责决策
2. **CLI**：通过 skill 调用，执行原子命令
3. **API Server**：FastAPI 服务，内置 LLM，自主 Agent
4. **browser-use SDK 组件**：核心能力层（session manager、browser controller、browser session、playwright）
5. **Gateway**：远程浏览器资源管理（API Key 认证、创建/销毁浏览器）
6. **本地浏览器**：CloakBrowser 本地进程
7. **远程浏览器**：K8s/Docker 中的 CloakBrowser 容器

### 架构图的正确性验证

✅ **正确的部分：**
- External LLM Agent 通过 skill 调用 CLI
- CLI 和 API Server 都依赖 browser-use SDK 组件
- Gateway 负责远程浏览器的创建/销毁和 API Key 认证
- 支持本地和远程两种浏览器模式

⚠️ **需要澄清的部分：**
1. **LLM 的位置**：
   - API Server 内置 LLM（用于自主 Agent）
   - CLI 模式不包含 LLM，依赖外部 LLM Agent

2. **browser-use SDK 组件的分层**：
   - 应该明确区分"完整 Agent"和"原子能力"
   - API 模式使用 browser-use Agent（自主决策）
   - CLI 模式使用 browser-use 底层 API（BrowserSession + Playwright）

3. **Gateway 的定位**：
   - Gateway 是独立服务，不是 browser-use SDK 的一部分
   - API Server 和 CLI 都可以通过 Gateway 获取远程浏览器

---

## 二、精确的架构分层（基于你的图优化）

### 完整架构图

```
┌──────────┐
│  用户     │
└────┬─────┘
     │ 对话
     ▼
┌─────────────────┐
│ External LLM    │ ◄─── 外部 LLM（Claude/GPT）负责决策
│ Agent           │
└────┬────────────┘
     │
     │ skill 调用
     ▼
┌─────────────────────────────────────────────────────────────┐
│                      接入层 (Entry Layer)                    │
├──────────────────────────┬──────────────────────────────────┤
│      CLI 模式            │         API 模式                  │
│  (原子命令，被动)         │    (自主 Agent，主动)             │
│  - 依赖外部 LLM          │    - 内置 LLM                     │
│  - 返回 JSON             │    - 自主决策                     │
└──────────┬───────────────┴────────────┬─────────────────────┘
           │                            │
           └──────────┬─────────────────┘
                      │ 依赖
                      ▼
┌─────────────────────────────────────────────────────────────┐
│            browser-use SDK 组件 (Core Layer)                │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  UnifiedSessionManager (会话管理)                     │  │
│  │  - 创建/销毁会话                                      │  │
│  │  - 本地/远程浏览器选择                                │  │
│  └─────────────────────┬─────────────────────────────────┘  │
│                        │                                     │
│  ┌─────────────────────▼─────────────────────────────────┐  │
│  │  BrowserController (原子操作封装)                     │  │
│  │  - navigate, interact, extract, page                  │  │
│  │  - 保证隐匿性、节省 token、步骤跟踪                   │  │
│  └─────────────────────┬─────────────────────────────────┘  │
│                        │                                     │
│  ┌─────────────────────▼─────────────────────────────────┐  │
│  │  BrowserSession (browser-use 原生)                    │  │
│  │  - CDP 连接管理                                       │  │
│  │  - DOM 压缩                                           │  │
│  └─────────────────────┬─────────────────────────────────┘  │
│                        │                                     │
│  ┌─────────────────────▼─────────────────────────────────┐  │
│  │  Playwright (browser-use 依赖)                        │  │
│  │  - CDP 协议通信                                       │  │
│  └─────────────────────────────────────────────────────────┘  │
└─────────────────────────┬───────────────────────────────────┘
                          │ cdp_url
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                  浏览器层 (Browser Layer)                    │
├──────────────────────────┬──────────────────────────────────┤
│   本地浏览器              │        远程浏览器                 │
│  ┌────────────────┐      │   ┌──────────────────────────┐   │
│  │ CloakBrowser   │      │   │  Gateway (独立服务)       │   │
│  │ (本地进程)     │      │   │  - API Key 认证          │   │
│  │ CDP: 19222     │      │   │  - 创建/销毁浏览器        │   │
│  └────────────────┘      │   └──────┬───────────────────┘   │
│                          │          │                        │
│                          │          ▼                        │
│                          │   ┌──────────────────────────┐   │
│                          │   │ K8s/Docker               │   │
│                          │   │ ┌──────────────────────┐ │   │
│                          │   │ │ CloakBrowser (容器)  │ │   │
│                          │   │ │ CDP: 19222           │ │   │
│                          │   │ └──────────────────────┘ │   │
│                          │   └──────────────────────────┘   │
└──────────────────────────┴──────────────────────────────────┘
```

---

## 三、关键设计说明

### 3.1 两种模式的本质区别

| 维度 | CLI 模式 | API 模式 |
|------|---------|---------|
| **LLM 位置** | 外部（External LLM Agent） | 内置（FastAPI 进程） |
| **决策方** | 外部 LLM | browser-use Agent |
| **browser-use 使用** | 底层 API（BrowserSession + Playwright） | 完整 Agent（自主循环） |
| **交互方式** | 原子命令（每次一个操作） | 任务描述（自动执行多步） |
| **返回格式** | JSON（结构化数据） | 任务结果（最终输出） |
| **适用场景** | MCP skill、本地开发 | 独立服务、多用户 SaaS |

### 3.2 browser-use SDK 组件的分层使用

**关键理解：browser-use 提供两层能力**

```
┌─────────────────────────────────────────────┐
│         browser-use 框架                     │
├─────────────────────────────────────────────┤
│  高层：Agent (自主决策)                      │
│  - 完整的 LLM 驱动循环                       │
│  - 自动规划和执行                            │
│  - API 模式使用这一层 ✓                      │
├─────────────────────────────────────────────┤
│  底层：BrowserSession + Playwright (原子操作)│
│  - goto(), click(), extract_text()          │
│  - 不依赖 LLM                                │
│  - CLI 模式使用这一层 ✓                      │
└─────────────────────────────────────────────┘
```

**实现方式：**

```python
# API 模式：使用完整 Agent
from browser_use import Agent

agent = Agent(
    task="在 Boss 直聘搜索 Python 开发",
    llm=llm,  # 内置 LLM
    browser=browser
)
result = await agent.run()  # 自主执行多步操作

# CLI 模式：使用底层 API
from browser_use import BrowserSession

session = BrowserSession(cdp_url="http://localhost:19222")
await session.goto("https://www.zhipin.com")  # 单步操作
await session.click("#search-btn")  # 单步操作
text = await session.extract_text(".job-list")  # 单步操作
```

### 3.3 Gateway 的定位和职责

**Gateway 是独立的认证和资源管理服务**

```
┌─────────────────────────────────────────────┐
│  Gateway (独立 FastAPI 服务，端口 8001)     │
├─────────────────────────────────────────────┤
│  职责：                                      │
│  1. API Key 认证和配额管理                   │
│  2. 远程浏览器资源池管理                     │
│  3. Docker/K8s 容器创建/销毁                │
│  4. CDP URL 分发                            │
│  5. API Key 验证                   │
└─────────────────────────────────────────────┘
         ▲                    ▲
         │                    │
    ┌────┴────┐          ┌────┴────┐
    │ CLI     │          │ API     │
    │ 模式    │          │ 模式    │
    └─────────┘          └─────────┘
```

**Gateway 不负责：**
- ❌ 浏览器操作（由 BrowserController 负责）
- ❌ 会话管理（由 UnifiedSessionManager 负责）
- ❌ LLM 调用（由 API 模式或外部 LLM 负责）

**Gateway 只负责：**
- ✅ 认证：验证 API Key
- ✅ 分配：创建远程浏览器容器
- ✅ 释放：销毁浏览器容器
- ✅ 配额：管理用户使用限制

### 3.4 核心特性保证

**1. 反侦察（隐匿性）**
- 5 层防护栈：CloakBrowser + patchright + rebrowser-patches + 非标准端口 + 持久化会话
- StealthEnhancer：人类延迟、鼠标移动、行为模拟
- 对 API 和 CLI 模式透明

**2. 节省 Token**
- DOM 压缩：利用 browser-use 内置能力，节省 85%
- 选择性提取：text/html/elements，节省 97-99%
- 增量更新：只返回变化部分

**3. 高性能**
- 连接池复用：避免重复创建浏览器
- 并发控制：限制最大并发数
- 缓存策略：DOM 缓存、元素定位缓存

**4. 步骤可跟踪**
- ActionTracer：记录每步操作
- 返回格式包含 trace 信息
- 便于调试和审计

**5. 过程可反馈**
- CLI 模式：每步返回 JSON
- API 模式：任务状态查询
- 实时进度更新

---

## 四、数据流向详解

### 4.1 CLI 模式数据流

```
用户 → External LLM Agent → CLI 命令 → UnifiedSessionManager
                                ↓
                         BrowserController (原子操作)
                                ↓
                         BrowserSession (browser-use)
                                ↓
                         Playwright (CDP 协议)
                                ↓
                         CloakBrowser (本地/远程)
                                ↓
                         返回 JSON → External LLM Agent → 决策下一步
```

**关键点：**
- 外部 LLM 负责决策循环
- CLI 每次执行一个原子操作
- 返回结构化 JSON 供 LLM 解析

### 4.2 API 模式数据流

```
用户 → API Server → UnifiedSessionManager → BrowserController
                         ↓
                  browser-use Agent (内置 LLM)
                         ↓
                  自主决策循环 (多步操作)
                         ↓
                  BrowserSession → Playwright → CloakBrowser
                         ↓
                  返回最终结果 → 用户
```

**关键点：**
- API Server 内置 LLM
- browser-use Agent 自主执行多步操作
- 用户只需提交任务描述

### 4.3 远程浏览器数据流

```
CLI/API → Gateway (认证) → Docker/K8s (创建容器)
            ↓
       返回 cdp_url
            ↓
CLI/API → BrowserController → CDP 连接 → 远程 CloakBrowser
            ↓
       执行操作
            ↓
CLI/API → Gateway (释放) → Docker/K8s (销毁容器)
```

**关键点：**
- Gateway 只负责容器生命周期
- 实际操作通过 CDP 直连
- 支持 API Key 认证和配额管理

---

## 五、典型使用场景

### 5.1 场景 1：CLI 模式 + 本地浏览器

**用户需求：** 通过 MCP skill 在 Boss 直聘搜索职位

```bash
# 1. 创建会话
stealth-browser session create --name job-search --browser local
# 返回：{"session_id": "job-search", "cdp_url": "http://localhost:19222"}

# 2. 导航到网站
stealth-browser navigate goto --session job-search --url https://www.zhipin.com
# 返回：{"status": "success", "url": "https://www.zhipin.com", "trace": {...}}

# 3. 输入搜索关键词
stealth-browser interact input --session job-search --selector "#search-input" --text "Python开发"
# 返回：{"status": "success", "selector": "#search-input", "trace": {...}}

# 4. 点击搜索
stealth-browser interact click --session job-search --selector "#search-btn"
# 返回：{"status": "success", "selector": "#search-btn", "trace": {...}}

# 5. 提取结果
stealth-browser extract text --session job-search --selector ".job-list .job-item"
# 返回：{"status": "success", "text": "...", "trace": {...}}

# 6. 销毁会话
stealth-browser session destroy --session job-search
# 返回：{"status": "destroyed"}
```

**特点：**
- 外部 LLM（如 Claude）负责决策每一步
- CLI 执行原子操作，返回 JSON
- 本地浏览器，无需 Gateway

### 5.2 场景 2：API 模式 + 本地浏览器

**用户需求：** 独立部署的自动化服务

```bash
# 1. 创建会话
curl -X POST http://localhost:8000/sessions/create \
  -H "Content-Type: application/json" \
  -d '{"user_id": "alice", "browser_mode": "local"}'
# 返回：{"session_id": "alice_abc123"}

# 2. 提交任务（Agent 自主执行）
curl -X POST http://localhost:8000/sessions/alice_abc123/task \
  -H "Content-Type: application/json" \
  -d '{
    "task": "在 Boss 直聘搜索 Python 开发岗位，提取前 5 个结果",
    "llm_provider": "openai",
    "llm_model": "gpt-4o-mini"
  }'
# 返回：{"task_id": "task_xyz789", "status": "running"}

# 3. 查询任务状态
curl http://localhost:8000/sessions/alice_abc123/tasks/task_xyz789
# 返回：{"status": "completed", "result": [...]}
```

**特点：**
- API Server 内置 LLM
- browser-use Agent 自主执行多步操作
- 用户只需提交任务描述

### 5.3 场景 3：CLI 模式 + 远程浏览器 + Gateway

**用户需求：** 使用远程浏览器资源池

```bash
# 配置环境变量
export BROWSER_GATEWAY_URL=http://gateway:8001
export BROWSER_GATEWAY_KEY=key_abc123

# 1. 创建会话（自动通过 Gateway 分配浏览器）
stealth-browser session create --name remote-job --browser remote --use-gateway
# CLI 内部调用：Gateway /allocate → 返回 cdp_url
# 返回：{"session_id": "remote-job", "cdp_url": "http://10.0.1.5:19222"}

# 2-5. 执行操作（与本地浏览器相同）
stealth-browser navigate goto --session remote-job --url https://www.zhipin.com
# ...

# 6. 销毁会话（自动释放 Gateway 资源）
stealth-browser session destroy --session remote-job
# CLI 内部调用：Gateway /release
# 返回：{"status": "destroyed"}
```

**特点：**
- 通过 Gateway 获取远程浏览器
- API Key 认证和配额管理
- 自动资源释放

### 5.4 场景 4：API 模式 + 远程浏览器 + Gateway

**用户需求：** 多租户 SaaS 服务

```bash
# API Server 配置
export BROWSER_GATEWAY_URL=http://gateway:8001
export BROWSER_GATEWAY_KEY=service_key_xyz

# 1. 创建会话（自动通过 Gateway）
curl -X POST http://localhost:8000/sessions/create \
  -d '{"user_id": "bob", "browser_mode": "remote"}'
# 返回：{"session_id": "bob_def456", "cdp_url": "http://10.0.1.6:19222"}

# 2. 提交任务
curl -X POST http://localhost:8000/sessions/bob_def456/task \
  -d '{"task": "..."}'
# Agent 通过 CDP 连接远程浏览器执行
```

**特点：**
- 多用户隔离
- 远程浏览器资源池
- Gateway 统一管理

---

## 六、实施路径（8-9 周）

### Phase 1: 核心能力层（2-3 周）

**目标：** 提取 browser-use 原子能力，统一会话管理

**任务：**
1. 创建 `src/core/browser_controller.py`
   - 封装 20+ 原子方法（navigate、interact、extract、page）
   - 集成 StealthEnhancer（人类延迟、鼠标移动）
   - 集成 ActionTracer（步骤跟踪）

2. 创建 `src/core/session_manager.py`
   - UnifiedSessionManager 类
   - 支持本地/远程浏览器模式
   - 会话监控和超时

3. 测试
   - 单元测试：每个原子方法
   - 集成测试：会话生命周期

**交付物：**
- BrowserController（20+ 方法）
- UnifiedSessionManager
- 测试覆盖率 > 80%

### Phase 2: CLI 模式实现（2-3 周）

**目标：** 实现完整 CLI 命令集

**任务：**
1. 创建 CLI 框架
   - `src/cli/commands.py`：命令定义（Click）
   - `src/cli/output.py`：JSON 输出格式化
   - `src/cli/session_store.py`：本地会话存储

2. 实现命令组
   - session：create, list, info, destroy
   - navigate：goto, back, forward, refresh
   - interact：click, input, scroll, select
   - extract：text, dom, screenshot, elements
   - page：new, switch, close, list

3. 集成测试
   - E2E 测试：完整任务流程
   - MCP 集成测试

**交付物：**
- 20+ CLI 命令
- 完整文档和示例
- MCP skill 集成指南

### Phase 3: Gateway 服务（1-2 周）

**目标：** 实现独立的浏览器资源管理服务

**任务：**
1. 创建 Gateway 服务
   - `src/gateway/api.py`：FastAPI 服务（端口 8001）
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
- API Key 管理
- 部署文档

### Phase 4: API 模式增强（1 周）

**目标：** 重构 API 模式使用统一核心层

**任务：**
1. 重构 `src/api.py`
   - 使用 UnifiedSessionManager
   - 保持向后兼容
   - 添加新端点（可选：原子操作）

2. 文档更新
   - API 文档
   - 迁移指南

**交付物：**
- 重构后的 API（向后兼容）
- 完整文档

---

## 七、关键文件列表

### Phase 1: 核心能力层
- `src/core/browser_controller.py` (新建)
- `src/core/session_manager.py` (新建)
- `src/core/stealth_enhancer.py` (新建)
- `src/core/action_tracer.py` (新建)
- `src/browser/instance_pool.py` (重构)

### Phase 2: CLI 模式
- `src/cli/commands.py` (重构)
- `src/cli/output.py` (新建)
- `src/cli/session_store.py` (新建)

### Phase 3: Gateway 服务
- `src/gateway/api.py` (新建)
- `src/gateway/auth.py` (新建)
- `src/gateway/pool.py` (新建)

### Phase 4: API 模式
- `src/api.py` (重构)
- `src/session/pool_manager.py` (重构)

### 支持文件
- `src/models.py` (扩展)
- `requirements.txt` (更新)
- `tests/` (新增测试)

---

## 八、总结

### 核心设计原则

1. **职责分离**
   - 接入层：API（自主）vs CLI（被动）
   - 核心层：browser-use SDK 组件（70% 共享）
   - 浏览器层：本地 vs 远程
   - Gateway：独立认证服务

2. **browser-use 分层使用**
   - API 模式：使用完整 Agent（自主决策）
   - CLI 模式：使用底层 API（原子操作）

3. **Gateway 独立定位**
   - 只负责认证和资源管理
   - 不参与浏览器操作
   - API/CLI 通过 CDP 直连浏览器

4. **核心特性保证**
   - ✅ 反侦察：5 层防护栈
   - ✅ 节省 Token：DOM 压缩 85-99%
   - ✅ 高性能：连接池复用
   - ✅ 可跟踪：ActionTracer
   - ✅ 可反馈：JSON 输出

### 关键优势

- **代码复用**：API 和 CLI 共享 70% 核心代码
- **灵活部署**：本地/远程、单机/分布式
- **安全可控**：Gateway 认证、API Key、配额
- **易于扩展**：模块化设计，清晰边界

---

## 九、关键场景时序图

### 场景 1：CLI 模式 + 本地浏览器

```
External LLM → CLI → SessionManager → BrowserController → BrowserSession → Playwright → CloakBrowser

详细流程：

用户 → External LLM Agent
         │
         │ 决策：创建会话
         ├──> CLI: session create --browser local
         │      │
         │      ├──> SessionManager.create_session()
         │      │      ├──> BrowserPool.allocate_local()
         │      │      │      └──> 启动 CloakBrowser (CDP:19222)
         │      │      ├──> 创建 BrowserSession(cdp_url)
         │      │      └──> 创建 BrowserController
         │      │
         │      └──< {"session_id": "s1", "cdp_url": "..."}
         │
         ├──< JSON 输出
         │
         │ 决策：导航到 URL
         ├──> CLI: navigate goto --session s1 --url https://example.com
         │      │
         │      ├──> SessionManager.get_session("s1")
         │      ├──> BrowserController.goto(url)
         │      │      ├──> StealthEnhancer.add_delay()
         │      │      ├──> BrowserSession.page.goto(url)
         │      │      │      └──> Playwright → CDP → CloakBrowser
         │      │      └──> ActionTracer.record_step()
         │      │
         │      └──< {"url": "...", "title": "...", "trace": {...}}
         │
         ├──< JSON 输出
         │
         │ 决策：点击元素
         ├──> CLI: interact click --session s1 --selector "#btn"
         │      │
         │      ├──> BrowserController.click(selector)
         │      │      ├──> StealthEnhancer.add_delay()
         │      │      ├──> BrowserSession.page.click(selector)
         │      │      └──> ActionTracer.record_step()
         │      │
         │      └──< {"selector": "#btn", "trace": {...}}
         │
         └──< JSON 输出
```

**关键点：**
- 外部 LLM 负责每步决策
- CLI 执行原子操作
- 每步返回 JSON 供 LLM 解析

---

### 场景 2：API 模式 + 本地浏览器

```
用户 → API Server → SessionManager → browser-use Agent → LLM → BrowserSession → CloakBrowser

详细流程：

用户
 │
 ├──> POST /sessions/create {"user_id": "alice", "browser_mode": "local"}
 │      │
 │      ├──> SessionManager.create_session()
 │      │      ├──> BrowserPool.allocate_local()
 │      │      │      └──> 启动 CloakBrowser (CDP:19222)
 │      │      ├──> 创建 BrowserSession(cdp_url)
 │      │      └──> 创建 BrowserController
 │      │
 │      └──< {"session_id": "alice_abc123"}
 │
 ├──< HTTP 响应
 │
 ├──> POST /sessions/alice_abc123/task
 │      {"task": "在 Boss 直聘搜索 Python 开发"}
 │      │
 │      ├──> SessionManager.get_session("alice_abc123")
 │      ├──> 创建 browser-use Agent(task, llm, browser_session)
 │      ├──> 后台任务：agent.run()
 │      │      │
 │      │      ├──> LLM: 规划第 1 步
 │      │      ├──> BrowserSession.goto("https://www.zhipin.com")
 │      │      │      └──> Playwright → CDP → CloakBrowser
 │      │      │
 │      │      ├──> LLM: 规划第 2 步
 │      │      ├──> BrowserSession.input_text("#search", "Python开发")
 │      │      │
 │      │      ├──> LLM: 规划第 3 步
 │      │      ├──> BrowserSession.click("#search-btn")
 │      │      │
 │      │      ├──> LLM: 规划第 4 步
 │      │      ├──> BrowserSession.extract_text(".job-list")
 │      │      │
 │      │      └──> 返回结果
 │      │
 │      └──< {"task_id": "task_xyz", "status": "running"}
 │
 ├──< HTTP 响应
 │
 ├──> GET /sessions/alice_abc123/tasks/task_xyz
 │      │
 │      └──< {"status": "completed", "result": [...]}
 │
 └──< HTTP 响应
```

**关键点：**
- API Server 内置 LLM
- browser-use Agent 自主决策循环
- 用户只需提交任务描述

---

### 场景 3：CLI 模式 + 远程浏览器 + Gateway

```
External LLM → CLI → Gateway → Docker/K8s → 远程 CloakBrowser

详细流程：

用户 → External LLM Agent
         │
         │ 决策：创建远程会话
         ├──> CLI: session create --browser remote --use-gateway
         │      │
         │      ├──> Gateway: POST /allocate (X-API-Key: xxx)
         │      │      ├──> 验证 API Key
         │      │      ├──> 检查配额
         │      │      ├──> Docker/K8s: 创建容器
         │      │      │      └──> 启动 CloakBrowser 容器 (CDP:19222)
         │      │      └──< {"cdp_url": "http://10.0.1.5:19222", "instance_id": "..."}
         │      │
         │      ├──> SessionManager.create_session(browser_mode="remote", cdp_url)
         │      │      ├──> 创建 BrowserSession(cdp_url)
         │      │      └──> 创建 BrowserController
         │      │
         │      └──< {"session_id": "s1", "cdp_url": "http://10.0.1.5:19222"}
         │
         ├──< JSON 输出
         │
         │ 决策：执行操作
         ├──> CLI: navigate goto --session s1 --url https://example.com
         │      │
         │      ├──> BrowserController.goto(url)
         │      │      └──> BrowserSession → Playwright → CDP → 远程 CloakBrowser
         │      │
         │      └──< {"url": "...", "trace": {...}}
         │
         ├──< JSON 输出
         │
         │ 决策：销毁会话
         ├──> CLI: session destroy --session s1
         │      │
         │      ├──> SessionManager.destroy_session("s1")
         │      ├──> Gateway: POST /release (instance_id)
         │      │      ├──> Docker/K8s: 停止容器
         │      │      └──< {"status": "released"}
         │      │
         │      └──< {"status": "destroyed"}
         │
         └──< JSON 输出
```

**关键点：**
- Gateway 负责容器生命周期
- CLI 通过 CDP 直连远程浏览器
- 自动资源分配和释放

---

### 场景 4：API 模式 + 远程浏览器 + Gateway

```
用户 → API Server → Gateway → Docker/K8s → 远程 CloakBrowser → browser-use Agent

详细流程：

用户
 │
 ├──> POST /sessions/create {"user_id": "bob", "browser_mode": "remote"}
 │      │
 │      ├──> Gateway: POST /allocate (X-API-Key: service_key)
 │      │      ├──> 验证 API Key
 │      │      ├──> Docker/K8s: 创建容器
 │      │      │      └──> 启动 CloakBrowser 容器
 │      │      └──< {"cdp_url": "http://10.0.1.6:19222", "instance_id": "..."}
 │      │
 │      ├──> SessionManager.create_session(cdp_url)
 │      │      ├──> 创建 BrowserSession(cdp_url)
 │      │      └──> 创建 BrowserController
 │      │
 │      └──< {"session_id": "bob_def456"}
 │
 ├──< HTTP 响应
 │
 ├──> POST /sessions/bob_def456/task {"task": "..."}
 │      │
 │      ├──> 创建 browser-use Agent
 │      ├──> 后台任务：agent.run()
 │      │      └──> 通过 CDP 连接远程 CloakBrowser 执行
 │      │
 │      └──< {"task_id": "...", "status": "running"}
 │
 └──< HTTP 响应
```

**关键点：**
- API Server 通过 Gateway 获取远程浏览器
- Agent 通过 CDP 直连远程浏览器
- 多租户隔离

---

### 场景 5：Gateway 内部流程（资源分配）

```
CLI/API → Gateway → AuthManager → BrowserPool → Docker/K8s

详细流程：

CLI/API
 │
 ├──> POST /allocate (X-API-Key: key_abc123)
 │      │
 │      ├──> AuthManager.verify_key("key_abc123")
 │      │      ├──> 查询数据库/Redis
 │      │      ├──> 验证 API Key 有效性
 │      │      ├──> 检查配额 (quota > 0)
 │      │      └──< {"user_id": "alice", "quota": 10}
 │      │
 │      ├──> BrowserPool.allocate("alice")
 │      │      ├──> 检查可用实例
 │      │      ├──> 如果无可用实例：
 │      │      │      ├──> Docker/K8s: docker run cloakbrowser
 │      │      │      ├──> 等待健康检查 (CDP 连接测试)
 │      │      │      └──< container_id, cdp_url
 │      │      └──< instance
 │      │
 │      ├──> AuthManager.update_quota("alice", -1)
 │      │
 │      └──< {"cdp_url": "http://10.0.1.5:19222", "instance_id": "..."}
 │
 └──< HTTP 响应
```

**关键点：**
- Gateway 只负责认证和资源管理
- 不参与浏览器操作
- 支持配额管理

---

### 时序图总结

以上 5 个时序图覆盖了核心场景：

1. **场景 1**：CLI + 本地浏览器（外部 LLM 决策）
2. **场景 2**：API + 本地浏览器（内置 Agent 自主）
3. **场景 3**：CLI + 远程浏览器 + Gateway
4. **场景 4**：API + 远程浏览器 + Gateway
5. **场景 5**：Gateway 内部资源分配流程

**关键理解：**
- CLI 模式：外部 LLM → 原子命令 → browser-use 底层 API
- API 模式：内置 LLM → browser-use Agent → 自主决策
- Gateway：独立服务，只管认证和容器生命周期

---

## 十、现有代码重构方案

### 10.1 现有代码分析

**当前架构：**
```
src/
├── api.py                    # FastAPI 入口（需重构）
├── agent/runner.py           # Agent 运行器（保留）
├── browser/
│   ├── stealth_launcher.py   # 浏览器启动（保留）
│   ├── instance_pool.py      # 实例池（需重构）
│   └── human_behavior.py     # 行为模拟（保留）
├── session/
│   ├── pool_manager.py       # 会话池（需重构）
│   ├── profile_manager.py    # 配置管理（保留）
│   └── session_manager.py    # 会话管理（保留）
└── models.py                 # 数据模型（需扩展）
```

### 10.2 重构步骤

**Step 1: 创建核心能力层（新增）**

```python
# src/core/browser_controller.py (新建)
from browser_use import BrowserSession
from typing import Dict, Optional

class BrowserController:
    """browser-use 原子能力封装"""

    def __init__(self, browser_session: BrowserSession):
        self.session = browser_session
        self.page = browser_session.current_page
        self.tracer = ActionTracer()

    # 导航操作
    async def goto(self, url: str) -> Dict:
        await asyncio.sleep(random.uniform(0.5, 1.5))  # 人类延迟
        await self.page.goto(url)
        step = self.tracer.record_step("goto", {"url": url}, {"status": "success"})
        return {"url": self.page.url, "title": await self.page.title(), "trace": step}

    async def go_back(self) -> Dict:
        await self.page.go_back()
        return {"url": self.page.url}

    # 交互操作
    async def click(self, selector: str) -> Dict:
        await asyncio.sleep(random.uniform(0.1, 0.3))
        await self.page.click(selector)
        step = self.tracer.record_step("click", {"selector": selector}, {"status": "success"})
        return {"selector": selector, "trace": step}

    async def input_text(self, selector: str, text: str) -> Dict:
        await self.page.fill(selector, text)
        return {"selector": selector, "text": text}

    # 提取操作
    async def extract_text(self, selector: str) -> Dict:
        element = await self.page.query_selector(selector)
        text = await element.inner_text() if element else None
        return {"selector": selector, "text": text}
```

**Step 2: 创建统一会话管理器（新建）**

```python
# src/core/session_manager.py (新建)
from typing import Dict, Literal, Optional
from dataclasses import dataclass
import time

@dataclass
class SessionContext:
    session_id: str
    browser_instance: BrowserInstance
    browser_session: BrowserSession
    controller: BrowserController
    created_at: float = field(default_factory=time.time)

class UnifiedSessionManager:
    """统一会话管理，支持 API 和 CLI"""

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
        # 分配浏览器
        if browser_mode == "local":
            instance = await self.browser_pool.allocate_local(session_id)
            cdp_url = instance.cdp_url
        else:
            instance = RemoteBrowserInstance(cdp_url=cdp_url)

        # 创建 BrowserSession
        browser_session = BrowserSession(
            browser_profile=BrowserProfile(cdp_url=cdp_url)
        )

        # 创建 Controller
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
        if session_id not in self.sessions:
            raise SessionNotFoundError(f"Session {session_id} not found")
        return self.sessions[session_id]

    async def destroy_session(self, session_id: str):
        context = self.sessions.pop(session_id, None)
        if context:
            await context.browser_session.close()
            await self.browser_pool.release(context.browser_instance)
```

**Step 3: 实现 CLI 命令（新建）**

```python
# src/cli/commands.py (新建)
import click
import json
import asyncio
from core.session_manager import UnifiedSessionManager

session_mgr = UnifiedSessionManager(mode="cli")

@click.group()
def cli():
    """Stealth Browser CLI"""
    pass

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
        "data": {"session_id": context.session_id, "cdp_url": context.browser_instance.cdp_url}
    }

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

**Step 4: 重构 API 模式（修改现有）**

```python
# src/api.py (重构)
from core.session_manager import UnifiedSessionManager

# 使用统一会话管理器
session_mgr = UnifiedSessionManager(mode="api")

@app.post("/sessions/create")
async def create_session(request: CreateSessionRequest):
    """创建会话（使用统一管理器）"""
    context = await session_mgr.create_session(
        session_id=f"{request.user_id}_{uuid4().hex[:8]}",
        browser_mode=request.browser_mode,
    )
    return {"session_id": context.session_id}

@app.post("/sessions/{session_id}/task")
async def submit_task(session_id: str, request: SubmitTaskRequest):
    """提交任务（使用 browser-use Agent）"""
    context = await session_mgr.get_session(session_id)

    # API 模式：使用完整 Agent
    from browser_use import Agent
    llm = create_llm(request.llm_config)
    agent = Agent(
        task=request.task,
        llm=llm,
        browser_session=context.browser_session,
    )

    task_id = f"task_{uuid4().hex[:8]}"
    asyncio.create_task(_run_agent(session_id, task_id, agent))

    return {"task_id": task_id, "status": "running"}
```

**Step 5: 实现 Gateway 服务（新建）**

```python
# src/gateway/api.py (新建)
from fastapi import FastAPI, Header, HTTPException

app = FastAPI(title="Browser Gateway")

API_KEYS = {
    "key_abc123": {"user": "alice", "quota": 10},
}

@app.post("/allocate")
async def allocate_browser(x_api_key: str = Header(...)):
    """分配浏览器资源"""
    if x_api_key not in API_KEYS:
        raise HTTPException(status_code=401, detail="Invalid API key")

    user_info = API_KEYS[x_api_key]
    if user_info["quota"] <= 0:
        raise HTTPException(status_code=429, detail="Quota exceeded")

    # 分配浏览器实例
    instance = await browser_pool.allocate(user=user_info["user"])

    return {
        "instance_id": instance.instance_id,
        "cdp_url": instance.cdp_url,
    }

@app.post("/release")
async def release_browser(instance_id: str, x_api_key: str = Header(...)):
    """释放浏览器资源"""
    await browser_pool.release(instance_id)
    return {"status": "released"}
```

---

## 十一、自动化测试方案

### 11.1 测试场景覆盖

**7 个核心测试场景：**

1. CLI + 本地浏览器 + 基本操作
2. CLI + 本地浏览器 + 完整任务流程
3. API + 本地浏览器 + Agent 自主执行
4. CLI + 远程浏览器 + Gateway
5. API + 远程浏览器 + Gateway
6. 反检测能力验证
7. Token 优化验证

### 11.2 测试实现

**场景 1: CLI + 本地浏览器 + 基本操作**

```python
# tests/test_cli_local_basic.py
import pytest
import subprocess
import json

@pytest.mark.asyncio
async def test_cli_local_basic_operations():
    """测试 CLI 本地浏览器基本操作"""

    # 1. 创建会话
    result = subprocess.run(
        ["stealth-browser", "session", "create", "--name", "test1", "--browser", "local"],
        capture_output=True, text=True
    )
    data = json.loads(result.stdout)
    assert data["status"] == "success"
    session_id = data["data"]["session_id"]

    # 2. 导航
    result = subprocess.run(
        ["stealth-browser", "navigate", "goto", "--session", session_id, "--url", "https://example.com"],
        capture_output=True, text=True
    )
    data = json.loads(result.stdout)
    assert data["status"] == "success"
    assert "example.com" in data["data"]["url"]

    # 3. 提取文本
    result = subprocess.run(
        ["stealth-browser", "extract", "text", "--session", session_id, "--selector", "h1"],
        capture_output=True, text=True
    )
    data = json.loads(result.stdout)
    assert data["status"] == "success"
    assert "Example Domain" in data["data"]["text"]

    # 4. 销毁会话
    result = subprocess.run(
        ["stealth-browser", "session", "destroy", "--session", session_id],
        capture_output=True, text=True
    )
    data = json.loads(result.stdout)
    assert data["status"] == "destroyed"
```

**场景 2: CLI + 本地浏览器 + 完整任务流程**

```python
# tests/test_cli_local_full_task.py
import pytest
import subprocess
import json

@pytest.mark.asyncio
async def test_cli_local_full_task():
    """测试 CLI 完整任务流程（模拟 Boss 直聘搜索）"""

    session_id = None
    try:
        # 创建会话
        result = subprocess.run(
            ["stealth-browser", "session", "create", "--name", "job-search", "--browser", "local"],
            capture_output=True, text=True
        )
        session_id = json.loads(result.stdout)["data"]["session_id"]

        # 导航到 Boss 直聘
        subprocess.run(
            ["stealth-browser", "navigate", "goto", "--session", session_id, "--url", "https://www.zhipin.com"],
            capture_output=True, text=True
        )

        # 输入搜索关键词
        subprocess.run(
            ["stealth-browser", "interact", "input", "--session", session_id, "--selector", "#search-input", "--text", "Python开发"],
            capture_output=True, text=True
        )

        # 点击搜索按钮
        subprocess.run(
            ["stealth-browser", "interact", "click", "--session", session_id, "--selector", "#search-btn"],
            capture_output=True, text=True
        )

        # 提取结果
        result = subprocess.run(
            ["stealth-browser", "extract", "text", "--session", session_id, "--selector", ".job-list"],
            capture_output=True, text=True
        )
        data = json.loads(result.stdout)
        assert data["status"] == "success"
        assert len(data["data"]["text"]) > 0

    finally:
        if session_id:
            subprocess.run(
                ["stealth-browser", "session", "destroy", "--session", session_id],
                capture_output=True, text=True
            )
```

**场景 3: API + 本地浏览器 + Agent 自主执行**

```python
# tests/test_api_local_agent.py
import pytest
import httpx

@pytest.mark.asyncio
async def test_api_local_agent():
    """测试 API 模式 Agent 自主执行"""

    async with httpx.AsyncClient() as client:
        # 创建会话
        response = await client.post(
            "http://localhost:8000/sessions/create",
            json={"user_id": "test_user", "browser_mode": "local"}
        )
        assert response.status_code == 200
        session_id = response.json()["session_id"]

        # 提交任务
        response = await client.post(
            f"http://localhost:8000/sessions/{session_id}/task",
            json={
                "task": "访问 example.com 并提取标题",
                "llm_provider": "openai",
                "llm_model": "gpt-4o-mini"
            }
        )
        assert response.status_code == 200
        task_id = response.json()["task_id"]

        # 等待任务完成
        import asyncio
        await asyncio.sleep(10)

        # 查询任务状态
        response = await client.get(
            f"http://localhost:8000/sessions/{session_id}/tasks/{task_id}"
        )
        assert response.status_code == 200
        assert response.json()["status"] == "completed"
```

**场景 4: CLI + 远程浏览器 + Gateway**

```python
# tests/test_cli_remote_gateway.py
import pytest
import subprocess
import json
import os

@pytest.mark.asyncio
async def test_cli_remote_gateway():
    """测试 CLI 远程浏览器 + Gateway"""

    # 设置环境变量
    os.environ["BROWSER_GATEWAY_URL"] = "http://localhost:8001"
    os.environ["BROWSER_GATEWAY_KEY"] = "test_key_123"

    session_id = None
    try:
        # 创建远程会话
        result = subprocess.run(
            ["stealth-browser", "session", "create", "--name", "remote1", "--browser", "remote", "--use-gateway"],
            capture_output=True, text=True
        )
        data = json.loads(result.stdout)
        assert data["status"] == "success"
        session_id = data["data"]["session_id"]
        assert "cdp_url" in data["data"]

        # 执行操作
        result = subprocess.run(
            ["stealth-browser", "navigate", "goto", "--session", session_id, "--url", "https://example.com"],
            capture_output=True, text=True
        )
        assert json.loads(result.stdout)["status"] == "success"

    finally:
        if session_id:
            subprocess.run(
                ["stealth-browser", "session", "destroy", "--session", session_id],
                capture_output=True, text=True
            )
```


**场景 5: API + 远程浏览器 + Gateway**

```python
# tests/test_api_remote_gateway.py
import pytest
import httpx

@pytest.mark.asyncio
async def test_api_remote_gateway():
    """测试 API 远程浏览器 + Gateway"""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8000/sessions/create",
            json={"user_id": "remote_user", "browser_mode": "remote"}
        )
        assert response.status_code == 200
```

**场景 6: 反检测能力验证**

```python
# tests/test_anti_detection.py
import pytest

@pytest.mark.asyncio
async def test_anti_detection():
    """验证 5 层反检测能力"""
    controller = await create_test_controller()
    await controller.goto("https://bot.sannysoft.com")
    result = await controller.extract_text("body")
    assert "webdriver: false" in result["text"].lower()
```

**场景 7: Token 优化验证**

```python
# tests/test_token_optimization.py
import pytest

@pytest.mark.asyncio
async def test_token_optimization():
    """验证 DOM 压缩"""
    controller = await create_test_controller()
    await controller.goto("https://example.com")
    full = await controller.extract_html("body")
    compressed = await controller.get_dom(simplified=True)
    ratio = (len(full["html"]) - len(compressed["dom"])) / len(full["html"])
    assert ratio > 0.80
```


---

## 十二、测试执行和修复流程

### 12.1 测试执行步骤

**1. 环境准备**

```bash
# 安装依赖
pip install -r requirements.txt
pip install pytest pytest-asyncio httpx

# 启动 Gateway（如果测试远程浏览器）
cd src/gateway
uvicorn api:app --port 8001 &

# 启动 API Server
cd src
uvicorn api:app --port 8000 &
```

**2. 运行测试**

```bash
# 运行所有测试
pytest tests/ -v

# 运行特定场景
pytest tests/test_cli_local_basic.py -v
pytest tests/test_api_local_agent.py -v

# 生成覆盖率报告
pytest tests/ --cov=src --cov-report=html
```

**3. 测试顺序**

```
Phase 1: 核心能力层测试
├── test_browser_controller.py
├── test_session_manager.py
└── test_action_tracer.py

Phase 2: CLI 模式测试
├── test_cli_local_basic.py
└── test_cli_local_full_task.py

Phase 3: Gateway 测试
├── test_gateway_auth.py
├── test_cli_remote_gateway.py
└── test_api_remote_gateway.py

Phase 4: 集成测试
├── test_anti_detection.py
└── test_token_optimization.py
```


### 12.2 常见问题和修复

**问题 1: 浏览器启动失败**

```python
# 错误：CloakBrowser 启动超时
# 修复：增加启动超时时间，检查端口占用

async def launch_browser_with_retry(max_retries=3):
    for i in range(max_retries):
        try:
            browser = await launch_stealth_browser()
            return browser
        except TimeoutError:
            if i < max_retries - 1:
                await asyncio.sleep(5)
            else:
                raise
```

**问题 2: CDP 连接失败**

```python
# 错误：无法连接到 CDP
# 修复：验证 CDP URL，添加重试机制

async def connect_cdp_with_retry(cdp_url, max_retries=3):
    for i in range(max_retries):
        try:
            session = BrowserSession(cdp_url=cdp_url)
            await session.connect()
            return session
        except Exception as e:
            if i < max_retries - 1:
                await asyncio.sleep(2)
            else:
                raise
```

**问题 3: Gateway 认证失败**

```python
# 错误：401 Unauthorized
# 修复：检查 API Key 配置

# 确保环境变量正确
assert os.getenv("BROWSER_GATEWAY_KEY"), "Gateway key not set"
```


### 12.3 自动化修复流程

**修复脚本：**

```bash
# scripts/auto_fix.sh
#!/bin/bash

echo "开始自动修复流程..."

# 1. 运行测试并捕获失败
pytest tests/ -v --tb=short > test_results.txt 2>&1

# 2. 分析失败原因
if grep -q "TimeoutError" test_results.txt; then
    echo "检测到超时错误，增加超时时间..."
    # 自动调整配置
fi

if grep -q "ConnectionError" test_results.txt; then
    echo "检测到连接错误，检查服务状态..."
    # 重启服务
fi

# 3. 重新运行失败的测试
pytest tests/ --lf -v

echo "修复完成"
```

### 12.4 验收标准

**必须通过的测试：**

- ✅ 所有 7 个场景测试通过
- ✅ 测试覆盖率 > 80%
- ✅ 无内存泄漏
- ✅ 反检测测试通过
- ✅ Token 压缩率 > 80%

**性能指标：**

- 会话创建时间 < 3s
- 单次操作响应时间 < 1s
- 并发 10 个会话无错误


---

## 十三、实施检查清单

### Phase 1: 核心能力层（2-3 周）

- [ ] 创建 `src/core/browser_controller.py`
- [ ] 创建 `src/core/session_manager.py`
- [ ] 创建 `src/core/action_tracer.py`
- [ ] 单元测试覆盖率 > 80%

### Phase 2: CLI 模式（2-3 周）

- [ ] 创建 `src/cli/commands.py`
- [ ] 实现 20+ CLI 命令
- [ ] 测试场景 1、2 通过

### Phase 3: Gateway 服务（1-2 周）

- [ ] 创建 `src/gateway/api.py`
- [ ] 实现认证和资源管理
- [ ] 测试场景 4、5 通过

### Phase 4: API 重构（1 周）

- [ ] 重构 `src/api.py`
- [ ] 测试场景 3 通过
- [ ] 向后兼容验证

### 最终验收

- [ ] 所有 7 个测试场景通过
- [ ] 测试覆盖率 > 80%
- [ ] 性能指标达标
- [ ] 文档完整

---

## 总结

本方案提供了完整的重构路径：

1. **架构清晰**：接入层、核心层、浏览器层、Gateway 分离
2. **代码复用**：70% 核心代码共享
3. **测试完善**：7 个场景全覆盖
4. **自动化**：测试和修复流程自动化

**关键文件：**
- `/Users/galen/.claude/plans/lovely-painting-nest.md` - 本方案
- `/Users/galen/.claude/plans/lovely-painting-nest-agent-a041139ab1fe5cf95.md` - 详细时序图


---

## 十四、Gateway CDP 代理方案

### 14.1 架构调整

**原方案（直连）：**
```
客户端 → Gateway /allocate → 返回 cdp_url: http://10.0.1.5:19222
客户端 → 直接连接浏览器 CDP
```

**新方案（代理）：**
```
客户端 → Gateway /allocate → 返回 cdp_url: ws://gateway:8001/cdp?apikey=xxx&instance=yyy
客户端 → Gateway CDP 代理 → 转发到浏览器
```

**关键变化：**
- CDP URL 指向 Gateway
- URL 参数包含 apikey 和 instance
- Gateway 作为 WebSocket 代理


### 14.2 CDP 协议技术栈

**CDP (Chrome DevTools Protocol)：**
- 基于 WebSocket 协议
- JSON-RPC 2.0 消息格式
- 双向通信（命令/事件）

**消息示例：**
```json
// 客户端 → 浏览器
{"id": 1, "method": "Page.navigate", "params": {"url": "https://example.com"}}

// 浏览器 → 客户端  
{"id": 1, "result": {"frameId": "xxx"}}
```

### 14.3 性能分析

**技术选型：FastAPI + websockets**
- 并发能力：~1000 WebSocket 连接
- 延迟增加：+5ms（可接受）
- 优点：与现有技术栈一致

**性能指标：**
- 10-100 个浏览器实例：足够
- 单个连接带宽：~1MB/s
- 总带宽需求：~100MB/s


### 14.4 Gateway CDP 代理实现

```python
# src/gateway/cdp_proxy.py (新建)
from fastapi import WebSocket, Query
import websockets
import asyncio

@app.websocket("/cdp")
async def cdp_proxy(
    websocket: WebSocket,
    apikey: str = Query(...),
    instance: str = Query(...)
):
    """CDP WebSocket 代理"""
    
    # 验证 API Key
    if apikey not in API_KEYS:
        await websocket.close(code=1008, reason="Invalid API key")
        return
    
    # 获取真实 CDP URL
    real_cdp_url = await get_instance_cdp_url(instance)
    if not real_cdp_url:
        await websocket.close(code=1008, reason="Instance not found")
        return
    
    await websocket.accept()
    
    # 连接真实浏览器并双向转发
    async with websockets.connect(real_cdp_url) as browser_ws:
        await asyncio.gather(
            forward(websocket, browser_ws),
            forward(browser_ws, websocket)
        )

async def forward(src, dst):
    """转发消息"""
    try:
        while True:
            if hasattr(src, 'receive_text'):
                data = await src.receive_text()
                await dst.send(data)
            else:
                async for data in src:
                    await dst.send_text(data)
    except:
        pass
```


### 14.5 /allocate 端点修改

```python
# src/gateway/api.py (修改)
@app.post("/allocate")
async def allocate_browser(x_api_key: str = Header(...)):
    """分配浏览器资源"""
    if x_api_key not in API_KEYS:
        raise HTTPException(status_code=401)
    
    user_info = API_KEYS[x_api_key]
    instance = await browser_pool.allocate(user=user_info["user"])
    
    # 返回 Gateway 代理 URL
    gateway_host = os.getenv("GATEWAY_PUBLIC_HOST", "localhost:8001")
    cdp_url = f"ws://{gateway_host}/cdp?apikey={x_api_key}&instance={instance.instance_id}"
    
    return {
        "instance_id": instance.instance_id,
        "cdp_url": cdp_url,
    }
```


### 14.6 新的数据流

```
CLI/API → Gateway /allocate
         ↓
      返回 cdp_url: ws://gateway:8001/cdp?apikey=xxx&instance=yyy
         ↓
CLI/API → 连接 Gateway WebSocket
         ↓
      Gateway 验证 apikey
         ↓
      Gateway 转发到真实浏览器 (http://10.0.1.5:19222)
         ↓
      双向消息转发
```

### 14.7 优缺点分析

**优点：**
- ✅ 统一认证：所有请求都通过 Gateway
- ✅ 安全性：浏览器不直接暴露
- ✅ 可观测：Gateway 可记录所有 CDP 消息
- ✅ 灵活性：可添加限流、审计

**缺点：**
- ❌ 延迟增加：+5ms
- ❌ 单点故障：Gateway 挂了全挂
- ❌ 带宽瓶颈：所有流量经过 Gateway

**缓解措施：**
- Gateway 高可用部署（多实例 + 负载均衡）
- 监控 Gateway 性能指标


### 14.8 更新时序图（场景 3：CLI + 远程浏览器）

```
用户 → External LLM Agent
         │
         ├──> CLI: session create --browser remote --use-gateway
         │      │
         │      ├──> Gateway: POST /allocate (X-API-Key: xxx)
         │      │      ├──> 验证 API Key
         │      │      ├──> Docker/K8s: 创建容器
         │      │      │      └──> 启动 CloakBrowser (内网 CDP:19222)
         │      │      └──< {"cdp_url": "ws://gateway:8001/cdp?apikey=xxx&instance=yyy"}
         │      │
         │      ├──> SessionManager.create_session(cdp_url)
         │      │      └──> BrowserSession(cdp_url) → WebSocket → Gateway → 浏览器
         │      │
         │      └──< {"session_id": "s1"}
         │
         ├──> CLI: navigate goto --session s1 --url https://example.com
         │      ├──> BrowserController.goto()
         │      │      └──> CDP 消息 → Gateway → 浏览器
         │      └──< JSON 输出
         │
         └──> CLI: session destroy --session s1
                ├──> Gateway: POST /release (X-API-Key: xxx) {instance_id: yyy}
                └──> Docker/K8s: 销毁容器
```


### 14.9 方案一致性说明

**需要同步更新的位置：**

1. **场景 3 时序图**（已更新）：cdp_url 指向 Gateway 代理
2. **场景 4 时序图**：API 模式同样使用 Gateway 代理 cdp_url
3. **场景 5 时序图（Gateway 内部）**：/allocate 返回代理 URL
4. **Gateway 实现代码**：添加 /cdp WebSocket 端点
5. **BrowserSession 连接**：通过 ws://gateway/cdp?apikey&instance 连接

**核心原则：**
- 内网浏览器 CDP 端口不对外暴露
- 所有 CDP 流量经过 Gateway
- API Key 在 URL query 参数中传递
- Gateway 根据 instance_id 查找真实 CDP URL 并转发

**内网 vs 外网：**
```
外网（客户端侧）：
  ws://gateway:8001/cdp?apikey=xxx&instance=yyy

内网（Gateway 侧）：
  ws://10.0.1.5:19222/devtools/browser/xxx
```


---

## 十五、API Key 管理与状态持久化

### 15.1 两类数据区分

| 数据类型 | 内容 | 特点 |
|---------|------|------|
| API Key 配置 | key、用户、配额上限 | 静态，手动维护 |
| 运行时状态 | 哪个 key 占用哪个 instance | 动态，随会话变化 |

### 15.2 API Key 管理：keys.yaml

```yaml
# config/keys.yaml（手动维护，类似 htpasswd）
keys:
  - key: "sk_alice_abc123"
    user: "alice"
    quota: 10          # 最大并发实例数
    enabled: true
  - key: "sk_bob_def456"
    user: "bob"
    quota: 5
    enabled: true
```

**热重载：**
```python
import yaml
from watchfiles import awatch

class KeyStore:
    def __init__(self, path="config/keys.yaml"):
        self.path = path
        self.keys: dict[str, KeyInfo] = {}
        self.load()

    def load(self):
        with open(self.path) as f:
            data = yaml.safe_load(f)
        self.keys = {k["key"]: KeyInfo(**k) for k in data["keys"]}

    async def watch(self):
        """文件变更自动热重载"""
        async for _ in awatch(self.path):
            self.load()
```

### 15.3 运行时状态：内存 + JSON 快照

```python
# src/gateway/state.py
import json
import asyncio
from pathlib import Path

class GatewayState:
    def __init__(self, snapshot_path="data/state.json", interval=10):
        self.snapshot_path = Path(snapshot_path)
        self.interval = interval
        # 内存状态
        self.allocations: dict[str, Allocation] = {}
        # {instance_id: {apikey, user, cdp_url, created_at}}

    def allocate(self, instance_id, apikey, user, cdp_url):
        self.allocations[instance_id] = Allocation(
            instance_id=instance_id,
            apikey=apikey,
            user=user,
            cdp_url=cdp_url,
        )

    def release(self, instance_id):
        self.allocations.pop(instance_id, None)

    def save(self):
        """快照到 JSON"""
        self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.snapshot_path, "w") as f:
            json.dump(
                {k: v.__dict__ for k, v in self.allocations.items()}, f
            )

    async def auto_save(self):
        """定期快照（每 10 秒）"""
        while True:
            await asyncio.sleep(self.interval)
            self.save()
```

### 15.4 重启恢复流程

```python
    async def restore(self):
        """重启后恢复状态"""
        if not self.snapshot_path.exists():
            return

        with open(self.snapshot_path) as f:
            data = json.load(f)

        for instance_id, info in data.items():
            # 检查容器是否存活（ping CDP 端口）
            alive = await self._check_cdp_alive(info["cdp_url"])
            if alive:
                self.allocations[instance_id] = Allocation(**info)
            # 不存活则丢弃，容器已消失

    async def _check_cdp_alive(self, cdp_url: str) -> bool:
        """检查 CDP 端口是否可连接"""
        import aiohttp
        try:
            async with aiohttp.ClientSession() as s:
                # 真实 CDP URL（内网）
                async with s.get(cdp_url.replace("ws://", "http://") + "/json",
                                  timeout=aiohttp.ClientTimeout(total=2)):
                    return True
        except:
            return False
```

### 15.5 Gateway 启动流程

```python
# src/gateway/api.py
@app.on_event("startup")
async def startup():
    # 1. 加载 API Key
    key_store.load()
    asyncio.create_task(key_store.watch())   # 热重载

    # 2. 恢复运行时状态
    await state.restore()

    # 3. 启动定期快照
    asyncio.create_task(state.auto_save())

@app.on_event("shutdown")
async def shutdown():
    # 关闭前最后一次快照
    state.save()
```

### 15.6 文件结构

```
gateway/
├── config/
│   └── keys.yaml        # API Key 配置（手动维护）
├── data/
│   └── state.json       # 运行时快照（自动生成）
└── src/gateway/
    ├── api.py
    ├── cdp_proxy.py
    ├── state.py          # 状态管理
    └── key_store.py      # Key 管理
```

### 15.7 方案优缺点

**优点：**
- ✅ 无数据库依赖
- ✅ 运维简单（只需维护 keys.yaml）
- ✅ 热重载（新增/禁用 key 无需重启）
- ✅ 重启自动恢复（验证存活性）
- ✅ 快照间隔可配置

**缺点：**
- ❌ 快照间隔内（默认 10s）重启会丢失新分配
- ❌ 多 Gateway 实例需要共享文件（NFS/挂载卷）

**缓解措施：**
- 缩短快照间隔（可调为 3s）
- 或在 allocate/release 时同步写快照（牺牲少量性能）

