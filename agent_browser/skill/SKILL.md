---
name: agent-browser
argument-hint: <task description>
description: >
  Anti-detection browser automation for Claude Code. Create sessions, navigate pages,
  click/fill elements, extract data with 7-layer stealth protection. Supports local
  browser (CloakBrowser), Chrome Extension (natural fingerprints), and remote API mode.
  Trigger on: "帮我访问", "打开浏览器", "扫码登录", "自动化浏览", "网页采集",
    "浏览器操作", "帮我打开网站", "open website", "search for", "browse",
    "scrape", "fill form", "visit url", "help me browse", "automate browser".
  Proactively use when user mentions interacting with websites, collecting data, or
  automating browser tasks.
---

# Agent Browser -- 多模式浏览器自动化

> **ARGUMENTS Handling**: ARGUMENTS is a natural language task description. If it contains surrounding double quotes (`"..."`), strip them first. Treat the entire ARGUMENTS as a single task -- never split on quotes or special characters inside.
>
> **Execution Environment**: ALWAYS use `.venv/bin/python3` (never bare `python3`) from the project root. Detect the project root dynamically:
> ```python
> import os, sys
> # Method A: from installed package
> import agent_browser.skill as _mod
> project_root = os.path.dirname(os.path.dirname(_mod.__file__))
> # Method B: from source checkout (fallback)
> if not os.path.exists(os.path.join(project_root, 'pyproject.toml')):
>     project_root = os.path.dirname(os.path.abspath('.'))
> sys.path.insert(0, project_root)
> from agent_browser import create_session, snapshot, click, fill
> ```

## Quick Start (首次使用清单)

Copy this checklist and track progress:

```
Setup Progress:
- [ ] Step 1: Run environment diagnostic (doctor.py)
- [ ] Step 2: Auto-fix missing dependencies
- [ ] Step 3: Select optimal mode (Extension > Local > Remote)
- [ ] Step 4: Create session + verify connection
- [ ] Step 5: Execute task via ReAct loop or Agent mode
```

### Step 1: Detect Environment

```python
import asyncio, sys
sys.path.insert(0, '/path/to/project/root')  # or use dynamic detection above
from agent_browser.skill.scripts.doctor import run_diagnosis

report = await run_diagnosis()
# report.ready == True -> skip to Step 4
# report.ready == False -> proceed to Step 2
```

### Step 2: Auto-Fix Dependencies

The doctor report lists fixable issues. For each fixable dep:

```python
for dep in report.fixable:
    print(f"Installing {dep.name}: {dep.fix_command}")
    # Run the fix_command via bash (pip install, playwright install, etc.)
```

For `needs_human` items (e.g., LLM API key), present options to the user and continue without blocking.

### Step 3: Select Mode

Auto-detection handles this, but you can force a mode:

| Priority | Mode | When it's used |
|----------|------|---------------|
| 1 | **Extension** | Chrome Extension connected (user's real Chrome, natural fingerprints) |
| 2 | **Local** | CloakBrowser CDP reachable at 127.0.0.1:19222 (anti-detection) |
| 3 | **Remote** | FastAPI server at localhost:8000 (HTTP transport) |

Mode auto-detected by `_ensure_backend()`. Override with `configure(mode="api")` or env var `AGENT_BROWSER_CALLING_MODE`.

### Step 4: Create Session

```python
from agent_browser import create_session

session_id = await create_session()
# Returns a UUID string like "a1b2c3d4..."
```

### Step 5: Execute Task

See **ReAct Workflow** below for LLM mode (atomic operations), or **Agent Mode** for autonomous execution.

---

## 工作模式

| 模式 | 组合 | 数据流 |
|------|------|--------|
| CLI + LLM（默认） | LocalCDPBackend → Playwright CDP | Agent → Python API → CDP |
| CLI + Agent | LocalCDPBackend → browser-use Agent → CDP | Agent → run_task → CDP |
| API + LLM | RemoteAPIBackend → HTTP → FastAPI → CDP | Agent → HTTP → FastAPI → CDP |
| API + Agent | RemoteAPIBackend → HTTP → FastAPI → browser-use | Agent → HTTP → FastAPI → Agent → CDP |

**自动检测**: `curl -s http://localhost:8000/health` 成功 → API 模式，否则 CLI 模式。

**手动配置**:
```python
from agent_browser import configure
configure(mode="api", api_url="http://localhost:8000")
# 或通过环境变量
# AGENT_BROWSER_CALLING_MODE=api
# AGENT_BROWSER_API_URL=http://localhost:8000
```

---

## 模式优先级

Backend selection order when multiple modes are available:

1. **Extension** (if Chrome Extension connected via WebSocket port 19825) -- your real Chrome, natural fingerprints, inherits login state
2. **Local** (CLI mode, CloakBrowser at 127.0.0.1:19222) -- full 7-layer anti-detection
3. **Remote** (API mode, localhost:8000 health check passes) -- HTTP transport to FastAPI server

Extension is tried first regardless of calling_mode. If unavailable, falls back to mode-gated selection.

---

## 模式 1：LLM ReAct（原子操作）

外部 LLM（Claude/GPT）通过 ReAct 循环控制每一步。

### Observe → Reason & Act → Check 循环

```
┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
│ Observe  │→  │ Reason   │→  │ Act      │→  │ Check    │
│          │   │          │   │          │   │          │
│ snapshot │   │ Analyze  │   │ Execute  │   │ Verify   │
│ elements │   │ elements │   │ action   │   │ result   │
│ URL/title│   │ Plan next│   │ (click/  │   │ Loop or  │
│          │   │ step     │   │ fill/    │   │ done     │
└──────────┘   └──────────┘   └──────────┘   └──────────┘
     ↑                                              │
     └──────────── retry on failure ←───────────────┘
                    (max 3 retries per action)
```

**1. Observe（观察）**
```python
session_id = await create_session()
await open_page(session_id, "https://example.com")
snap = await snapshot(session_id)
# 返回 {url, title, elements: [{ref, text, role}...]}
```

**2. Reason & Act（推理并行动）**
```python
for el in snap["elements"]:
    if "搜索" in el.get("text", ""):
        await fill(session_id, el["ref"], "关键词")
    if "提交" in el.get("text", ""):
        await click(session_id, el["ref"])
```

**3. Check（验证）**
```python
snap2 = await snapshot(session_id)
# 检查 URL 变化、目标元素、数据是否提取到
```

### 可用操作

| 操作 | 函数 | 说明 |
|------|------|------|
| 创建会话 | `create_session(mode?, api_url?, cdp_url?)` | 默认 http://127.0.0.1:19222 |
| 打开页面 | `open_page(sid, url)` | 导航到 URL |
| 获取快照 | `snapshot(sid)` | 返回页面状态 + 元素列表 |
| 点击元素 | `click(sid, ref)` | 点击 @eN 元素 |
| 填充输入 | `fill(sid, ref, text)` | 在 @eN 输入框填入文本 |
| 滚动页面 | `scroll(sid, dir, amt)` | dir="down"/"up"，默认 500px |
| 悬停元素 | `hover(sid, ref)` | 悬停在 @eN 元素上 |
| 选择下拉 | `select_option(sid, ref, value)` | 选择下拉选项 |
| 按键 | `press_key(sid, key)` | Enter, Tab, Escape 等 |
| 等待元素 | `wait_for_selector(sid, selector)` | 等待选择器出现 |
| 后退 | `go_back(sid)` | 后退到上一页 |
| 关闭会话 | `delete_session(sid)` | 释放浏览器资源 |

**元素引用格式**: `@e0`, `@e1`, `@e2`...（通过 snapshot获取）

**快照返回字段**:
```python
{
    "url": "当前页面 URL",
    "title": "页面标题",
    "elements": [{"ref": "@e0", "text": "...", "role": "a"}, ...]
}
```

### Human Handoff Points（何时暂停询问用户）

Stop and ask the user when:
- **Login required** -- "I see a login page. Please log in, then tell me when ready."
- **Captcha detected** -- "There's a captcha. Please solve it, then tell me."
- **Unexpected modal/dialog** -- "Something popped up. What should I do?"
- **3 consecutive failures** -- "I'm stuck on [specific element]. Options: try different approach / skip this step / show you what I see."

---

## 模式 2：Agent 自主执行（browser-use）

内置 LLM Agent 自主完成整个任务，无需外部 ReAct 循环。

```python
import asyncio, sys
sys.path.insert(0, '/path/to/project/root')  # use dynamic detection above
from agent_browser import create_session, delete_session, run_task

sid = await create_session()
result = await run_task(
    sid,
    task="访问百度搜索 AI coding，提取前5条结果标题和链接",
    intelligence="agent",
    max_steps=10,
)
print(result["result"])
await delete_session(sid)

# result = {"status": "completed" | "failed" | "stuck", "result": "...", "steps": 8, "chunks": 2}
```

**Agent 模式参数**:
- `task`: 任务描述（中文或英文）
- `intelligence`: "agent"（默认）或 "llm"
- `llm_config`: LLM 配置（可选，默认从环境变量读取）
  ```python
  llm_config = {
      "provider": "openai",  # "openai" | "anthropic"
      "model": "gpt-4o",
      "api_key": "sk-...",
      "base_url": "https://api.openai.com/v1",
  }
  ```
- `max_steps`: 每块最大步数（默认 6）

**环境变量配置**:
```bash
AGENT_BROWSER_LLM_PROVIDER=openai    # 或 anthropic
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.openai.com/v1
```

---

## 标准流程

### 简单导航/提取（LLM 模式）
```
1. create_session → open_page → snapshot → [分析元素] → delete_session
```

### 搜索任务（LLM 模式）
```
1. create_session → open_page(搜索页) → snapshot
2. 找搜索框 → fill(搜索词)
3. snapshot → 找搜索按钮 → click
4. 等待加载 → snapshot → 提取结果
5. delete_session
```

### 自主任务（Agent 模式）
```
1. create_session → run_task(sid, "任务描述", max_steps=10) → delete_session
```

### 适配器优先（零 LLM 成本）
```
1. 检查 run_adapter(site, command) 是否存在
2. 存在 → 直接执行 pipeline（零 token）
3. 不存在 → explore → synthesize → 生成适配器 → 下次零 token
```

---

## 远程模式

### LLM 模式（原子操作）
```bash
# 创建会话
SID=$(curl -s -X POST http://localhost:8000/sessions/create \
  -d '{"user_id":"test","browser_mode":"local"}' | jq -r '.session_id')

# 快照
curl -s http://localhost:8000/sessions/$SID/snapshot

# 点击
curl -s -X POST http://localhost:8000/sessions/$SID/click -d '{"ref":"@e3"}'

# 清理
curl -s -X DELETE http://localhost:8000/sessions/$SID
```

### Agent 模式（任务提交）
```bash
# 提交任务
TASK=$(curl -s -X POST http://localhost:8000/sessions/$SID/task \
  -d '{"task":"任务描述","max_steps":6}')
TID=$(echo $TASK | jq -r '.task_id')

# 轮询状态
while true; do
  STATUS=$(curl -s http://localhost:8000/sessions/$SID/tasks/$TID)
  STATE=$(echo $STATUS | jq -r '.status')
  [ "$STATE" = "completed" ] || [ "$STATE" = "failed" ] && break
  sleep 5
done
```

---

## Extension Mode（Chrome 扩展）

For natural fingerprints and inherited login state, load the included Chrome extension.

### Setup (one-time):

1. Build/load the extension from `extension/` directory into Chrome (`chrome://extensions/` -> "Developer mode" -> "Load unpacked")
2. Ensure agent-browser daemon is running (starts automatically on first `create_session()`)
3. Extension auto-connects to `ws://127.0.0.1:19825/ext`
4. Badge shows green when connected, click toolbar icon to see popup status panel

### When Extension mode activates:

- `calling_mode=cli` + Extension connected -> automatic
- Falls back to LocalCDPBackend if Extension unavailable
- Disable explicitly: `AGENT_BROWSER_EXTENSION_ENABLED=false`

### Popup Panel:

Clicking the extension icon opens a status panel showing:
- Connection status to daemon (connected/disconnected/error)
- Current tab being debugged (URL, title, debugger attached yes/no)
- Session statistics (commands processed, reconnect count)
- Troubleshooting section with copy-paste fix commands

---

## 站点适配器（零 LLM 成本）

### 列出可用适配器
```python
from agent_browser import list_adapters
adapters = await list_adapters()
```

### 执行适配器
```python
from agent_browser import run_adapter

# 百度搜索
results = await run_adapter("baidu", "search", query="AI coding", limit=5)

# Boss直聘搜索
results = await run_adapter("boss", "search", query="Python", city="101010100")
```

### AI 自动探索未知网站
```python
from agent_browser import create_session, explore, synthesize, cascade

sid = await create_session()
artifacts = await explore(sid, "https://example.com", goal="获取文章列表")
strategies = await cascade(sid, "https://example.com", endpoints=artifacts.endpoints)
adapter = synthesize("example", artifacts, command_name="articles")
```

---

## 错误处理与自主恢复

When an error occurs, follow this conversation pattern:

```
1. CLASSIFY the error (match against known patterns below)
2. ATTEMPT auto-fix silently (if fixable):
   - CDP not reachable → try launching browser / connecting
   - Element @eN not found → re-snapshot (up to 3x), find by text/selector
   - Missing dependency → run doctor.py auto_fix()
   - Timeout / slow page → wait longer, re-snapshot
3. If auto-fix fails after 3 attempts → PRESENT TO USER with context:
   "I'm stuck on [specific element/action]. Options:
    A) Try different approach
    B) Skip this step
    C) Show me what you see (screenshot)
    D) I'll handle it manually"
4. For HUMAN-ONLY blocks (login, captcha, ambiguous choice):
   STOP and say: "[What you see]. Please [action], then tell me when ready."
```

| 错误 | 原因 | 处理 | 自动修复? |
|------|------|------|---------|
| `Element @eN not found` | DOM 变化，引用过期 | 重新 snapshot 获取新 refs，按文本/选择器查找 | 是 (自动，最多3次重试) |
| `CDP not initialized` | 浏览器未就绪 | 等待 5-10 秒重试 | 是 |
| `Backend not initialized` | 未调用 create_session | 先创建会话 | 否 |
| `ConnectionError: CDP not reachable` | 浏览器未启动 | 启动 CloakBrowser 或连接现有实例 | 是 |
| `FirstSessionError: Setup needed` | 缺少依赖 | 运行 doctor.py，安装可修复项 | 部分 (API key 需手动) |
| `ConnectionError: Extension not connected` | 未安装/启用扩展 | 引导用户安装扩展 (一次性设置) | 否 |
| `ImportError: cloakbrowser` | 未安装 CloakBrowser | 降级到基础模式 (仅 layers 6-7) | 是 (自动降级) |
| Agent stuck (连续空结果) | 反爬检测/captcha | 截图 + 建议人工干预 | 否 |

**重试策略**: 同一操作失败 3 次 → 换选择器策略 → 仍失败 → 报告用户

---

## 扫码登录

```
1. create_session → 告知用户 VNC 地址
2. 等待 15s → 导航到登录页
3. 点击"扫码登录" → 告知用户扫码
4. 用户确认后继续
```

---

## 详细参考文档

Progressive disclosure -- read these only when you need depth:

- **ReAct workflow details**: See [references/react-workflow.md](references/react-workflow.md) -- exact Claude Code interaction format, element ref lifecycle, human-like timing values
- **Error recovery patterns**: See [references/error-recovery.md](references/error-recovery.md) -- full pattern matching table with code examples
- **Complete API reference**: See [references/api-reference.md](references/api-reference.md) -- all functions with signatures, examples, edge cases
- **Adapter/exploration guide**: See [references/adapter-guide.md](references/adapter-guide.md) -- site adapters, explore/synthesize pipeline
