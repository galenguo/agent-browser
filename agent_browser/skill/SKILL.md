---
name: agent-browser
argument-hint: <task description>
description: >
  Anti-detection browser automation. Create sessions, navigate pages,
  click/fill elements, extract data, run Agent tasks.
  Trigger on: "帮我访问", "打开浏览器", "扫码登录", "自动化浏览", "网页采集",
    "浏览器操作", "帮我打开网站", "open website", "search for", "browse",
    "scrape", "fill form", "visit url", "help me browse", "automate browser".
  Proactively use when user mentions interacting with websites, collecting data, or
  automating browser tasks.
---

# Agent Browser -- 浏览器自动化

> **ARGUMENTS Handling**: ARGUMENTS is a natural language task description. If it contains surrounding double quotes (`"..."`), strip them first. Treat the entire ARGUMENTS as a single task -- never split on quotes or special characters inside.

```python
from agent_browser.skill.scripts.browser_cli import SkillBrowser
```

---

## 执行策略（必读）

**在开始任务前，必须先读取 `config.yaml` 的 `intelligence` 字段，决定执行模式：**

```python
sb = SkillBrowser()
# sb._intelligence 已自动从 config.yaml 加载，值为 "llm" 或 "agent"
```

### LLM 模式 (`intelligence: "llm"`)
- **外部 ReAct 循环**：你（LLM）逐步控制每个操作
- 适合：需要人工介入（登录/验证码）、需要精确控制每步、复杂筛选逻辑
- 执行方式：`snapshot() → 分析 → click()/fill() → snapshot() → 循环`

### Agent 模式 (`intelligence: "agent"`)
- **服务端自主执行**：一次提交任务，服务端 Agent 自动完成
- 适合：简单数据采集、无需人工干预、明确的单一目标
- 执行方式：`run_task(sid, "任务描述", max_steps=10)`

**重要**：根据 `sb._intelligence` 的值选择对应的执行方式，不要混用。

---

## 首次使用

### 自动配置加载

`SkillBrowser()` 初始化时自动按以下顺序加载配置：

1. 构造参数（`api_url`, `api_key`）
2. `skill/config.yaml` 文件
3. 自动检测 `localhost:8000/health`
4. 默认值 `http://localhost:8000`

```python
from agent_browser.skill.scripts.browser_cli import SkillBrowser

sb = SkillBrowser()  # 自动读取 config.yaml → 自动检测 → 默认值
```

### 检查服务是否可用

```python
report = await sb.diagnose()
if not report["ready"]:
    # report["errors"] 包含原因和解决建议
    print(report["errors"])
```

### 配置服务地址（如果默认不生效）

编辑 `agent_browser/skill/config.yaml`：

```yaml
service:
  url: "http://your-api-server:8000"
  api_key: "your-api-key"
  timeout: 120
intelligence: "llm"    # "llm" (ReAct 逐步) 或 "agent" (自治)
```

或在代码中直接指定：

```python
sb = SkillBrowser(api_url="http://your-server:8000", api_key="your-key")
```

---

## 交互模式

SkillBrowser 通过 config.yaml 的 `intelligence` 字段决定交互模式：

### LLM 模式 (intelligence: "llm")

LLM 通过 ReAct 循环逐步控制：Observe → Reason → Act → Check。
适合：简单操作、需要确认每步、需要人工介入（登录/验证码）。

```python
# config.yaml: intelligence: "llm"
snap = await sb.snapshot(sid)   # Observe — 观察页面
# LLM 分析 elements，决定下一步
await sb.click(sid, "@e3")      # Act — 执行操作
snap2 = await sb.snapshot(sid)  # Check — 验证结果
```

### Agent 模式 (intelligence: "agent")

一次提交任务，服务端 Agent 自主执行完成。
适合：复杂多步任务、数据采集、无需人工干预。

```python
# config.yaml: intelligence: "agent"
result = await sb.run_task(sid, "访问百度搜索 AI coding，提取前5条结果")
# result["status"] == "completed" → result["result"] 包含结果
```

### 选择指南

- 需要人工介入（登录、验证码）→ `llm`
- 需要精确控制每步 → `llm`
- 复杂多步自治任务 → `agent`
- 不确定 → 先用 `llm` 观察再决定

---

## 可用操作

### 会话管理

```python
sb = SkillBrowser()
sid = await sb.create_session()
# ... do work ...
await sb.delete_session(sid)
```

### 导航

```python
await sb.open_page(sid, "https://example.com")
await sb.go_back(sid)
```

### 观察页面（ReAct 核心）

```python
snap = await sb.snapshot(sid)
# 返回: {url, title, elements: [{ref: "@e0", text: "...", role: "a"}, ...]}
```

### 交互操作

```python
await sb.click(sid, "@e3")              # 点击元素
await sb.click(sid, x=150.5, y=200.0)   # 坐标点击
await sb.fill(sid, "@e1", "关键词")      # 填充输入
await sb.scroll(sid, "down", 500)        # 滚动页面
await sb.hover(sid, "@e2")              # 悬停元素
await sb.select_option(sid, "@e4", "val")  # 选择下拉
await sb.press_key(sid, "Enter")        # 按键
await sb.wait_for_selector(sid, ".result", timeout=10000)  # 等待元素
```

### 执行 JavaScript

```python
result = await sb.evaluate(sid, "document.title")
```

### Agent 自主执行

```python
result = await sb.run_task(sid, "访问百度搜索 AI coding，提取前5条结果", max_steps=10)
# result = {"status": "completed"|"failed"|"stuck"|"timeout", "result": "...", "steps": 8}
```

### 诊断

```python
report = await sb.diagnose()
# report["ready"] == True → 服务就绪
```

### 操作速查表

| 操作 | 方法 | 说明 |
|------|------|------|
| 创建会话 | `create_session(user_id?)` | 返回 session_id |
| 删除会话 | `delete_session(sid)` | 释放资源 |
| 打开页面 | `open_page(sid, url)` | 导航到 URL |
| 页面快照 | `snapshot(sid)` | 返回 `{url, title, elements}` |
| 点击元素 | `click(sid, ref)` | 点击 @eN 元素 |
| 坐标点击 | `click(sid, x=x, y=y)` | 按坐标点击 |
| 填充输入 | `fill(sid, ref, text)` | 在 @eN 输入框填文本 |
| 滚动页面 | `scroll(sid, dir, amt)` | dir="down"/"up"，默认 500px |
| 悬停元素 | `hover(sid, ref)` | 悬停在 @eN 上 |
| 选择下拉 | `select_option(sid, ref, val)` | 选择下拉选项 |
| 按键 | `press_key(sid, key)` | Enter, Tab, Escape 等 |
| 等待元素 | `wait_for_selector(sid, sel)` | 等待选择器出现 |
| 后退 | `go_back(sid)` | 后退到上一页 |
| 执行 JS | `evaluate(sid, expr)` | 执行 JavaScript |
| Agent 任务 | `run_task(sid, task, ...)` | 自主完成任务 |
| 获取会话信息 | `get_session_info(sid)` | 获取 noVNC URL 等完整信息 |

**元素引用格式**: `@e0`, `@e1`, `@e2`...（通过 snapshot 获取）

---

## ReAct 工作流

外部 LLM 通过 Observe -> Reason -> Act -> Check 循环控制每一步。

```
+----------+   +----------+   +----------+   +----------+
| Observe  |-> | Reason   |-> | Act      |-> | Check    |
|          |   |          |   |          |   |          |
| snapshot |   | Analyze  |   | Execute  |   | Verify   |
| elements |   | elements |   | action   |   | result   |
| URL/title|   | Plan next|   | (click/  |   | Loop or  |
|          |   | step     |   | fill/    |   | done     |
+----------+   +----------+   +----------+   +----------+
     ^                                              |
     +-------- retry on failure <---------------+
                    (max 3 retries per action)
```

### 1. Observe（观察）

```python
snap = await sb.snapshot(sid)
# 分析 snap["elements"] 和 snap["url"]
```

### 2. Reason & Act（推理并行动）

```python
for el in snap["elements"]:
    if "搜索" in el.get("text", ""):
        await sb.fill(sid, el["ref"], "关键词")
    if "提交" in el.get("text", ""):
        await sb.click(sid, el["ref"])
```

### 3. Check（验证）

```python
snap2 = await sb.snapshot(sid)
# 检查 URL 变化、目标元素、数据是否提取到
```

### 标准流程模板

**简单导航/提取**: `create_session -> open_page -> snapshot -> [分析] -> delete_session`

**搜索任务**: `create_session -> open_page(搜索页) -> snapshot -> fill(搜索词) -> click(搜索按钮) -> snapshot -> 提取结果 -> delete_session`

**扫码登录**: `create_session -> open_page(登录页) -> click(扫码登录) -> 告知用户扫码 -> 用户确认后继续`

---

## Agent 自主执行模式

内置 LLM Agent 自主完成整个任务，无需外部 ReAct 循环。

```python
sid = await sb.create_session()
result = await sb.run_task(
    sid,
    task="访问百度搜索 AI coding，提取前5条结果标题和链接",
    max_steps=10,
)
print(result["result"])
await sb.delete_session(sid)
```

**参数**: `task`（任务描述）、`max_steps`（最大步数，默认 6）、`total_timeout`（总超时秒数，默认 300）

---

## 错误处理与自主恢复

```
1. CLASSIFY the error
2. ATTEMPT auto-fix (if fixable):
   - Element @eN not found -> re-snapshot (up to 3x), find by text/selector
   - Session not found -> re-create session
   - Timeout / slow page -> wait longer, re-snapshot
3. Auto-fix fails after 3 attempts -> PRESENT TO USER
4. HUMAN-ONLY blocks (login, captcha) -> STOP and ask user
```

| 错误 | 处理 | 自动修复? |
|------|------|---------|
| Service not reachable | 用户检查服务是否运行 | 否 |
| Element @eN not found | 重新 snapshot 获取新 refs | 是（最多 3 次）|
| Session not found | 重新创建会话 | 部分 |
| API error 409 | 稍后重试 | 是 |
| API error 403 | 用户检查认证配置 | 否 |
| Task timeout | 增加 timeout 或简化任务 | 否 |
| Agent stuck | 建议人工干预 | 否 |

**重试策略**: 同一操作失败 3 次 -> 换策略 -> 仍失败 -> 报告用户

---

## Human Handoff Points

Stop and ask the user when:
- **Login required** -- Call `sb.get_session_info(sid)` to get the `novnc_url`, then tell user to open it for manual login. "I see a login page. Open the noVNC URL to log in, then tell me when ready."
- **Captcha detected** -- "There's a captcha. Please solve it, then tell me."
- **Unexpected modal/dialog** -- "Something popped up. What should I do?"
- **3 consecutive failures** -- "I'm stuck on [specific element]. Options: try different approach / skip / show you what I see."

---

## 详细参考文档

Progressive disclosure -- read these only when you need depth:

- **ReAct workflow details**: See [references/react-workflow.md](references/react-workflow.md)
- **Error recovery patterns**: See [references/error-recovery.md](references/error-recovery.md)
- **Complete API reference**: See [references/api-reference.md](references/api-reference.md)
- **Adapter/exploration guide**: See [references/adapter-guide.md](references/adapter-guide.md)
