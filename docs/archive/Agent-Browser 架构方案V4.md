# Skill 架构优化方案：可配置化多模式支持

## Context

当前 `skills/stealth-browser/` 仅支持 local CDP 直连（硬编码 `127.0.0.1:19222`），没有模式切换、没有配置系统、没有 daemon 持久化。而 `src/` 下的 ConfigManager、Gateway、StealthEnhancer 等基础设施与 skill 包完全断开。本次优化目标：让 skill 通过配置化支持 **CLI/API 调用模式 × local/remote 浏览器模式 × LLM/Agent 智能模式**，并引入 opencli 风格的微 daemon 持久化。

---

## 模式矩阵

| 调用模式 | 浏览器模式 | 后端实现 | 智能模式 | 数据流 |
|---------|-----------|---------|---------|--------|
| CLI | local | LocalCDPBackend (daemon) | LLM (tool-use) | Agent → Python API → CDP |
| CLI | remote | **不支持** | — | — |
| API | local | RemoteAPIBackend → localhost FastAPI → LocalCDPBackend | LLM 或 Agent | Agent → HTTP → FastAPI → CDP |
| API | remote | RemoteAPIBackend → remote FastAPI → Gateway → Docker CDP | LLM 或 Agent | Agent → HTTP → FastAPI → Gateway → Docker → CDP |

---

## 核心架构原则：RemoteAPIBackend 是 LocalCDPBackend 的 HTTP 传输层

**关键洞察**：RemoteAPIBackend 不重新实现任何浏览器逻辑，它只是 LocalCDPBackend 的 HTTP 远程代理。

```
┌─────────────────────────────────────────────────────────┐
│                   Skill 客户端侧                        │
│                                                         │
│  ┌──────────────────┐    ┌───────────────────────────┐  │
│  │ LocalCDPBackend  │    │ RemoteAPIBackend          │  │
│  │ (直连 CDP)       │    │ (HTTP 传输适配器)          │  │
│  │                  │    │ - 翻译为 HTTP REST 调用    │  │
│  │ 同一套接口：      │    │ - 处理认证/session 映射   │  │
│  │ BrowserPageHandle│    │ - 返回同样的              │  │
│  │ StealthEnhancer  │    │   BrowserPageHandle 抽象  │  │
│  │ browser-use Agent│    │                           │  │
│  └────────┬─────────┘    └──────────┬────────────────┘  │
│           │ CDP                      │ HTTP              │
└───────────┼──────────────────────────┼───────────────────┘
            │                          │
            │    ┌─────────────────────┘
            │    │
            │    ▼
            │  ┌─────────────────────────────────────────┐
            │  │        FastAPI 服务端（独立进程/容器）    │
            │  │                                         │
            │  │  ┌───────────────────────────────────┐  │
            │  │  │    LocalCDPBackend（同一实现）      │  │
            │  │  │  ├─ StealthEnhancer               │  │
            │  │  │  ├─ browser-use Agent             │  │
            │  │  │  ├─ stealth_actions               │  │
            │  │  │  └─ adapters/pipeline/explore     │  │
            │  │  └───────────────┬───────────────────┘  │
            │  │                  │                       │
            │  │         浏览器模式路由：                  │
            │  │                  │                       │
            │  │  ┌───────────────┴───────────────┐      │
            │  │  │ local: 直连 CDP               │      │
            │  │  │ remote: → Gateway → Docker    │      │
            │  │  └───────────────────────────────┘      │
            │  └─────────────────────────────────────────┘
            │
            ▼
┌───────────────────────┐
│  本地 CloakBrowser     │
│  CDP: 127.0.0.1:19222 │
└───────────────────────┘
```

**这意味着**：
- LocalCDPBackend 是唯一的浏览器操作核心实现
- RemoteAPIBackend 只做 HTTP 序列化/反序列化，零业务逻辑
- FastAPI 服务端内部运行的也是 LocalCDPBackend
- 新功能（stealth、browser-use、adapters）只需在 LocalCDPBackend 实现一次，自动对两种后端生效

---

## 完整架构图（含 Gateway + Docker）

```
                         ┌─────────────────────────────┐
                         │         SKILL.md             │
                         │ (mode detection + routing)   │
                         └──────────────┬──────────────┘
                                        │
                         ┌──────────────▼──────────────┐
                         │     main.py (facade)         │
                         │  _ensure_backend() 路由       │
                         │  run_task() 智能模式路由      │
                         └──────┬───────────────┬───────┘
                                │               │
                 ┌──────────────▼──┐  ┌─────────▼──────────────┐
                 │ LocalCDPBackend │  │ RemoteAPIBackend       │
                 │ (本地直连)      │  │ (HTTP 传输适配器)       │
                 └──────┬──────────┘  └─────────┬──────────────┘
                        │ CDP                     │ HTTP
                        │              ┌──────────▼──────────────┐
                        │              │ FastAPI 服务             │
                        │              │  ├─ 会话管理 API        │
                        │              │  ├─ 原子操作 API        │
                        │              │  ├─ 任务提交 API        │
                        │              │  └─ 内部使用            │
                        │              │     LocalCDPBackend ────┼──┐
                        │              └─────────────────────────┘  │
                        │                                           │
                        │         ┌─────────────────────────────────┘
                        │         │ 浏览器模式路由
                        │         │
              ┌─────────▼─────────▼──────────────────────┐
              │            浏览器层                        │
              ├──────────────────┬────────────────────────┤
              │   local 模式     │      remote 模式        │
              │                  │                        │
              │ ┌──────────────┐ │ ┌────────────────────┐ │
              │ │ CloakBrowser │ │ │  Gateway :8001     │ │
              │ │ (本地进程)   │ │ │  ├─ API Key 认证   │ │
              │ │ CDP: 19222   │ │ │  ├─ 浏览器资源池   │ │
              │ └──────────────┘ │ │  ├─ CDP WebSocket  │ │
              │                  │ │  │   代理           │ │
              │                  │ │  └──────┬───────────┘ │
              │                  │ └────────┼─────────────┘ │
              │                  │          │               │
              │                  │ ┌────────▼─────────────┐ │
              │                  │ │  Docker / K8s        │ │
              │                  │ │ ┌──────────────────┐ │ │
              │                  │ │ │ CloakBrowser     │ │ │
              │                  │ │ │ (容器实例)       │ │ │
              │                  │ │ │ CDP: 19222       │ │ │
              │                  │ │ └──────────────────┘ │ │
              │                  │ │ 支持 HPA 弹性伸缩   │ │
              │                  │ └──────────────────────┘ │
              └──────────────────┴────────────────────────┘
                        │
              ┌─────────▼──────────────────────────────────┐
              │        共享核心层（skill 包内）              │
              │  StealthEnhancer │ stealth_actions          │
              │  browser-use Agent │ BrowserSession         │
              │  BrowserDaemon │ BrowserPageHandle          │
              │  adapters/ │ pipeline/ │ explore/ │ desktop │
              └─────────────────────────────────────────────┘
```

### 数据流详解

**场景 A：CLI + Local（最简单）**
```
Agent → LocalCDPBackend → BrowserDaemon → Playwright CDP → CloakBrowser
```

**场景 B：API + Local（单机服务）**
```
Agent → RemoteAPIBackend → HTTP → FastAPI → LocalCDPBackend → Playwright CDP → CloakBrowser
```

**场景 C：API + Remote（分布式）**
```
Agent → RemoteAPIBackend → HTTP → FastAPI → Gateway /allocate → Docker 创建容器
                                                     ↓
                              FastAPI → Gateway CDP Proxy → WebSocket → Docker CloakBrowser
```

**场景 D：CLI + Agent 模式（本地 AI 自主执行）**
```
Agent → LocalCDPBackend → browser-use Agent → LLM → Playwright CDP → CloakBrowser
                                  ↑
                         stealth_actions 覆盖默认行为
```

---

## 关键架构问题解答

### Q1: RemoteAPIBackend 如何操作 CDP 浏览器？

**核心理念：RemoteAPIBackend = HTTP 传输层 + LocalCDPBackend = 唯一核心实现**

RemoteAPIBackend 不实现任何浏览器逻辑。它只做一件事：将 `BrowserPageHandle` 的方法调用翻译为 HTTP REST 请求，发给 FastAPI 服务端。FastAPI 服务端内部运行的是**同一个** LocalCDPBackend。

```
客户端 RemoteAPIBackend              服务端 FastAPI
┌──────────────────────┐            ┌──────────────────────────┐
│ snapshot(sid)        │──HTTP──→  │ POST /sessions/{id}/     │
│                      │            │   snapshot               │
│                      │            │   ↓                      │
│                      │            │ LocalCDPBackend.snapshot()│
│                      │            │   ↓                      │
│                      │  ←──JSON── │ Playwright → CDP         │
│ return BrowserPage   │            └──────────────────────────┘
│   Handle 结果        │
└──────────────────────┘
```

**local 浏览器**：FastAPI 与 CloakBrowser 同机，LocalCDPBackend 直连 `127.0.0.1:19222`
**remote 浏览器**：FastAPI 通过 Gateway `/allocate` 获取 Docker 容器 CDP URL，LocalCDPBackend 连接远程 CDP

**优势**：
1. 浏览器操作只实现一次（LocalCDPBackend），HTTP 只是传输方式
2. 新功能（stealth、browser-use、adapters）只需加在 LocalCDPBackend，自动对 API 模式生效
3. FastAPI 本质是"远程 LocalCDPBackend 服务器"，不是独立实现

### Q2: LocalCDPBackend 和 RemoteAPIBackend 如何整合 browser-use 框架？

**browser-use 提供两层能力，两种后端分别使用不同层：**

```
┌─────────────────────────────────────────────────┐
│              browser-use 框架                    │
├─────────────────────────────────────────────────┤
│ 高层：Agent（自主决策循环）                      │
│  - Agent(task, llm, browser_session)            │
│  - 内置 LLM 驱动：observe → think → act → check │
│  - DOM 压缩 → LLM → action 执行                │
│  → Agent 模式使用 ✓                            │
├─────────────────────────────────────────────────┤
│ 底层：BrowserSession + Playwright（原子操作）    │
│  - BrowserSession(cdp_url=...)                  │
│  - page.goto(), page.evaluate(), page.click()   │
│  - 不依赖 LLM                                   │
│  → LLM 模式使用 ✓                              │
└─────────────────────────────────────────────────┘
```

**LocalCDPBackend**：
- **LLM 模式**：直接使用 Playwright `connect_over_cdp()`，不经过 browser-use。现有 `controller.py` 的 `page.evaluate()` 方式。
- **Agent 模式**：创建 `BrowserSession(cdp_url=..., is_local=True)` + `Agent(task, llm, browser_session)`，使用 `stealth_actions.py` 覆盖默认行为。

**RemoteAPIBackend**：
- **LLM 模式**：通过 HTTP 调用 FastAPI 的原子端点。FastAPI 内部使用 Playwright 直接操作。
- **Agent 模式**：通过 HTTP `POST /sessions/{id}/task` 提交任务。FastAPI 内部创建 browser-use Agent 自主执行。

### Q3: 非 Agent 模式和 Agent 模式如何整合？

**两种模式共享同一套后端和会话管理，区别在"谁做决策"：**

```
┌─────────────────────────────────────────────────────────────┐
│                      main.py facade                         │
├──────────────┬──────────────────────────────────────────────┤
│  LLM 模式    │  Agent 模式                                  │
│ (外部决策)   │ (内置决策)                                    │
├──────────────┼──────────────────────────────────────────────┤
│ 调用方：      │ 调用方：                                     │
│ Claude/GPT   │ user 提交 task                               │
│ 通过 ReAct   │ → run_task()                                 │
│ 循环决策     │ → browser-use Agent                          │
├──────────────┼──────────────────────────────────────────────┤
│ 工具集：      │ Agent 内部：                                 │
│ snapshot()   │ LLM 自动解析 DOM tree                        │
│ click()      │ LLM 选择 action (click/input/navigate)       │
│ fill()       │ Agent 自主循环 max_steps 轮                  │
│ scroll()     │ 返回最终结果                                  │
│ go_back()    │                                              │
│ delete_session│                                             │
├──────────────┼──────────────────────────────────────────────┤
│ 会话管理：    │ 会话管理：                                   │
│ create/delete│ create/delete (相同)                         │
│ (相同)       │                                              │
├──────────────┼──────────────────────────────────────────────┤
│ 隐匿保证：    │ 隐匿保证：                                   │
│ StealthEnhancer│ stealth_actions.py 覆盖 Agent 默认行为     │
│ → pipeline   │ register_stealth_actions(tools, stealth)    │
│ → 直接操作   │ 两种模式得分一致 (87.4-87.6/100)            │
└──────────────┴──────────────────────────────────────────────┘
```

**整合方式**：`main.py` 暴露统一接口，`intelligence/` 模块根据模式路由：

```python
# LLM 模式：外部 LLM 调用这些原子工具（通过 ReAct 循环）
async def create_session(...) -> str: ...     # 创建会话
async def snapshot(sid) -> Dict: ...          # 观察页面
async def click(sid, ref) -> None: ...        # 执行操作
async def fill(sid, ref, text) -> None: ...   # 执行操作
async def scroll(sid, dir, amt) -> None: ...  # 执行操作
async def delete_session(sid) -> None: ...    # 清理

# Agent 模式：提交任务，Agent 自主使用 browser-use 内部循环
async def run_task(sid, task, llm_config, max_steps) -> Dict: ...
```

---

## 功能问题解答

### F1: 怎么保证高度隐匿性？

**5 层反检测栈 + StealthEnhancer + stealth_actions 一致性保证：**

| 层级 | 组件 | 作用 | 两种模式是否一致 |
|------|------|------|-----------------|
| 1 | CloakBrowser | C++ 编译级指纹伪装（33处补丁） | ✅ 一致（底层浏览器相同） |
| 2 | patchright | 驱动级 CDP 补丁（移除 `__playwright__binding__`） | ✅ 一致 |
| 3 | rebrowser-patches | Runtime.Enable 泄漏修复（addBinding 模式） | ✅ 一致 |
| 4 | 非标准端口 19222 | 绑定 127.0.0.1 混淆连接 | ✅ 一致 |
| 5 | 持久化 CDP 会话 | 防止频繁 attach/detach 循环 | ✅ 一致（daemon 保持连接） |
| 6 | StealthEnhancer | 人类延迟 + 贝塞尔鼠标 + 逐字输入 | ✅ 一致 |
| 7 | stealth_actions.py | 覆盖 browser-use 默认行为 | LLM 模式用 StealthEnhancer<br>Agent 模式用 stealth_actions |

**关键**：`stealth_actions.py` 通过 `tools.registry.exclude_action()` + 重新注册来覆盖 browser-use Agent 的默认 navigate/click/input 操作，注入 StealthEnhancer 的延迟和鼠标模拟。**两种模式的隐匿得分一致（87.4-87.6/100）**。

**实现路径**：
- `skills/stealth-browser/stealth.py`：从 `src/core/stealth_enhancer.py` 移植（纯 Python，零重依赖）
- LLM 模式：StealthEnhancer 集成到 pipeline steps 和 `PlaywrightPageHandle`
- Agent 模式：`register_stealth_actions(tools, stealth)` 覆盖 browser-use Agent 的默认操作

### F2: 怎么节省 Token？

**三层 Token 节省策略，从最大效果到最小：**

#### 层 1：YAML 适配器 — 100% Token 节省（零 LLM 调用）

参考 opencli 的 200+ 适配器模式。已录制站点完全不需要 LLM：

```yaml
# adapters/baidu/search.yaml — 零 LLM 调用
site: baidu
name: search
strategy: cookie         # cookie 级别（需浏览器建立 cookie 上下文）
browser: true

pipeline:
  - navigate: https://www.baidu.com
  - wait: 1s
  - evaluate: |
      document.querySelector('#kw').value = '${{ args.query }}';
      document.querySelector('#su').click();
  - wait: 3s
  - select: "#content_left .result"
  - map:
      rank: ${{ index + 1 }}
      title: ${{ item.querySelector('h3').textContent }}
      url: ${{ item.querySelector('a').href }}
  - limit: ${{ args.limit }}
```

**效果**：`run_adapter("baidu", "search", query="AI")` → 直接执行 pipeline → 0 token。opencli 已有 200+ 适配器全部零 token。

#### 层 2：browser-use DOM 压缩 — 85-99% Token 节省

browser-use 内置多层压缩管线（Agent 模式自动使用）：

1. **Paint Order Filtering**：移除被遮挡的元素
2. **Bounding Box Filtering**：移除被父元素完全包含的子元素
3. **Attribute Filtering**：只保留 ~80 个关键属性
4. **Text Capping**：文本截断到 100 字符
5. **Message Compaction**：历史消息每 25 步压缩一次

```
完整 DOM → 简化树 → 可见元素 → 交互元素 → 紧凑文本
~500KB     ~100KB    ~20KB     ~5KB      ~2KB
```

配置项（`AgentSettings`）：
- `use_vision=False`：禁用截图（节省最多）
- `max_clickable_elements_length=40000`：DOM 最大字符数
- `flash_mode=True`：最小输出（仅 memory + action）
- `message_compaction`：自动压缩历史消息

#### 层 3：explore/synthesize — 新站点自适应生成适配器

遇到新站点时的自适应流程（现有 `explore/` 子系统）：

```
1. explore(url, goal)
   → 导航到页面 + 网络拦截 JSON API
   → 自动滚动触发懒加载
   → 发现 API 端点 + 字段角色推断
   → 输出 ExplorationResult

2. cascade(url, endpoints)
   → 从 public → cookie → header → intercept 逐级探测
   → 找到最小权限策略
   → 输出 strategy + sample_data

3. synthesize(site, artifacts, name)
   → 根据 strategy 生成 YAML 适配器
   → public: fetch + map pipeline
   → cookie: navigate + evaluate + map pipeline
   → 自动写入 adapters/{site}/{name}.yaml
```

**后续使用**：生成后，该站点变为层 1（零 token）。参考 opencli 的 `opencli generate` 一键生成流程。

#### 层 4：LLM 模式的 refs 快照 — 精简元素列表

当前 `refs_generator.py` 已实现精简化：
- 只返回 `button, a, input, textarea, select` 交互元素
- 每个元素仅返回 `{ref, text, role}` 三字段
- 避免返回完整 DOM 树

### F3: Skill 怎么实现 ReAct 交互效果？

**SKILL.md 作为 prompt 模板，根据 mode 动态生成不同的 ReAct 指令：**

#### LLM 模式的 ReAct（当前已实现，优化后增强）

```
Observe → Reason & Act → Check 循环：

1. Observe: snapshot(sid) → {url, title, elements: [{ref, text, role}]}
2. Reason: 外部 LLM 分析 elements，选择操作
3. Act: click(sid, @e3) / fill(sid, @e5, "text") / scroll(sid, "down")
4. Check: snapshot(sid) 验证结果
5. 循环直到任务完成
```

SKILL.md 定义完整的 ReAct prompt，包含：
- 工具列表和调用方式
- 元素引用格式（@e0, @e1）
- 错误处理策略
- 标准流程模板

#### Agent 模式的 ReAct（browser-use 内置）

```
Agent 内部循环（用户无感知）：

1. browser-use 获取 DOM state（压缩后的可访问性树）
2. LLM 推理下一步 action（structured output: AgentOutput）
3. 执行 action（navigate/click/input/scroll/extract/done）
4. 检查是否完成（done action 或 max_steps）
5. 循环
```

用户只需：`run_task(sid, "在Boss直聘搜索Python工程师", max_steps=10)`

#### 模式切换的 ReAct 适配

```python
# SKILL.md prompt routing 逻辑（在 SKILL.md 中描述，由 Claude 执行）：

if config.calling_mode == "cli" and config.intelligence == "llm":
    # 使用原子工具 ReAct 循环
    # → create_session → open_page → snapshot → [分析] → click/fill → snapshot → ... → delete_session

elif config.calling_mode == "api" and config.intelligence == "agent":
    # 使用 run_task 提交任务
    # → create_session → run_task(sid, task, max_steps=10) → [轮询结果] → delete_session

elif config.calling_mode == "api" and config.intelligence == "llm":
    # API 模式的原子操作（需 FastAPI 支持原子端点）
    # → create_session(api_url=...) → snapshot → click → ... → delete_session

elif config.intelligence == "agent" and config.calling_mode == "cli":
    # CLI + Agent：本地创建 browser-use Agent
    # → create_session → run_task(sid, task) → delete_session
```

**适配器优先的 ReAct**（opencli 模式）：

```
遇到任务时：
1. 检查 adapters/{site}/{command}.yaml 是否存在
2. 存在 → run_adapter(site, command, **args) → 零 token 执行
3. 不存在 → 判断是否可 explore
   a. 可 explore → explore → cascade → synthesize → 生成 adapter → 执行
   b. 不可 explore → 使用 LLM/Agent ReAct 模式执行
```

---

## 新增文件（8 个）

### 1. `skills/stealth-browser/config.py` — 配置管理器

从 `src/config/manager.py` 适配，无重依赖：

```python
@dataclass
class SkillConfig:
    calling_mode: str        # "cli" | "api"
    browser_mode: str        # "local" | "remote"
    intelligence: str        # "llm" | "agent"

    cdp_url: str             # "http://127.0.0.1:19222"
    api_url: str             # "http://localhost:8000"
    api_key: str             # Optional

    daemon_enabled: bool     # 是否启用 daemon 持久化
    daemon_idle_timeout: int # 秒，默认 1800
    daemon_state_path: str   # "~/.stealth-browser/daemon-state.json"

    headless: bool
    default_timeout: int     # ms
```

**配置解析优先级**：显式参数 → 环境变量 → `~/.stealth-browser/config.yaml` → 自动探测 → 硬编码默认

**自动探测逻辑**：
1. `http://localhost:8000/health` 可达 → API mode
2. `http://127.0.0.1:19222/json/version` 可达 → CLI mode
3. 默认 → CLI + local

### 2. `skills/stealth-browser/backends/__init__.py` — 后端抽象

```python
class BrowserBackend(ABC):
    """参考 opencli IBrowserFactory 模式"""
    async def connect(self) -> None
    async def disconnect(self) -> None
    async def is_connected(self) -> bool
    async def create_session(self, session_id: str) -> BrowserPageHandle
    async def delete_session(self, session_id: str)
    async def get_page(self, session_id: str) -> BrowserPageHandle

class BrowserPageHandle(ABC):
    """参考 opencli IPage/BasePage 模式 — 统一页面操作接口"""
    async def goto(url, wait_until, timeout)
    async def evaluate(expression) -> Any
    async def wait_for_selector(selector, timeout)
    async def go_back(wait_until, timeout)
    async def mouse_wheel(delta_x, delta_y)
    async def mouse_move(x, y)
    async def keyboard_press(key)
    async def title() -> str
    async def url() -> str
    async def on(event, handler)       # explore 网络拦截需要
    def remove_listener(event, handler)
    async def close()
```

### 3. `skills/stealth-browser/backends/local.py` — 本地 CDP 后端

- `LocalCDPBackend`：包装当前 `BrowserController`，使用 `BrowserDaemon` 管理持久连接
- `PlaywrightPageHandle`：薄 wrapper，委托 Playwright `Page`，集成 `StealthEnhancer`
- **95% 复用现有 `controller.py` 代码**
- Agent 模式：创建 `BrowserSession(cdp_url=..., is_local=True)` + `Agent(task, llm, browser_session)`，注入 `stealth_actions`

### 4. `skills/stealth-browser/backends/remote.py` — HTTP 传输适配器（薄包装）

**RemoteAPIBackend 不实现任何浏览器逻辑，它是 LocalCDPBackend 的 HTTP 代理。**

- `RemoteAPIBackend`：将 `BrowserPageHandle` 方法翻译为 HTTP REST 调用
- `RemotePageHandle`：实现 `BrowserPageHandle` 接口，内部全部是 aiohttp 调用
- 服务端（FastAPI）内部运行的是同一个 `LocalCDPBackend`

端点映射：
```python
# BrowserBackend 接口 → HTTP REST
create_session(sid)      → POST   /sessions/create       {session_id: sid}
delete_session(sid)      → DELETE /sessions/{id}
get_page(sid)            → 返回 RemotePageHandle(sid)     # 薄包装

# BrowserPageHandle 接口 → HTTP REST（LLM 模式）
goto(sid, url)           → POST   /sessions/{id}/navigate {url}
evaluate(sid, expr)      → POST   /sessions/{id}/evaluate {expression}
snapshot(sid)            → GET    /sessions/{id}/snapshot
click(sid, ref)          → POST   /sessions/{id}/click    {ref}
fill(sid, ref, text)     → POST   /sessions/{id}/fill     {ref, text}
scroll(sid, dir, amt)    → POST   /sessions/{id}/scroll   {direction, amount}

# Agent 模式
run_task(sid, task, ...) → POST   /sessions/{id}/task     {task, max_steps, ...}
get_task_result(sid,tid) → GET    /sessions/{id}/tasks/{tid}
```

**关键**：所有浏览器逻辑（StealthEnhancer、browser-use、adapters）在服务端的 LocalCDPBackend 中执行。RemoteAPIBackend 只处理 HTTP 序列化、认证、session 映射。

### 5. `skills/stealth-browser/daemon.py` — 微 Daemon

```python
class BrowserDaemon:
    """
    进程内持久化浏览器连接 singleton。
    参考 opencli 的 daemon + IdleManager 双条件模式。

    与 opencli daemon 的区别：
    - opencli 用独立 HTTP 进程（因为 CLI 每次是新的 subprocess）
    - 我们用进程内 singleton（因为 skill 运行在 Claude REPL 长生命周期中）
    - 共享：IdleManager 双条件退出、状态持久化、自动重连

    生命周期：
    - 首次浏览器命令时懒连接
    - 双条件空闲断开（无活跃 session 且超时）
    - 下次命令自动重连
    - 状态持久化到 ~/.stealth-browser/daemon-state.json
    """
```

### 6. `skills/stealth-browser/stealth.py` — StealthEnhancer

从 `src/core/stealth_enhancer.py` 移植核心逻辑（纯 Python，零重依赖）：
- `pre_action(action_type)` / `post_action()` — 按操作类型的随机延迟
- `human_type(page, selector, text)` — 逐字输入，50-250ms/字，5% typo + backspace
- `random_mouse_move(page)` — 贝塞尔曲线鼠标轨迹
- `human_scroll(page)` — 非均匀滚动，20% 回滚
- `inject_timing_noise(page)` — Date.now() / performance.now() 偏移
- `warmup_browsing(page)` — 访问 3 个站点建立正常基线

### 7. `skills/stealth-browser/intelligence/__init__.py` — 智能模式路由

```python
async def run_task(
    session_id: str,
    task: str,
    intelligence: str = "agent",
    llm_config: dict = None,
    max_steps: int = 6,
) -> dict:
    """
    统一任务入口。
    Agent 模式：创建 browser-use Agent 自主执行
    LLM 模式：返回工具描述，由外部 LLM 驱动 ReAct
    """
```

### 8. `skills/stealth-browser/intelligence/agent_runner.py` — Agent 模式执行器

从 `src/agent/runner.py` 和 `src/core/stealth_actions.py` 适配：
- 创建 `BrowserSession` + `Agent`
- 注入 `stealth_actions` 覆盖默认操作
- 支持分块执行（max_steps=6, stuck detection）
- 返回结构化结果

---

## 修改文件（7 个）

### 1. `skills/stealth-browser/main.py`
模式感知 facade，`_ensure_backend(config)` 路由到后端。保持向后兼容。新增 `run_task()`。

### 2. `skills/stealth-browser/session_manager.py`
从 `BrowserController` 改为 `BrowserBackend`。

### 3. `skills/stealth-browser/controller.py`
变为 `LocalCDPBackend` 内部实现（不删除，被包装）。

### 4. `skills/stealth-browser/pipeline/steps.py`
`_get_page()` 改为从 backend 获取 `BrowserPageHandle`。

### 5. `skills/stealth-browser/explore/explorer.py`
`session.page` → `backend.get_page(session_id)`。

### 6. `skills/stealth-browser/__init__.py`
新增导出：`run_task`, `detect_mode`, `SkillConfig`, `configure`。

### 7. `skills/stealth-browser/SKILL.md`
重写：三种模式配置、ReAct/Agent prompt routing、适配器优先策略。

---

## 不变文件

`refs_generator.py`, `adapters/loader.py`, `adapters/runner.py`, `pipeline/executor.py`, `pipeline/template.py`, `explore/synthesizer.py`, `explore/cascade.py`, `desktop/runner.py`, `desktop/cdp_discovery.py`, `desktop/applescript.py` — 通过 `main.py` facade 或纯逻辑，不需要直接修改。

---

## 实施阶段

### Phase 1：基础层 — 配置 + 后端抽象 + 隐匿增强
- 创建 `config.py`, `backends/__init__.py`, `backends/local.py`, `stealth.py`
- 修改 `main.py`, `session_manager.py`
- **验证**：所有现有调用不变；StealthEnhancer 在 LLM 模式生效

### Phase 2：微 Daemon 持久化
- 创建 `daemon.py`
- 修改 `backends/local.py` 使用 daemon
- **验证**：创建/删除 session 不重连 CDP；空闲超时自动断开；重连后恢复

### Phase 3：智能模式集成
- 创建 `intelligence/__init__.py`, `intelligence/agent_runner.py`
- 修改 `main.py` 添加 `run_task()`
- **验证**：LLM ReAct 和 Agent 自主模式均可用；stealth_actions 覆盖生效

### Phase 4：远程 API 后端
- 创建 `backends/remote.py`
- **验证**：API 模式可创建 session、提交 task、轮询结果

### Phase 5：子系统适配 + Token 优化
- 修改 `pipeline/steps.py`, `explore/explorer.py`
- 增强 adapters 的 explore/synthesize 流程
- **验证**：adapters、pipeline、explore 在两种后端下均可运行；新站点可自适应生成 adapter

### Phase 6：SKILL.md 重写
- 重写文档，描述模式配置、ReAct/Agent routing、适配器优先策略

---

## 关键参考文件

| 用途 | 文件路径 |
|------|---------|
| 现有 controller（→ LocalCDPBackend） | `skills/stealth-browser/controller.py` |
| 现有 facade（→ 模式路由） | `skills/stealth-browser/main.py` |
| 配置参考 | `src/config/manager.py` |
| 隐匿增强参考 | `src/core/stealth_enhancer.py` |
| stealth_actions 参考 | `src/core/stealth_actions.py` |
| browser-use Agent 集成参考 | `src/agent/runner.py` |
| Pipeline steps（→ 适配 BrowserPageHandle） | `skills/stealth-browser/pipeline/steps.py` |
| Daemon 参考 | `references/opencli/src/daemon.ts` |
| IdleManager 参考 | `references/opencli/src/idle-manager.ts` |
| IPage 抽象参考 | `references/opencli/src/browser/base-page.ts` |
| YAML 适配器模式参考 | `references/opencli/src/clis/` (200+ 适配器) |
| explore 自动生成参考 | `references/opencli/src/explore.ts` |
| V3 架构文档 | `docs/Stealth-Browser 架构方案V3.md` |

---

## 验证方案

1. **向后兼容**：现有 `create_session()` → `open_page()` → `snapshot()` → `click()` → `delete_session()` 无参数调用正常
2. **模式切换**：设置 `STEALTH_BROWSER_MODE=api` 后自动路由到 RemoteAPIBackend
3. **Daemon 持久化**：连续创建/删除 session 不触发 CDP 重连；空闲超时后自动断开
4. **Agent 模式**：`run_task(sid, "访问 example.com 提取标题")` 返回正确结果；stealth_actions 覆盖生效
5. **适配器兼容**：`run_adapter("baidu", "search", query="test")` 在 CLI 和 API 模式下均可执行（零 token）
6. **自适应生成**：对未知站点调用 `explore()` + `synthesize()` 生成 YAML 适配器
7. **隐匿一致性**：两种模式在 bot.sannysoft.com 上检测结果一致
