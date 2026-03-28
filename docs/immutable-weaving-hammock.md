# Agent-Browser 架构优化方案

## Context

基于对以下项目的深度探索：
1. **agent-browser** - 当前实现（FastAPI + browser-use + 5层反检测）
2. **browser-use Cloud** - 官方云服务（Task API + Browser Sessions API）
3. **agent-browser-vercel** - Rust CLI + Daemon + refs 快照模式
4. **openclaw** - Skill 系统 + MCP 集成 + 浏览器工具

## 用户需求

1. **统一 API 网关模式**
   - 支持 API Key 接入不同用户
   - 不同 API Key 使用不同浏览器 Pod 实例
   - 支持自动化横向扩展（K8s HPA）

2. **实时通知机制**
   - 同时支持 WebSocket 推送和 Webhook 回调
   - 可选择配置

3. **混合交互模式**
   - 参考 browser-use Cloud 的实现
   - Agent 自主执行 + 卡点时切换到用户控制
   - 支持 refs 快照模式

## 设计目标

- ✅ 保持现有 5 层反检测能力
- ✅ 兼容现有 API（向后兼容）
- ✅ 支持本地、远程 K8s、browser-use Cloud 三种模式
- ✅ 实时通知用户卡点和进度
- ✅ 灵活的交互模式（Agent 自主 + 用户介入）
- ✅ 易于 openclaw skill 集成

---

## 第一部分：整体架构设计

### 1.1 三层架构

```
┌─────────────────────────────────────────────────────────┐
│                   API Gateway Layer                     │
│  (FastAPI + API Key Auth + WebSocket + Webhook)        │
│  - 统一入口，路由到不同后端                              │
│  - 用户认证和会话管理                                    │
│  - 实时通知分发（WebSocket/Webhook）                     │
└────────────────────┬────────────────────────────────────┘
                     │
        ┌────────────┼────────────┐
        │            │            │
┌───────▼──────┐ ┌──▼──────┐ ┌──▼────────────────┐
│ Local Mode   │ │ K8s Mode│ │ Browser-Use Cloud │
│ (本地浏览器)  │ │ (Pod池) │ │ (官方云服务)       │
└──────────────┘ └─────────┘ └───────────────────┘
```

### 1.2 部署模式对比

| 模式 | 适用场景 | 反检测能力 | 成本 | 扩展性 |
|------|---------|-----------|------|--------|
| Local | 开发测试 | 5层（最强） | 低 | 单机 |
| K8s | 生产环境 | 5层（最强） | 中 | 水平扩展 |
| Browser-Use Cloud | 快速原型 | 基础 | 按用量 | 无限 |

### 1.3 API Key 与资源隔离

**API Key 结构：**
```
agb_<env>_<user_id>_<random>
例如：agb_prod_user123_a1b2c3d4
```

**资源映射：**
```python
api_key → user_id → {
    "mode": "k8s",  # local | k8s | cloud
    "k8s_namespace": "agent-browser-user123",
    "max_sessions": 5,
    "webhook_url": "https://example.com/webhook",
    "websocket_enabled": true
}
```

**K8s 资源隔离：**
- 每个用户独立 Namespace
- 每个 API Key 独立 Pod 池（通过 label selector）
- HPA 基于 CPU/内存/会话数自动扩展

---

## 第二部分：实时通知机制设计

### 2.1 事件类型定义

```python
class EventType(str, Enum):
    # 会话事件
    SESSION_CREATED = "session.created"
    SESSION_CLOSED = "session.closed"

    # 任务事件
    TASK_STARTED = "task.started"
    TASK_PROGRESS = "task.progress"  # 每步更新
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"

    # 交互事件
    INTERVENTION_NEEDED = "intervention.needed"  # 需要用户介入
    INTERVENTION_RESOLVED = "intervention.resolved"

    # 错误事件
    ERROR_OCCURRED = "error.occurred"
```

### 2.2 WebSocket 推送设计

**连接建立：**
```
ws://api.example.com/ws?api_key=agb_xxx&session_id=sess_123
```

**消息格式：**
```json
{
  "event": "intervention.needed",
  "timestamp": "2026-03-28T03:44:51.690Z",
  "session_id": "sess_123",
  "task_id": "task_456",
  "data": {
    "reason": "login_required",
    "current_url": "https://example.com/login",
    "screenshot_url": "https://cdn.example.com/screenshots/xxx.png",
    "live_url": "https://novnc.example.com/vnc.html?session=sess_123",
    "suggested_actions": [
      {"type": "snapshot", "description": "获取页面快照和可交互元素"},
      {"type": "manual", "description": "手动登录后继续"}
    ]
  }
}
```

**心跳机制：**
- 客户端每 30s 发送 ping
- 服务端响应 pong
- 超时 60s 自动断开

### 2.3 Webhook 回调设计

**配置方式：**
```python
# 创建会话时配置
POST /sessions/create
{
  "user_id": "user123",
  "webhook_url": "https://example.com/webhook",
  "webhook_events": ["intervention.needed", "task.completed"]
}
```

**回调格式：**
```http
POST https://example.com/webhook
Content-Type: application/json
X-Agent-Browser-Signature: sha256=xxx

{
  "event": "intervention.needed",
  "timestamp": "2026-03-28T03:44:51.690Z",
  "session_id": "sess_123",
  "task_id": "task_456",
  "data": { ... }
}
```

**重试机制：**
- 失败后指数退避重试（1s, 2s, 4s, 8s, 16s）
- 最多重试 5 次
- 记录失败日志

---

## 第三部分：混合交互模式设计

### 3.1 三种执行模式

**Mode 1: Agent 自主模式（默认）**
```python
POST /sessions/{session_id}/task
{
  "task": "登录网站并提取数据",
  "mode": "autonomous",  # 默认
  "max_steps": 50,
  "intervention_policy": "auto"  # auto | manual | never
}
```

- Agent 完全自主执行
- 遇到卡点自动尝试恢复（循环检测、重试）
- 达到阈值后触发 `intervention.needed` 事件

**Mode 2: Refs 快照模式**
```python
POST /sessions/{session_id}/snapshot
{
  "include_screenshot": true,
  "filter": "interactive"  # all | interactive | content
}

# 返回
{
  "url": "https://example.com/login",
  "elements": [
    {"ref": "@e1", "role": "textbox", "name": "用户名", "value": ""},
    {"ref": "@e2", "role": "textbox", "name": "密码", "value": ""},
    {"ref": "@e3", "role": "button", "name": "登录"}
  ],
  "screenshot_url": "https://cdn.example.com/screenshots/xxx.png"
}

# 用户选择操作
POST /sessions/{session_id}/action
{
  "actions": [
    {"type": "fill", "ref": "@e1", "value": "username"},
    {"type": "fill", "ref": "@e2", "value": "password"},
    {"type": "click", "ref": "@e3"}
  ]
}
```

**Mode 3: 混合模式（推荐）**
```python
POST /sessions/{session_id}/task
{
  "task": "登录网站并提取数据",
  "mode": "hybrid",
  "intervention_policy": "auto",
  "intervention_threshold": {
    "consecutive_failures": 3,
    "loop_detected": true,
    "timeout_seconds": 180
  }
}
```

- 默认 Agent 自主执行
- 触发阈值后自动切换到 refs 模式
- 发送 `intervention.needed` 事件（WebSocket/Webhook）
- 用户可选择：
  - 获取快照 → 手动操作
  - 提供提示 → Agent 继续
  - 手动接管 → 通过 live_url

### 3.2 卡点检测逻辑

**检测条件（任一满足即触发）：**
```python
class InterventionDetector:
    def should_intervene(self, agent_state) -> bool:
        # 1. 连续失败
        if agent_state.consecutive_failures >= 3:
            return True

        # 2. 循环检测
        if self._detect_loop(agent_state.recent_actions):
            return True

        # 3. 超时
        if time.time() - agent_state.last_progress > 180:
            return True

        # 4. 特定错误
        if agent_state.last_error in ["login_required", "captcha_failed"]:
            return True

        return False
```

**触发后的行为：**
1. 暂停 Agent 执行
2. 保存当前状态（URL、cookies、DOM）
3. 生成快照（accessibility tree + screenshot）
4. 发送 `intervention.needed` 事件
5. 等待用户响应（超时 300s 后自动失败）

---

## 第四部分：K8s 部署架构

### 4.1 Pod 架构设计

**Browser Pod 规格：**
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: agent-browser-{user_id}-{instance_id}
  namespace: agent-browser-{user_id}
  labels:
    app: agent-browser
    user_id: user123
    api_key_hash: sha256(api_key)
spec:
  containers:
  - name: browser
    image: agent-browser-chromium:latest
    resources:
      requests:
        memory: "2Gi"
        cpu: "1000m"
      limits:
        memory: "4Gi"
        cpu: "2000m"
    ports:
    - containerPort: 19222  # CDP
      name: cdp
    - containerPort: 6080   # noVNC
      name: novnc
    env:
    - name: DISPLAY
      value: ":99"
    - name: CDP_PORT
      value: "19222"
    volumeMounts:
    - name: profile-storage
      mountPath: /data/profiles
    - name: shm
      mountPath: /dev/shm
  volumes:
  - name: profile-storage
    persistentVolumeClaim:
      claimName: browser-profiles-{user_id}
  - name: shm
    emptyDir:
      medium: Memory
      sizeLimit: 2Gi
```

### 4.2 HPA 自动扩展

**基于会话数的扩展：**
```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: agent-browser-hpa
  namespace: agent-browser-{user_id}
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: agent-browser
  minReplicas: 1
  maxReplicas: 10
  metrics:
  - type: Pods
    pods:
      metric:
        name: active_sessions
      target:
        type: AverageValue
        averageValue: "3"  # 每个 Pod 最多 3 个会话
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```

### 4.3 服务发现与负载均衡

**Service 定义：**
```yaml
apiVersion: v1
kind: Service
metadata:
  name: agent-browser-service
  namespace: agent-browser-{user_id}
spec:
  selector:
    app: agent-browser
    user_id: user123
  ports:
  - name: cdp
    port: 19222
    targetPort: 19222
  - name: novnc
    port: 6080
    targetPort: 6080
  type: ClusterIP
```

**API Gateway 路由逻辑：**
```python
class K8sBackend:
    async def get_or_create_pod(self, api_key: str) -> PodInfo:
        user_id = self._extract_user_id(api_key)
        namespace = f"agent-browser-{user_id}"

        # 1. 查找空闲 Pod
        pods = await self.k8s_client.list_pods(
            namespace=namespace,
            label_selector=f"app=agent-browser,user_id={user_id}"
        )

        for pod in pods:
            if self._get_active_sessions(pod) < 3:  # 未满
                return PodInfo(
                    pod_name=pod.name,
                    cdp_url=f"ws://{pod.ip}:19222",
                    novnc_url=f"http://{pod.ip}:6080"
                )

        # 2. 触发扩展（通过增加 Deployment replicas）
        await self._scale_up(namespace)

        # 3. 等待新 Pod ready
        return await self._wait_for_pod(namespace, timeout=60)
```

---

## 第五部分：Browser-Use Cloud 集成

### 5.1 三种云端模式

**模式 A：Browser Sessions API（仅浏览器）**
```python
class BrowserUseCloudBackend:
    async def create_session(self, api_key: str) -> SessionInfo:
        # 创建远程浏览器
        response = await self.client.post(
            "https://api.browser-use.com/api/v2/browsers",
            headers={"X-Browser-Use-API-Key": api_key},
            json={"timeout": 3600}
        )

        return SessionInfo(
            session_id=response["id"],
            cdp_url=response["cdpUrl"],
            live_url=response["liveUrl"]
        )

    async def run_task(self, session_id: str, task: str):
        # 本地 Agent 连接到远程浏览器
        browser = await playwright.chromium.connect_over_cdp(
            self.sessions[session_id].cdp_url
        )
        agent = Agent(task=task, browser=browser)
        return await agent.run()
```

**模式 B：Task API（完整 Agent 服务）**
```python
class BrowserUseCloudTaskBackend:
    async def run_task(self, api_key: str, task: str) -> TaskResult:
        # 提交任务到云端 Agent
        response = await self.client.post(
            "https://api.browser-use.com/api/v2/tasks",
            headers={"X-Browser-Use-API-Key": api_key},
            json={
                "task": task,
                "llm": "browser-use-llm",
                "maxSteps": 50
            }
        )

        task_id = response["id"]
        session_id = response["sessionId"]

        # 轮询任务状态
        while True:
            task = await self._get_task(task_id)
            if task["status"] in ["finished", "stopped"]:
                return TaskResult(
                    success=task.get("isSuccess", False),
                    output=task.get("output"),
                    steps=task.get("steps")
                )
            await asyncio.sleep(2)
```

**模式 C：混合模式（推荐）**
```python
class HybridCloudBackend:
    async def run_task_with_intervention(
        self,
        api_key: str,
        task: str,
        on_intervention: Callable
    ):
        # 1. 创建 Browser Session
        session = await self.create_browser_session(api_key)

        # 2. 本地 Agent 连接
        browser = await self._connect_cdp(session.cdp_url)
        agent = Agent(task=task, browser=browser)

        # 3. 注册卡点回调
        agent.register_should_stop_callback(
            lambda: self._check_intervention_needed(agent)
        )

        # 4. 运行
        try:
            result = await agent.run()
            return result
        except InterventionNeeded as e:
            # 5. 触发用户介入
            await on_intervention(
                session_id=session.id,
                live_url=session.live_url,
                reason=e.reason
            )
            # 6. 等待用户操作后继续
            await self._wait_for_user_action()
            return await agent.resume()
```

### 5.2 Profile Sync 集成

**自动同步本地 Profile 到云端：**
```python
class ProfileSyncService:
    async def sync_to_cloud(
        self,
        local_profile_path: str,
        cloud_api_key: str
    ) -> str:
        # 1. 创建云端 Profile
        profile = await self.cloud_client.create_profile(
            name=f"synced-{uuid.uuid4()}"
        )

        # 2. 读取本地 cookies
        cookies = self._read_chrome_cookies(local_profile_path)

        # 3. 上传到云端
        await self.cloud_client.upload_cookies(
            profile_id=profile["id"],
            cookies=cookies
        )

        return profile["id"]
```

---

## 第六部分：OpenClaw Skill 优化设计

### 6.1 新的 Skill 接口

**SKILL.md 结构：**
```markdown
---
name: agent-browser
description: 反检测浏览器自动化，支持高防护网站
command-dispatch: tool
command-tool: agent-browser
command-arg-mode: raw
---

# Agent Browser Skill

## 能力
- 5层反检测栈（CloakBrowser + patchright + rebrowser-patches）
- 多模式：本地/K8s/browser-use Cloud
- 实时通知：WebSocket + Webhook
- 混合交互：Agent 自主 + 用户介入

## 使用方式

### 1. 创建会话
\`\`\`
agent-browser create-session --api-key <key> --mode k8s
\`\`\`

### 2. 提交任务（自主模式）
\`\`\`
agent-browser run-task --session-id <id> --task "登录网站" --mode autonomous
\`\`\`

### 3. 获取快照（介入模式）
\`\`\`
agent-browser snapshot --session-id <id> --filter interactive
\`\`\`

### 4. 执行操作
\`\`\`
agent-browser action --session-id <id> --actions '[{"type":"click","ref":"@e3"}]'
\`\`\`
```

### 6.2 MCP Tool 映射

**将 agent-browser 封装为 MCP Tool：**
```typescript
// openclaw 侧的 MCP 工具定义
const agentBrowserTools = {
  "agent-browser.create-session": {
    description: "创建浏览器会话",
    inputSchema: {
      type: "object",
      properties: {
        api_key: { type: "string" },
        mode: { enum: ["local", "k8s", "cloud"] },
        webhook_url: { type: "string" }
      }
    }
  },
  "agent-browser.run-task": {
    description: "运行自动化任务",
    inputSchema: {
      type: "object",
      properties: {
        session_id: { type: "string" },
        task: { type: "string" },
        mode: { enum: ["autonomous", "hybrid"] }
      }
    }
  },
  "agent-browser.snapshot": {
    description: "获取页面快照和可交互元素",
    inputSchema: {
      type: "object",
      properties: {
        session_id: { type: "string" },
        filter: { enum: ["all", "interactive", "content"] }
      }
    }
  },
  "agent-browser.action": {
    description: "执行页面操作",
    inputSchema: {
      type: "object",
      properties: {
        session_id: { type: "string" },
        actions: {
          type: "array",
          items: {
            type: "object",
            properties: {
              type: { enum: ["click", "fill", "type", "select"] },
              ref: { type: "string" },
              value: { type: "string" }
            }
          }
        }
      }
    }
  }
};
```

**实现方式：**
```python
# src/openclaw/mcp_bridge.py
class MCPBridge:
    """将 agent-browser API 桥接为 MCP 工具"""

    async def call_tool(self, tool_name: str, arguments: Dict) -> Dict:
        if tool_name == "agent-browser.create-session":
            return await self._create_session(**arguments)
        elif tool_name == "agent-browser.run-task":
            return await self._run_task(**arguments)
        elif tool_name == "agent-browser.snapshot":
            return await self._snapshot(**arguments)
        elif tool_name == "agent-browser.action":
            return await self._action(**arguments)
```

### 6.3 WebSocket 通知集成

**openclaw 接收实时通知：**
```typescript
// openclaw 侧的 WebSocket 客户端
class AgentBrowserNotifier {
  async connect(sessionId: string, apiKey: string) {
    const ws = new WebSocket(
      `ws://api.example.com/ws?api_key=${apiKey}&session_id=${sessionId}`
    );

    ws.on('message', (data) => {
      const event = JSON.parse(data);

      if (event.event === 'intervention.needed') {
        this.notifyUser({
          type: 'browser_intervention',
          reason: event.data.reason,
          liveUrl: event.data.live_url,
          screenshot: event.data.screenshot_url
        });
      }
    });
  }
}
```

### 6.4 自动安装模式

**参考 agent-browser-vercel 的安装方式：**
```bash
# 在 SKILL.md 中定义安装钩子
---
install-command: |
  curl -fsSL https://agent-browser.example.com/install.sh | sh
---
```

**安装脚本自动检测：**
```bash
#!/bin/bash
# install.sh
if command -v agent-browser &> /dev/null; then
    echo "✅ agent-browser already installed"
    exit 0
fi

# 检测操作系统
if [[ "$OSTYPE" == "darwin"* ]]; then
    brew install agent-browser
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    curl -L https://github.com/.../agent-browser-linux -o /usr/local/bin/agent-browser
    chmod +x /usr/local/bin/agent-browser
fi
```

---

## 第七部分：实现路线图

### 7.1 Phase 1: API Gateway 增强（1-2周）

**目标：** 添加 API Key 认证、WebSocket 通知、Webhook 回调

**关键文件：**
- `src/api.py` - 添加认证中间件、WebSocket 端点
- `src/auth.py` (新建) - API Key 验证逻辑
- `src/notification.py` (新建) - WebSocket/Webhook 管理器
- `src/models.py` - 添加事件模型

**实现步骤：**
1. 实现 API Key 认证中间件
2. 添加 WebSocket 端点 `/ws`
3. 实现事件发布-订阅系统
4. 添加 Webhook 回调机制
5. 更新所有端点支持 API Key

**验证：**
```bash
# 测试 API Key 认证
curl -H "X-API-Key: agb_test_xxx" http://localhost:8000/sessions/create

# 测试 WebSocket
wscat -c "ws://localhost:8000/ws?api_key=agb_test_xxx&session_id=sess_123"
```

### 7.2 Phase 2: 混合交互模式（2-3周）

**目标：** 实现 Agent 自主 + Refs 快照 + 卡点检测

**关键文件：**
- `src/agent/runner.py` - 添加卡点检测逻辑
- `src/agent/intervention.py` (新建) - InterventionDetector 类
- `src/agent/snapshot.py` (新建) - 可访问性树快照生成
- `src/api.py` - 添加 `/snapshot` 和 `/action` 端点

**实现步骤：**
1. 实现 InterventionDetector（循环检测、超时、失败计数）
2. 实现可访问性树快照生成（refs 模式）
3. 添加 Agent 执行暂停/恢复机制
4. 实现用户操作 API（click/fill/type）
5. 集成 WebSocket 通知触发

**验证：**
```python
# 测试混合模式
POST /sessions/{id}/task
{
  "task": "登录网站",
  "mode": "hybrid",
  "intervention_threshold": {"consecutive_failures": 3}
}
```

---

### 7.3 Phase 3: K8s 部署支持（2-3周）

**目标：** 支持 K8s Pod 池、HPA 自动扩展、用户隔离

**关键文件：**
- `src/backend/k8s_backend.py` (新建) - K8s 客户端封装
- `src/session/pool_manager.py` - 添加 K8s 模式支持
- `k8s/deployment.yaml` (新建) - K8s 部署清单
- `k8s/hpa.yaml` (新建) - HPA 配置

**实现步骤：**
1. 实现 K8sBackend 类（Pod 创建、查询、删除）
2. 修改 SessionPoolManager 支持多后端（local/k8s/cloud）
3. 实现基于 API Key 的 Namespace 隔离
4. 配置 HPA 基于会话数扩展
5. 实现服务发现和负载均衡

**验证：**
```bash
# 部署到 K8s
kubectl apply -f k8s/

# 测试自动扩展
for i in {1..10}; do
  curl -H "X-API-Key: agb_test_xxx" \
    -X POST http://api.example.com/sessions/create
done

# 检查 Pod 数量
kubectl get pods -n agent-browser-test
```

### 7.4 Phase 4: Browser-Use Cloud 集成（1-2周）

**目标：** 支持远程 browser-use Cloud 作为后端

**关键文件：**
- `src/backend/cloud_backend.py` (新建) - Browser-Use Cloud 客户端
- `src/backend/base.py` (新建) - 后端抽象接口
- `src/session/pool_manager.py` - 添加 cloud 模式

**实现步骤：**
1. 实现 CloudBackend 类（Browser Sessions API + Task API）
2. 实现 Profile Sync 功能（本地 → 云端）
3. 添加混合模式（本地 Agent + 远程浏览器）
4. 实现 CDP URL 和 Live URL 透传
5. 配置 API Key 映射

**验证：**
```bash
# 配置 Cloud 模式
export BROWSER_USE_API_KEY=bu_xxx
export DEPLOYMENT_MODE=cloud

# 测试远程浏览器
curl -H "X-API-Key: agb_test_xxx" \
  -X POST http://localhost:8000/sessions/create \
  -d '{"mode": "cloud"}'
```

---

### 7.5 Phase 5: OpenClaw Skill 优化（1周）

**目标：** 优化 skill 集成，支持实时通知和自动安装

**关键文件：**
- `skills/agent-browser/SKILL.md` - 更新 skill 定义
- `skills/agent-browser/install.sh` (新建) - 自动安装脚本
- `src/openclaw/mcp_bridge.py` (新建) - MCP 工具桥接

**实现步骤：**
1. 更新 SKILL.md 添加新的交互模式
2. 实现自动安装脚本
3. 添加 WebSocket 通知示例
4. 更新 MCP 工具定义
5. 编写 E2E 测试脚本

**验证：**
```bash
# 测试自动安装
curl -fsSL https://agent-browser.example.com/install.sh | sh

# 测试 skill 调用
agent-browser create-session --api-key agb_test_xxx
agent-browser run-task --session-id sess_123 --task "登录网站" --mode hybrid
```

---

## 第八部分：关键技术决策

### 8.1 后端架构选择

**三种后端模式对比：**

| 特性 | Local | K8s | Browser-Use Cloud |
|------|-------|-----|-------------------|
| 反检测能力 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ |
| 部署复杂度 | 低 | 高 | 极低 |
| 运维成本 | 低 | 中 | 按用量 |
| 扩展性 | 单机 | 水平扩展 | 无限 |
| 数据隐私 | 完全控制 | 完全控制 | 第三方 |
| 适用场景 | 开发测试 | 生产环境 | 快速原型 |

**推荐策略：**
- 开发阶段：Local 模式
- 生产环境（高防护网站）：K8s 模式
- 快速验证/低防护网站：Cloud 模式

### 8.2 实时通知机制选择

**WebSocket vs Webhook：**

| 特性 | WebSocket | Webhook |
|------|-----------|---------|
| 实时性 | 毫秒级 | 秒级 |
| 连接开销 | 持久连接 | 按需 HTTP |
| 客户端要求 | 需要 WebSocket 支持 | 标准 HTTP |
| 可靠性 | 需要心跳 | 重试机制 |
| 适用场景 | 实时监控 | 异步通知 |

**推荐策略：**
- 同时支持两种方式
- 用户可选择配置
- WebSocket 用于实时监控
- Webhook 用于关键事件通知

---

## 第九部分：API 设计详细规范

### 9.1 认证与授权

**API Key 格式：**
```
agb_<env>_<user_id>_<random>
例如：agb_prod_alice_a1b2c3d4e5f6
```

**认证方式：**
```http
# Header 方式（推荐）
X-API-Key: agb_prod_alice_xxx

# Query 参数方式（WebSocket）
ws://api.example.com/ws?api_key=agb_prod_alice_xxx
```

**权限模型：**
```python
class APIKey:
    user_id: str
    mode: Literal["local", "k8s", "cloud"]
    max_sessions: int
    allowed_operations: List[str]  # ["create", "read", "delete"]
    rate_limit: int  # 请求/分钟
```

### 9.2 核心 API 端点

**会话管理：**
```
POST   /v2/sessions              创建会话
GET    /v2/sessions              列出所有会话
GET    /v2/sessions/{id}         获取会话详情
DELETE /v2/sessions/{id}         删除会话
```

**任务管理：**
```
POST   /v2/sessions/{id}/tasks   提交任务
GET    /v2/sessions/{id}/tasks/{task_id}  获取任务状态
PATCH  /v2/sessions/{id}/tasks/{task_id}  暂停/恢复任务
```

**交互控制：**
```
GET    /v2/sessions/{id}/snapshot         获取页面快照
POST   /v2/sessions/{id}/actions          执行操作
GET    /v2/sessions/{id}/screenshot       获取截图
```

**实时通知：**
```
WS     /ws?api_key=xxx&session_id=xxx     WebSocket 连接
POST   /v2/webhooks                        配置 Webhook
```

### 9.3 请求/响应示例

**创建会话（混合模式）：**
```json
POST /v2/sessions
{
  "mode": "hybrid",
  "backend": "k8s",
  "webhook_url": "https://example.com/webhook",
  "webhook_events": ["intervention.needed", "task.completed"],
  "intervention_policy": {
    "consecutive_failures": 3,
    "timeout_seconds": 180,
    "loop_detection": true
  }
}

Response:
{
  "session_id": "sess_abc123",
  "status": "active",
  "cdp_url": "ws://10.0.1.5:19222",
  "live_url": "http://10.0.1.5:6080/vnc.html",
  "created_at": "2026-03-28T04:00:00Z"
}
```

**提交任务：**
```json
POST /v2/sessions/sess_abc123/tasks
{
  "task": "登录 Boss直聘并搜索 Python 工程师",
  "mode": "autonomous",
  "max_steps": 50
}

Response:
{
  "task_id": "task_xyz789",
  "status": "running",
  "current_step": 0,
  "started_at": "2026-03-28T04:01:00Z"
}
```

---


## 第十部分：OpenClaw Skill 完整设计

### 10.1 更新后的 SKILL.md 结构

```markdown
---
name: agent-browser
description: 反检测浏览器自动化，支持本地/K8s/Cloud 三种模式
version: 2.0.0
command-dispatch: tool
command-tool: agent-browser
install-command: curl -fsSL https://agent-browser.example.com/install.sh | sh
---

# Agent Browser Skill v2

## 核心能力

- **5层反检测栈**：CloakBrowser + patchright + rebrowser-patches
- **三种部署模式**：local（开发）/ k8s（生产）/ cloud（快速原型）
- **混合交互模式**：Agent 自主 + 用户介入 + refs 快照
- **实时通知**：WebSocket 推送 + Webhook 回调
```


### 10.2 使用流程示例

**1. 创建会话：**
```bash
agent-browser create-session \
  --api-key agb_prod_user123_xxx \
  --mode hybrid \
  --backend k8s
```

**2. 提交任务（自主模式）：**
```bash
agent-browser run-task \
  --session-id sess_abc123 \
  --task "登录 Boss直聘并搜索 Python 工程师" \
  --max-steps 50
```

**3. 监听通知：**
```bash
agent-browser watch --session-id sess_abc123
# 输出实时事件流
```

**4. 处理卡点：**
```bash
# 获取快照
agent-browser snapshot --session-id sess_abc123

# 执行操作
agent-browser action --session-id sess_abc123 \
  --actions '[{"type":"click","ref":"@e3"}]'
```

