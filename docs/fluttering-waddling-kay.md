# Agent Browser Skill 测试规划

## 背景

agent-browser 是一个反检测浏览器自动化平台的 OpenClaw skill，通过 FastAPI REST API 控制远程 Docker 浏览器。当前需要整理和回顾已有的测试规划。

## 已完成的测试（TEST_FIX_SUMMARY.md）

### ✅ 通过的测试用例

1. **test_zhipin_login_flow** (42.5秒)
   - 创建会话
   - 打开 Boss直聘
   - 获取快照并验证元素引用
   - 查找并点击登录按钮
   - 验证页面变化

2. **test_zhipin_search_jobs** (40.6秒)
   - 打开 Boss直聘
   - 查找搜索输入框
   - 填充搜索关键词
   - 点击搜索按钮

3. **test_zhipin_homepage_load** (5.4秒)
   - 基本页面加载测试

4. **test_xiaohongshu_homepage** (6.5秒)
   - 小红书页面加载测试

5. **test_session_isolation** (12秒)
   - 多会话隔离验证

6. **skill 模块导入测试**
   - 所有函数签名验证通过

### 已修复的问题

**问题 1：元素索引不匹配** ✅
- 原因：`snapshot()` 和 `click()`/`fill()` 元素索引不一致
- 修复：存储 `ElementHandle` 到 session，直接使用句柄

**问题 2：页面加载超时** ✅
- 原因：`wait_until="networkidle"` 对某些网站永远不满足
- 修复：改用 `wait_until="domcontentloaded"`

## Skill Evals 测试用例（evals.json）

### Eval 1: 百度搜索测试
**提示词：** "帮我用 agent browser 打开百度，搜索「Claude Code」，截图告诉我搜索结果的前3条标题是什么"

**预期行为：**
- 创建 Docker 会话
- 告知用户远程桌面地址（含 `/vnc.html`）
- 等待启动后访问百度
- 执行搜索
- 返回前3条结果标题
- 关闭会话

### Eval 2: Boss直聘扫码登录
**提示词：** "用 docker 浏览器帮我访问 Boss直聘，打开扫码登录页面，我要扫码登录"

**预期行为：**
- 创建 Docker 会话
- 立即告知用户 `{novnc_url}/vnc.html` 地址
- 等待启动（10-15秒）
- 导航到 Boss直聘登录页
- 点击扫码登录
- 主动提示用户去远程桌面扫码
- 等待用户确认

### Eval 3: 会话状态查询
**提示词：** "帮我检查一下 agent browser 现在有几个活跃的浏览器会话"

**预期行为：**
- 调用 `GET /sessions` 端点
- 返回当前活跃会话数量和状态

## 核心功能验证清单

### ✅ 已验证功能
- 浏览器启动和 CDP 连接
- 会话创建和管理
- 页面导航（open_page）
- 快照获取（snapshot）
- 元素引用生成（@e0, @e1...）
- 元素点击（click）
- 表单填充（fill）
- 多会话隔离
- Boss直聘网站访问
- 小红书网站访问

### ⏳ 待测试功能
- Mode 2: 远程 CDP 连接
- Mode 3: API Gateway + WebSocket
- 反检测功能验证
- 长时间会话稳定性

## Skill 工作流核心约束

### 分块执行循环（Chunked Execution Loop）

**问题：** 任务提交后需要轮询状态，阻塞期间无法汇报进度

**解决方案：** 利用 session 状态持久性，将长任务拆分为多个短 chunk

**循环逻辑：**
```
初始化：chunk_num=1, last_result="", stuck_count=0

LOOP:
  1. 构建任务提示词
  2. result = browser_run_task(session_id, task_prompt, max_steps=6, timeout=75)
  3. 判断结果：
     → 检测到 TASK_COMPLETE  → 汇报最终结果 → 关闭会话 → 结束
     → is_stuck(result)      → stuck_count++
                                stuck_count == 1 → 告知"进展缓慢，正在重试..."
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

### 用户干预流程

当 `stuck_count >= 2` 时，停止循环，向用户发送：

```
任务卡住了，请打开远程桌面查看当前状态：
👉 {novnc_url}/vnc.html

当前进度：第 {current_step} 步超时未完成

请告诉我：
1. 页面上显示什么？
2. 是否需要手动操作（验证码、登录等）？
3. 完成后告诉我，我会继续。
```

收到用户回复后，将用户描述的状态注入续接提示词，重置 `stuck_count=0`，继续循环。

## 关键测试场景

### 场景 1: 扫码登录（典型干预场景）

**步骤：**
1. 创建会话 → 告知用户 `{novnc_url}/vnc.html`
2. 等待 15 秒
3. 导航到登录页（max_steps=5, timeout=30）
4. 点击"扫码登录"（max_steps=5, timeout=30）
5. 主动告知用户：
   ```
   请在远程桌面扫码：{novnc_url}/vnc.html
   扫码完成后告诉我，我会继续后续操作。
   ```
6. 等用户确认后继续

**测试要点：**
- 远程桌面 URL 必须包含 `/vnc.html` 后缀
- 等待时间充足（10-15秒）
- 主动提示用户而非等待超时

### 场景 2: 搜索任务（多步骤协调）

**步骤：**
1. 打开目标网站
2. 定位搜索框
3. 填充关键词
4. 点击搜索按钮
5. 等待结果加载
6. 提取结果数据

**测试要点：**
- 元素引用（@e0, @e1）准确性
- 页面状态在多次 API 调用间保持
- 结果提取完整性

### 场景 3: 会话隔离

**测试要点：**
- 多个会话独立运行
- Cookie/localStorage 不互相污染
- 浏览器指纹独立

## 常见问题处理

| 现象 | 原因 | 处理方式 |
|------|------|---------|
| `CDP client not initialized` | 容器还没完全启动 | 等 5~10 秒重试 |
| 任务返回空结果 `[]` | 目标页面有反爬检测 | 触发卡住检测，引导用户 VNC 干预 |
| 任务超时 | timeout 太短或页面加载慢 | 自动重试，stuck_count 累计后干预 |
| 连续 3 次失败 | 会话异常 | 删除会话重建 |
| result 与上次相同 | agent 在循环 | 触发卡住检测，修改提示词重试 |

## 下一步测试计划

### 优先级 P0（必须完成）

1. **运行 Skill Evals**
   ```bash
   # 使用 skill-creator 运行 evals
   cd skills/agent-browser
   # 执行 evals.json 中的 3 个测试用例
   ```

2. **验证分块执行循环**
   - 测试 stuck_count 累计逻辑
   - 测试用户干预流程
   - 测试 TASK_COMPLETE 检测

3. **验证关键约束**
   - noVNC URL 必须包含 `/vnc.html`
   - 容器启动等待 10-15 秒
   - 进度汇报在 API 调用之间

### 优先级 P1（重要）

1. **Mode 2 测试：远程 CDP 连接**
   ```bash
   docker run -p 19222:19222 agent-browser-chromium
   pytest tests/test_mode2_remote_cdp.py
   ```

2. **Mode 3 测试：API Gateway + WebSocket**
   ```bash
   python src/api_gateway.py
   pytest tests/test_mode3_api_gateway.py
   ```

3. **反检测验证**
   ```bash
   pytest tests/test_anti_detection.py
   ```

### 优先级 P2（可选）

1. **长时间会话稳定性测试**
   - 会话保持 30 分钟以上
   - 多次任务执行不崩溃

2. **性能优化**
   - 减少元素查询次数
   - 优化快照生成速度
   - 添加元素缓存机制

## 测试执行建议

### 测试环境准备

1. **启动 Docker 浏览器服务**
   ```bash
   docker-compose up -d
   # 或
   docker run -p 8000:8000 -p 6080:6080 agent-browser:latest
   ```

2. **验证服务健康**
   ```bash
   curl http://localhost:8000/health
   ```

### 测试执行顺序

1. 先运行单元测试（快速验证基础功能）
2. 再运行集成测试（验证完整流程）
3. 最后运行 Skill Evals（验证用户场景）

### 测试报告要求

每个测试用例记录：
- 执行时间
- 成功/失败状态
- 关键步骤截图
- 错误日志（如有）
- 改进建议

## 参考文档

- `skills/agent-browser/SKILL.md` - Skill 使用指南
- `TEST_FIX_SUMMARY.md` - 已修复问题总结
- `skills/agent-browser/evals/evals.json` - Eval 测试用例
- `CLAUDE.md` - 项目开发指南

