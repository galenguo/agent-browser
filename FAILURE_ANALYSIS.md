# Agent Browser 失败原因分析报告

**分析时间：** 2026-03-31 19:15  
**问题：** 测试操作失败，无法完成场景测试

---

## 失败时间线

### 1. 会话创建阶段（成功）
```
✅ CloakBrowser 启动成功
✅ CDP 端口 19222 监听
✅ Profile 创建成功
✅ 返回 session_id 和 cdp_url
```

**耗时：** 约 60 秒  
**状态：** 成功

### 2. Warmup 阶段（部分失败）
```
⚠️ 访问 https://www.baidu.com - 失败（viewport_size bug）
⚠️ 访问 https://www.163.com - 失败（viewport_size bug）
⚠️ 访问 https://www.zhipin.com - 失败（viewport_size bug）
✅ Warmup 标记为完成（非致命错误）
```

**问题：** Bug #4 导致 warmup 失败，但标记为"非致命"继续执行

### 3. 会话创建后（立即失败）
```
❌ CDP WebSocket 连接断开
❌ 重连尝试 1 - 成功但立即又断开
❌ 重连尝试 2 - 成功但立即又断开
❌ Agent focus target 分离
❌ 无法创建新标签页
❌ 浏览器连接拒绝（Connection refused）
❌ 3 次重连全部失败
```

---

## 根本原因分析

### 原因 1: 会话创建后浏览器立即关闭

**证据：**
1. 第 27 行：`CDP WebSocket message handler exited unexpectedly (connection closed)`
2. 第 47 行：`ConnectionRefusedError: [Errno 61] Connect call failed ('127.0.0.1', 19222)`
3. 端口 19222 无进程监听（lsof 检查为空）
4. 无残留 Chromium 进程（ps 检查为空）

**分析：**
- 会话创建成功后，Python 进程返回了 JSON 响应
- 但浏览器进程在返回后立即退出
- 导致 CDP WebSocket 连接断开
- 后续操作无法连接到浏览器

**可能原因：**
1. **Python 进程退出导致浏览器关闭**
   - CLI 命令执行完成后，Python 进程退出
   - 浏览器作为子进程被一起终止
   - 没有实现浏览器进程的持久化

2. **会话管理器设计问题**
   - 会话创建后没有保持浏览器进程运行
   - 缺少进程守护机制
   - 没有实现跨命令的会话复用

### 原因 2: CLI 架构设计缺陷

**问题：**
CLI 模式下，每个命令都是独立的 Python 进程：
```bash
# 命令 1: 创建会话（进程 A）
python -m src.cli.commands session create --name test

# 命令 2: 导航（进程 B）
python -m src.cli.commands navigate goto --session test --url xxx
```

**设计缺陷：**
1. 进程 A 创建浏览器后退出
2. 浏览器作为子进程被终止
3. 进程 B 启动时浏览器已不存在
4. 无法连接到 CDP 端口

**预期设计：**
- 浏览器应该作为独立进程运行
- 不应该依赖 Python 进程存活
- 需要进程守护或后台服务

### 原因 3: 缺少会话持久化机制

**当前实现：**
```python
# 会话创建后返回
{"status": "success", "data": {"session_id": "test", "cdp_url": "http://127.0.0.1:19222"}}
# Python 进程退出，浏览器被终止
```

**需要的实现：**
```python
# 1. 启动浏览器作为独立进程
# 2. 保存会话信息到文件（~/.agent-browser/sessions.json）
# 3. Python 进程退出，浏览器继续运行
# 4. 后续命令从文件读取会话信息连接
```

---

## 错误日志详细分析

### 第 27-30 行：首次断开和重连
```
WARNING  [BrowserSession] 🔌 CDP WebSocket message handler exited unexpectedly (connection closed)
WARNING  [BrowserSession] 🔄 WebSocket reconnection attempt 1/3...
INFO     [BrowserSession] [SessionManager] Cleared all owned data (targets, sessions, mappings)
INFO     [BrowserSession] 🔄 WebSocket reconnected after 0.1s (attempt 1)
```

**分析：** 重连成功，但立即又断开（第 31 行）

### 第 35-39 行：Agent focus 丢失
```
WARNING  [BrowserSession] [SessionManager] Agent focus target FF8632B3... detached!
WARNING  [BrowserSession] [SessionManager] No tabs remain! Creating new tab for agent...
WARNING  [BrowserSession] Cannot navigate - browser not connected
INFO     [BrowserSession] [SessionManager] Created new tab B77DFECE... for agent
INFO     [BrowserSession] [SessionManager] ✅ Agent focus recovered: B77DFECE...
```

**分析：**
- 浏览器标签页分离
- 尝试创建新标签页
- 提示"browser not connected"但仍然创建成功
- 这是浏览器即将崩溃的征兆

### 第 40-43 行：再次失败
```
WARNING  [BrowserSession] [SessionManager] Agent focus target B77DFECE... detached!
WARNING  [BrowserSession] [SessionManager] No tabs remain! Creating new tab for agent...
WARNING  [BrowserSession] Cannot navigate - browser not connected
ERROR    [BrowserSession] [SessionManager] ❌ Error during agent_focus recovery: RuntimeError: {'code': -32000, 'message': 'Failed to open a new tab'}
```

**分析：**
- 新创建的标签页又立即分离
- 尝试再次创建失败
- CDP 返回错误：无法打开新标签页
- 浏览器进程已经崩溃或退出

### 第 47-52 行：完全失败
```
WARNING  [BrowserSession] 🔄 Reconnection attempt 1 failed: ConnectionRefusedError: [Errno 61] Connect call failed ('127.0.0.1', 19222)
WARNING  [BrowserSession] 🔄 Reconnection attempt 2 failed: ConnectionRefusedError: [Errno 61] Connect call failed ('127.0.0.1', 19222)
WARNING  [BrowserSession] 🔄 Reconnection attempt 3 failed: ConnectionRefusedError: [Errno 61] Connect call failed ('127.0.0.1', 19222)
ERROR    [BrowserSession] 🔄 All 3 reconnection attempts failed
```

**分析：**
- 端口 19222 拒绝连接
- 浏览器进程已完全退出
- 无法恢复

---

## 验证测试

### 测试 1: 检查端口占用
```bash
lsof -i :19222
```
**结果：** 无输出（端口未被占用）  
**结论：** 浏览器进程已退出

### 测试 2: 检查浏览器进程
```bash
ps aux | grep -E "chromium|CloakBrowser"
```
**结果：** 无输出（无残留进程）  
**结论：** 浏览器进程已完全清理

### 测试 3: 检查 Profile 目录
```bash
ls -la /tmp/agent_browser_profiles/test-scenario1-full
```
**结果：** 目录存在，包含 Default 等子目录  
**结论：** Profile 创建成功，但浏览器已退出

---

## 结论

### 核心问题
**CLI 架构设计缺陷：浏览器进程依赖 Python 进程存活**

### 失败流程
1. `session create` 命令启动 Python 进程 A
2. 进程 A 创建浏览器作为子进程
3. 进程 A 返回 JSON 响应后退出
4. 浏览器子进程被操作系统终止
5. 后续命令无法连接到已退出的浏览器

### 为什么会话创建"成功"
- 会话创建时浏览器确实启动了
- CDP 端口确实监听了
- 返回的 JSON 响应是正确的
- 但 Python 进程退出后，浏览器也退出了

---

## 解决方案

### 方案 1: 实现浏览器进程守护（推荐）

**实现：**
1. 使用 `subprocess.Popen()` 启动浏览器，设置 `start_new_session=True`
2. 浏览器进程独立于 Python 进程
3. 保存进程 PID 到文件
4. 后续命令通过 PID 检查浏览器是否存活

**代码示例：**
```python
import subprocess
import os

# 启动浏览器作为独立进程
process = subprocess.Popen(
    [browser_path, *args],
    start_new_session=True,  # 关键：创建新会话
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL
)

# 保存 PID
with open(f"/tmp/agent_browser_{session_id}.pid", "w") as f:
    f.write(str(process.pid))
```

### 方案 2: 使用后台服务模式

**实现：**
1. 启动一个长期运行的 Python 服务进程
2. CLI 命令通过 HTTP/Socket 与服务通信
3. 服务管理所有浏览器进程
4. 类似于 API 模式，但通过 CLI 调用

### 方案 3: 使用 API 模式替代 CLI

**实现：**
1. 启动 API 服务：`uvicorn src.api:app --port 8000`
2. CLI 命令转换为 API 调用
3. API 服务管理浏览器生命周期
4. 这是最稳定的方案

---

## 立即行动

### 优先级 1: 验证问题
1. 手动启动 API 服务测试
2. 确认 API 模式是否正常工作
3. 验证问题确实是 CLI 架构问题

### 优先级 2: 修复 CLI 模式
1. 实现方案 1（浏览器进程守护）
2. 测试会话持久化
3. 验证跨命令会话复用

### 优先级 3: 完成测试
1. 使用 API 模式完成场景 3 测试
2. 修复 CLI 后完成场景 1-2 测试
3. 完成剩余场景测试

---

**报告生成时间：** 2026-03-31 19:20  
**结论：** CLI 架构设计缺陷导致浏览器进程随 Python 进程退出而终止
