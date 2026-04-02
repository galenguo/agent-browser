---
name: agent-browser
description: >
  Anti-detection browser automation. Create sessions, navigate pages, click/fill elements, extract data.
  Supports local browser (CLI) and remote API mode. Use for web scraping, form filling, search, login, data collection.
  Trigger on: "帮我访问", "打开浏览器", "扫码登录", "自动化浏览", "网页采集", "浏览器操作", "帮我打开网站".
  Proactively use when user mentions browser automation, web scraping, or wants Claude to interact with websites.
---

# Agent Browser — ReAct 模式

## 工作模式

```
本地模式（默认）: Agent → Python API → BrowserController → Chrome CDP
远程模式:         Agent → curl → FastAPI → BrowserController → Docker Chrome
```

检测：`curl -s http://localhost:8000/health` 成功 → 远程模式，否则本地模式。

---

## ReAct 循环

每个任务按 **Observe → Reason & Act → Check** 循环执行：

### 1. Observe（观察）

获取当前页面状态：

**本地模式（Python）：**
```python
import asyncio
from agent_browser import create_session, delete_session, open_page, snapshot, click, fill, scroll

# 创建会话
session_id = await create_session()  # 默认 http://127.0.0.1:19222
# 或指定 CDP: await create_session("http://host:port")

# 打开页面
await open_page(session_id, "https://example.com")

# 获取快照 — 返回 {url, title, elements: [{ref, text, role}...]}
snap = await snapshot(session_id)
```

**远程模式（curl）：**
```bash
# 创建会话
SESSION=$(curl -s -X POST http://localhost:8000/sessions/create -d '{"user_id":"task"}')
SID=$(echo $SESSION | jq -r '.session_id')

# 打开页面 + 获取快照（通过 agent task）
curl -s -X POST http://localhost:8000/sessions/$SID/task \
  -d '{"task":"打开 https://example.com 并返回页面元素列表","max_steps":5}'
```

### 2. Reason & Act（推理并行动）

分析快照中的元素，选择操作：

```python
# 分析 snap["elements"] 找到目标元素
for el in snap["elements"]:
    if "搜索" in el.get("text", ""):
        await fill(session_id, el["ref"], "关键词")
    if "提交" in el.get("text", ""):
        await click(session_id, el["ref"])
```

**元素引用格式**: `@e0`, `@e1`, `@e2`...（通过 snapshot 获取）

**可用操作**:
| 操作 | 函数 | 说明 |
|------|------|------|
| 打开页面 | `open_page(sid, url)` | 导航到 URL |
| 获取快照 | `snapshot(sid)` | 返回页面状态 + 元素列表 |
| 点击元素 | `click(sid, ref)` | 点击 @eN 元素 |
| 填充输入 | `fill(sid, ref, text)` | 在 @eN 输入框填入文本 |
| 滚动页面 | `scroll(sid, dir, amt)` | dir="down"/"up"，默认滚动 500px |
| 关闭会话 | `delete_session(sid)` | 释放浏览器资源 |

**快照返回字段**:
```python
{
    "url": "当前页面 URL",
    "title": "页面标题",
    "page_text": "页面可见文本前 80 字符",
    "scroll_percent": 0,   # 滚动位置百分比 (0-100)
    "elements": [{"ref": "@e0", "text": "...", "role": "a", "tag": "a"}, ...]
}
```

**提示**：`scroll_percent` 接近 100 时说明已到底部。
```

### 3. Check（验证结果）

```python
# 操作后重新获取快照验证
snap2 = await snapshot(session_id)
# 检查 URL 是否变化、是否出现目标元素、数据是否提取到
```

---

## 标准流程

### 简单导航/提取

```
1. create_session → open_page → snapshot → [分析元素] → delete_session
```

### 搜索任务

```
1. create_session → open_page(搜索页) → snapshot
2. 找到搜索框 → fill(搜索词)
3. snapshot → 找到搜索按钮 → click
4. 等待加载 → snapshot → 提取结果
5. delete_session
```

### 多步复合任务

```
1. create_session → open_page → snapshot
2. 循环 { 观察 → 分析 → 操作 → 验证 } 直到目标达成
3. 汇总结果 → delete_session
```

---

## 远程模式分块执行

远程 API 使用 agent task，需要轮询：

```bash
# 提交任务
TASK=$(curl -s -X POST http://localhost:8000/sessions/$SID/task \
  -d '{"task":"任务描述","model":"glm-5-turbo","max_steps":6}')
TID=$(echo $TASK | jq -r '.task_id')

# 轮询状态
while true; do
  STATUS=$(curl -s http://localhost:8000/sessions/$SID/tasks/$TID)
  STATE=$(echo $STATUS | jq -r '.status')
  [ "$STATE" = "completed" ] || [ "$STATE" = "failed" ] && break
  sleep 5
done
```

### 分块循环

```
chunk=1, stuck=0
LOOP:
  task_result = run_task(session, prompt, max_steps=6)
  if result contains TASK_COMPLETE → done
  if result empty or same as last → stuck++
  if stuck >= 2 → ask user for intervention
  else → report progress, continue
```

### 续接提示词

**首轮**: `{任务描述}\n完成后输出 TASK_COMPLETE: {结果摘要}`
**续轮**: `任务：{原始}\n已完成：{上次结果摘要}\n请继续。完成后输出 TASK_COMPLETE: {结果摘要}`

---

## 错误处理

| 错误 | 原因 | 处理 |
|------|------|------|
| `Element @eN not found` | 元素引用过期（页面变化） | 重新 snapshot 获取新 refs |
| `CDP not initialized` | 浏览器未就绪 | 等待 5-10 秒重试 |
| 任务空结果 | 反爬检测 | 引导用户 VNC 干预 |
| 连续失败 | 会话异常 | 删除重建 |

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

## 使用示例

### 百度搜索并提取结果
```python
sid = await create_session()
await open_page(sid, "https://www.baidu.com")
snap = await snapshot(sid)

# 找搜索框
search_ref = next(e["ref"] for e in snap["elements"] if e["role"] == "input")
await fill(sid, search_ref, "AI coding")

# 找搜索按钮并点击
snap2 = await snapshot(sid)
btn_ref = next(e["ref"] for e in snap2["elements"] if "百度一下" in e.get("text",""))
await click(sid, btn_ref)

# 提取结果
import asyncio; await asyncio.sleep(3)
snap3 = await snapshot(sid)
results = [e["text"] for e in snap3["elements"] if e["role"] == "a" and e["text"]]
await delete_session(sid)
```

### 远程模式 Boss 直聘搜索
```bash
# 创建会话
SID=$(curl -s -X POST http://localhost:8000/sessions/create -d '{"user_id":"zhipin"}' | jq -r '.session_id')

# 提交搜索任务
curl -s -X POST http://localhost:8000/sessions/$SID/task \
  -d '{"task":"访问 Boss直聘 搜索 Python 工程师，提取前10条职位信息","model":"glm-5-turbo","max_steps":10}'

# 清理
curl -s -X DELETE http://localhost:8000/sessions/$SID
```
