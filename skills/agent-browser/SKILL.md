---
name: agent-browser
description: >
  Control a remote anti-detection browser via Docker for web automation tasks.
  Use bash tool with curl to call FastAPI endpoints (http://localhost:8000).
  Use this skill whenever the user wants to automate browser interactions, visit websites,
  scrape data, perform QR code login, fill forms, click elements, or do any multi-step
  web task in a remote browser. Also trigger on Chinese phrases: "帮我访问", "打开浏览器",
  "扫码登录", "自动化浏览", "网页采集", "浏览器操作", "帮我打开网站", "远程浏览器".
  Proactively use this skill whenever the user mentions browser automation, web scraping,
  remote browser, or wants Claude to interact with any website on their behalf — even if
  they don't explicitly say "agent browser".
---

# Agent Browser 使用指南

通过 **FastAPI REST API** 控制远程 Docker 浏览器，执行网页自动化任务。

## API 端点

使用 `bash` 工具通过 curl 调用 FastAPI（默认 `http://localhost:8000`）：

| 端点 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 检查 API 状态 |
| `/sessions/create` | POST | 创建会话，body: `{"user_id": "..."}` |
| `/sessions/{id}/task` | POST | 提交任务，body: `{"task": "...", "model": "glm-5-turbo", "max_steps": 6}` |
| `/sessions/{id}/tasks/{task_id}` | GET | 查询任务状态 |
| `/sessions/{id}` | DELETE | 删除会话 |
| `/sessions` | GET | 列出所有会话 |

---

## 核心约束：阻塞调用

任务提交后需要轮询 `/sessions/{id}/tasks/{task_id}` 查询状态，直到 `status` 变为 `completed` 或 `failed`。**进度汇报只能发生在两次 API 调用之间。**

解决方案：**分块执行循环**。利用 session 状态持久性（浏览器 URL/DOM/Cookie 在多次调用间保留），每次调用设置较短 timeout，调用结束后汇报进度、检测卡住状态，再决定继续/干预/结束。

---

## 标准工作流

### 第一步：创建会话

```bash
curl -X POST http://localhost:8000/sessions/create \
  -H "Content-Type: application/json" \
  -d '{"user_id": "任务名称"}'
```

返回 `session_id` 和 `browser_node`（可能为 null）。

**立即告知用户远程桌面地址：**
- 如果 `browser_node.novnc_url` 存在：`远程桌面：{novnc_url}/vnc.html`
- 如果为 null：`远程桌面：http://www.aiecho.site:6080/vnc.html`（默认地址）

**等待 10~15 秒**再执行任务，让 Docker 容器完全启动。

### 第二步：提交任务并轮询状态

```bash
# 提交任务
curl -X POST http://localhost:8000/sessions/{session_id}/task \
  -H "Content-Type: application/json" \
  -d '{"task": "任务描述", "model": "glm-5-turbo", "max_steps": 6}'
# 返回 task_id

# 轮询任务状态（每5秒查询一次）
curl http://localhost:8000/sessions/{session_id}/tasks/{task_id}
```

返回字段：
- `status`: "running" | "completed" | "failed"
- `current_step`: 当前执行到第几步
- `last_step_at`: 最后一步的时间戳
- `result`: 任务结果（completed 时）
- `error`: 错误信息（failed 时）

### 第三步：分块执行循环

见下方"分块执行循环"章节。

### 第四步：关闭会话

```bash
curl -X DELETE http://localhost:8000/sessions/{session_id}
```

任务完成后务必调用，否则容器资源持续占用。

---

## 分块执行循环

### 循环逻辑

```
初始化：chunk_num=1, last_result="", stuck_count=0

LOOP:
  1. 构建任务提示词（见"续接提示词模板"）
  2. result = browser_run_task(session_id, task_prompt, max_steps=6, timeout=75)
  3. 判断结果：
     → 检测到 TASK_COMPLETE  → 汇报最终结果 → 关闭会话 → 结束
     → is_stuck(result)      → stuck_count++
                                stuck_count == 1 → 告知用户"进展缓慢，正在重试..."，继续
                                stuck_count >= 2 → 进入用户干预流程
     → 正常进展              → 汇报进度，last_result=result，chunk_num++，继续
```

### 卡住检测规则

满足以下任一条件即判定为卡住，累计 `stuck_count`，≥2 进入用户干预流程：

| 信号 | 条件 |
|------|------|
| 超时未完成（未启动）| `status == "running"` 且 `current_step == 0` |
| 步骤停滞 | `status == "running"` 且 `current_step > 0` |
| 失败超时 | `status == "failed"` 且 error 含 "timeout" |
| 空结果 | `status == "completed"` 且 result 为空或 `[]` |
| 循环 | result 内容与 last_result 完全相同 |

> `status=running` 表示本次 chunk 在 timeout 内未完成，视为卡住；`current_step` 字段可用于诊断具体卡在哪一步。

### 续接提示词模板

**第一个 chunk（chunk_num == 1）：**
```
{original_task}

当所有步骤完成后，最后一行输出：TASK_COMPLETE: {结果摘要}
```

**后续 chunk（chunk_num > 1）：**
```
任务：{original_task}

当前浏览器状态（上一步已完成）：{last_result 的1~2句摘要}

请从当前状态继续，不要重复已完成的步骤。
当所有步骤完成后，最后一行输出：TASK_COMPLETE: {结果摘要}
```

### 完成信号检测

检测 result 中是否包含 `TASK_COMPLETE:` 字符串。检测到后提取其后的摘要作为最终结果汇报给用户。

---

## 用户干预流程

当 stuck_count >= 2 时，停止循环，向用户发送（根据 current_step 选择合适描述）：

```
任务卡住了，请打开远程桌面查看当前状态：
👉 {novnc_url}/vnc.html

当前进度：第 {current_step} 步超时未完成（current_step==0 则为初始化卡住）

请告诉我：
1. 页面上显示什么？
2. 是否需要手动操作（验证码、登录等）？
3. 完成后告诉我，我会继续。
```

收到用户回复后，将用户描述的状态注入续接提示词，重置 stuck_count=0，继续循环。

---

## 进度汇报规范

每个 chunk 完成后主动告知用户：
- 当前处于哪个阶段（从 result 内容推断，如"已打开登录页"、"正在搜索"）
- 是否正常进展 / 超时重试 / 空结果
- 复杂任务每次提醒远程桌面链接

示例：
```
✅ 第1轮完成：已打开 Boss直聘 并进入搜索页
   远程桌面：{novnc_url}/vnc.html
   继续执行第2轮...
```

---

## 扫码登录场景

扫码登录是干预流程的典型场景，按以下步骤处理：

1. `browser_create_session` → 告知用户 `{novnc_url}/vnc.html`
2. 等待 15 秒
3. 执行导航到登录页（max_steps=5, timeout=30）
4. 执行点击"扫码登录"（max_steps=5, timeout=30）
5. **主动告知用户**：
   ```
   请在远程桌面扫码：{novnc_url}/vnc.html
   扫码完成后告诉我，我会继续后续操作。
   ```
6. 等用户确认后继续

---

## 常见问题处理

| 现象 | 原因 | 处理方式 |
|------|------|---------|
| `CDP client not initialized` | 容器还没完全启动 | 等 5~10 秒重试 |
| 任务返回空结果 `[]` | 目标页面有反爬检测 | 触发卡住检测，引导用户 VNC 干预 |
| 任务超时 | timeout 太短或页面加载慢 | 自动重试，stuck_count 累计后干预 |
| 连续 3 次失败 | 会话异常 | 删除会话重建 |
| result 与上次相同 | agent 在循环 | 触发卡住检测，修改提示词重试 |
| `status=running` 超时返回（current_step==0）| 初始化卡住（浏览器连接或第1步超时）| 触发卡住检测，stuck_count++ |
| `status=running` 超时返回（current_step>0）| 第N步停滞（LLM/DOM超时）| 触发卡住检测，stuck_count++，干预时告知第N步 |
