---
name: agent-browser
description: >
  Anti-detection browser automation. Create sessions, navigate pages, click/fill elements, extract data.
  Supports local browser (CLI) and remote API mode. Use for web scraping, form filling, search, login, data collection.
  Trigger on: "帮我访问", "打开浏览器", "扫码登录", "自动化浏览", "网页采集", "浏览器操作", "帮我打开网站".
  Proactively use when user mentions browser automation, web scraping, or wants Claude to interact with websites.
---

# Agent Browser — 多模式浏览器自动化

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

## Quick Start（首次使用）

### 零配置启动（推荐）

首次使用时，Agent Browser 自动检测并修复缺失的依赖：

```python
import asyncio
from agent_browser import create_session, snapshot, delete_session, setup

# 可选：运行 setup() 检查环境（自动检测 + 修复）
result = await setup()
if not result["ready"]:
    print(f"需要配置: {result['report'].suggestion}")
    # CloakBrowser 会自动安装，CDP 端点会自动启动

# 正常使用 — First-Session Recovery 在后台处理一切
session_id = await create_session()
await open_page(session_id, "https://example.com")
snap = await snapshot(session_id)
print(snap["title"])
await delete_session(session_id)
```

### 手动完整配置

```python
from agent_browser import setup, DeployConfig

result = await setup(
    mode="local",           # local | docker-aio | k8s-aio
    browser_type="cloakbrowser",
    headless=False,
)
print(f"Ready: {result['ready']}")
print(f"Config: {result['config_path']}")
for issue in result["issues"]:
    print(f"  [{issue.severity}] {issue.message}")
```

### 配置文件位置

所有部署配置统一存储在 `~/.agent-browser/config.yaml`：

```yaml
deployment:
  mode: local            # local | docker-aio | docker-distributed | k8s-aio
browser:
  type: cloakbrowser     # cloakbrowser | chrome | playwright
  cdp_url: "http://127.0.0.1:19222"
api:
  port: 8000
stealth:
  enabled: true
  mode: full             # full | vanilla
```

**配置优先级**: 显式参数 > 环境变量 (AGENT_BROWSER_*) > config.yaml > 自动探测 > 默认值

---

## 模式 1：LLM ReAct（原子操作）

外部 LLM（Claude/GPT）通过 ReAct 循环控制每一步。

### Observe → Reason & Act → Check 循环

**1. Observe（观察）**
```python
import asyncio
from agent_browser import create_session, delete_session, open_page, snapshot, click, fill, scroll

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

**元素引用格式**: `@e0`, `@e1`, `@e2`...（通过 snapshot 获取）

**快照返回字段**:
```python
{
    "url": "当前页面 URL",
    "title": "页面标题",
    "elements": [{"ref": "@e0", "text": "...", "role": "a"}, ...]
}
```

---

## 模式 2：Agent 自主执行（browser-use）

内置 LLM Agent 自主完成整个任务，无需外部 ReAct 循环。

```python
from agent_browser import create_session, delete_session, run_task

sid = await create_session()
result = await run_task(
    sid,
    task="访问百度搜索 AI coding，提取前5条结果标题和链接",
    intelligence="agent",
    max_steps=10,
)
await delete_session(sid)

# result = {"status": "completed", "result": "...", "steps": 8, "chunks": 2}
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

**Agent 返回值**:
```python
{
    "status": "completed" | "failed" | "stuck",
    "result": "任务结果文本",
    "steps": 12,
    "chunks": 2,
    "error": "..."  # 仅失败时
}
```

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

### 桌面应用控制
```python
from agent_browser import list_desktop_apps, run_desktop_command
apps = await list_desktop_apps()
status = await run_desktop_command("cursor", "status")
```

---

## 错误处理

| 错误 | 原因 | 处理 |
|------|------|------|
| `Element @eN not found` | 元素引用过期（页面变化） | 重新 snapshot 获取新 refs |
| `CDP not initialized` | 浏览器未就绪 | 等待 5-10 秒重试 |
| `Backend not initialized` | 未调用 create_session | 先创建会话 |
| 任务空结果 | 反爬检测 | 引导用户 VNC 干预 |
| `explore() requires LocalCDPBackend` | API 模式不支持 explore | 使用 CLI 模式 |
| Agent stuck | 连续空/重复结果 | 手动干预或换策略 |

**重试策略**: 同一操作失败 3 次 → 换选择器策略 → 仍失败 → 报告用户

---

## 扫码登录

```
1. create_session → 告知用户 VNC 地址
2. 等待 15s → 导航到登录页
3. 点击"扫码登录" → 告知用户扫码
4. 用户确认后继续
```
