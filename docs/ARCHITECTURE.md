# 多用户会话架构设计 (v2)

## 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                     FastAPI (api_v2.py)                     │
│  - Session 管理 API                                          │
│  - 任务提交 API                                              │
│  - 向后兼容 API                                              │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│              SessionPoolManager (会话池管理器)               │
│  - 多用户隔离                                                │
│  - Session 生命周期管理                                      │
│  - 空闲超时回收                                              │
│  - 并发限制                                                  │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│           BrowserInstancePool (浏览器实例池)                 │
│  - 本地浏览器管理 (local mode)                               │
│  - Docker 浏览器管理 (docker mode)                           │
│  - 资源分配和释放                                            │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                  CloakBrowser + patchright                   │
│  - CDP 连接                                                  │
│  - 反检测浏览器                                              │
│  - 独立 Profile 目录                                         │
└─────────────────────────────────────────────────────────────┘
```

## 核心组件

### 1. 数据模型 (models.py)

定义核心数据结构：

```python
class BrowserMode(str, Enum):
    LOCAL = "local"      # 本地浏览器
    DOCKER = "docker"    # Docker 容器浏览器

class BrowserInstance(BaseModel):
    instance_id: str
    mode: BrowserMode
    cdp_url: str         # ws://host:port
    profile_dir: str
    process: Optional[Any] = None      # 本地模式
    container_id: Optional[str] = None # Docker 模式

class UserSession(BaseModel):
    session_id: str
    user_id: str
    browser_instance: BrowserInstance
    browser_session: Any  # browser-use BrowserSession
    tasks: Dict[str, Dict] = {}
    created_at: float
    last_activity: float
```

### 2. BrowserInstancePool (browser_instance_pool.py)

**职责**：
- 管理浏览器实例的生命周期
- 支持本地和 Docker 两种模式
- 资源分配和释放

**关键方法**：

```python
async def allocate(
    self,
    session_id: str,
    profile_dir: str,
) -> BrowserInstance:
    """分配浏览器实例"""
    if self.mode == "local":
        return await self._allocate_local(session_id, profile_dir)
    else:
        return await self._allocate_docker(session_id, profile_dir)

async def release(self, session_id: str):
    """释放浏览器实例"""
```

**本地模式实现**：

```python
async def _allocate_local(
    self,
    session_id: str,
    profile_dir: str,
) -> BrowserInstance:
    """启动本地 CloakBrowser 进程"""
    # 1. 启动 stealth_launcher
    # 2. 获取 CDP URL
    # 3. 返回 BrowserInstance
```

**Docker 模式实现**（未来）：

```python
async def _allocate_docker(
    self,
    session_id: str,
    profile_dir: str,
) -> BrowserInstance:
    """启动 Docker 容器中的 CloakBrowser"""
    # 1. docker run -d --name browser-{session_id}
    # 2. 端口映射 CDP
    # 3. 挂载 profile_dir
    # 4. 返回 BrowserInstance
```

### 3. SessionPoolManager (session_pool_manager.py)

**职责**：
- 多用户会话隔离
- Session 生命周期管理
- 任务调度和执行
- 空闲超时回收

**关键方法**：

```python
async def create_session(
    self,
    user_id: str,
    profile_config: Optional[Dict] = None,
) -> str:
    """创建新会话"""
    # 1. 检查并发限制
    # 2. 创建独立 Profile 目录
    # 3. 分配浏览器实例
    # 4. 创建 browser-use BrowserSession
    # 5. 返回 session_id

async def submit_task(
    self,
    session_id: str,
    task: str,
    llm_config: Dict,
    max_steps: int = 50,
) -> str:
    """提交任务到指定会话"""
    # 1. 验证 session 存在
    # 2. 创建 Agent
    # 3. 异步执行任务
    # 4. 返回 task_id

async def close_session(self, session_id: str):
    """关闭会话"""
    # 1. 关闭 browser-use session
    # 2. 释放浏览器实例
    # 3. 清理资源
```

**空闲监控**：

```python
async def _idle_monitor(self):
    """空闲监控：超时自动关闭会话"""
    while True:
        await asyncio.sleep(60)
        for session_id, session in self.sessions.items():
            if session.is_idle(self.idle_timeout):
                await self.close_session(session_id)
```

### 4. API 层 (api_v2.py)

**新增 Session 级别 API**：

```python
# Session 管理
POST   /sessions/create          # 创建会话
GET    /sessions/{session_id}    # 查询会话状态
DELETE /sessions/{session_id}    # 删除会话
GET    /sessions                 # 列出所有会话

# 任务管理
POST   /sessions/{session_id}/task              # 提交任务
GET    /sessions/{session_id}/tasks/{task_id}   # 查询任务状态
```

**向后兼容 API**：

```python
# 旧版 API（自动创建临时 Session）
POST   /tasks           # 创建任务
GET    /tasks/{task_id} # 查询任务状态
```

## 数据流

### 创建会话流程

```
1. Client → POST /sessions/create
2. API → SessionPoolManager.create_session()
3. SessionPoolManager → 创建 Profile 目录
4. SessionPoolManager → BrowserInstancePool.allocate()
5. BrowserInstancePool → 启动浏览器（本地/Docker）
6. BrowserInstancePool → 返回 BrowserInstance
7. SessionPoolManager → 创建 browser-use BrowserSession
8. SessionPoolManager → 返回 session_id
9. API → 返回响应给 Client
```

### 提交任务流程

```
1. Client → POST /sessions/{session_id}/task
2. API → SessionPoolManager.submit_task()
3. SessionPoolManager → 验证 session 存在
4. SessionPoolManager → 创建 Agent（复用 browser_session）
5. SessionPoolManager → 异步执行 agent.run()
6. SessionPoolManager → 返回 task_id
7. API → 返回响应给 Client
8. [后台] Agent 执行任务
9. [后台] 更新任务状态
```

### 空闲回收流程

```
1. [后台] _idle_monitor 每分钟检查
2. 遍历所有 sessions
3. 检查 last_activity 时间
4. 如果超过 idle_timeout：
   - 关闭 browser-use session
   - 释放浏览器实例
   - 删除 session
```

## 隔离机制

### 1. Profile 隔离

每个 Session 独立 Profile 目录：

```
/data/profiles/
├── user001_abc123/    # Session 1
│   ├── Default/
│   ├── cookies.db
│   └── ...
├── user002_def456/    # Session 2
│   ├── Default/
│   ├── cookies.db
│   └── ...
```

### 2. 浏览器实例隔离

- **本地模式**：每个 Session 独立进程
- **Docker 模式**：每个 Session 独立容器

### 3. 任务隔离

每个 Session 独立任务队列：

```python
session.tasks = {
    "task_abc": {"status": "running", ...},
    "task_def": {"status": "completed", ...},
}
```

## 资源管理

### 并发限制

```python
MAX_SESSIONS = 10  # 最大并发会话数

if len(self.sessions) >= self.max_concurrent:
    raise ResourceExhaustedError("Max concurrent sessions reached")
```

### 超时回收

```python
IDLE_TIMEOUT_SECONDS = 1800  # 30 分钟

if session.is_idle(self.idle_timeout):
    await self.close_session(session_id)
```

### 内存优化

- **Profile 目录**：按需创建，超时删除
- **浏览器实例**：按需启动，空闲关闭
- **任务历史**：限制保留数量

## 部署模式

### All-in-One 模式（当前）

```
┌─────────────────────────────────────┐
│         Docker Container            │
│  ┌──────────────────────────────┐   │
│  │  FastAPI + SessionPoolManager│   │
│  └──────────────────────────────┘   │
│  ┌──────────────────────────────┐   │
│  │  BrowserInstancePool (local) │   │
│  └──────────────────────────────┘   │
│  ┌──────────────────────────────┐   │
│  │  CloakBrowser Processes      │   │
│  │  - Session 1 (CDP :19222)    │   │
│  │  - Session 2 (CDP :19223)    │   │
│  └──────────────────────────────┘   │
└─────────────────────────────────────┘
```

### Distributed 模式（未来）

```
┌─────────────────────────────────────┐
│      API Container                  │
│  ┌──────────────────────────────┐   │
│  │  FastAPI + SessionPoolManager│   │
│  └──────────────────────────────┘   │
│  ┌──────────────────────────────┐   │
│  │ BrowserInstancePool (docker) │   │
│  └──────────────────────────────┘   │
└─────────────────────────────────────┘
              ↓ Docker API
┌─────────────────────────────────────┐
│   Browser Container 1 (Session 1)   │
│  - CloakBrowser                     │
│  - CDP :19222                       │
└─────────────────────────────────────┘
┌─────────────────────────────────────┐
│   Browser Container 2 (Session 2)   │
│  - CloakBrowser                     │
│  - CDP :19222                       │
└─────────────────────────────────────┘
```

## 扩展性

### 水平扩展

- **All-in-One 模式**：单容器多会话（10-50 并发）
- **Distributed 模式**：多容器独立会话（50+ 并发）

### 负载均衡

未来可添加：
- API 层负载均衡（Nginx/HAProxy）
- 浏览器实例池负载均衡
- 跨节点会话调度

## 安全性

### 隔离保证

- ✅ Profile 目录隔离（文件系统权限）
- ✅ 浏览器进程隔离（独立进程/容器）
- ✅ Cookie 隔离（独立 Profile）
- ✅ 指纹隔离（CloakBrowser 随机化）

### 访问控制

未来可添加：
- 用户认证（JWT/OAuth）
- Session 权限验证
- API Rate Limiting

## 监控指标

### 关键指标

- `sessions_total`: 当前会话数
- `sessions_max`: 最大会话数
- `tasks_running`: 运行中任务数
- `tasks_completed`: 完成任务数
- `tasks_failed`: 失败任务数
- `browser_instances`: 浏览器实例数
- `memory_usage`: 内存使用量

### 健康检查

```python
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "sessions": len(_session_manager.sessions),
        "max_sessions": _session_manager.max_concurrent,
        "browser_mode": _session_manager.browser_pool.mode,
    }
```

## 未来优化

### Phase 1（已完成）
- ✅ 多用户会话隔离
- ✅ 本地浏览器模式
- ✅ 向后兼容 API

### Phase 2（计划中）
- [ ] Docker 浏览器模式
- [ ] 独立浏览器容器
- [ ] 跨容器通信

### Phase 3（未来）
- [ ] 用户认证和授权
- [ ] 任务队列和优先级
- [ ] Prometheus 监控
- [ ] 自动扩缩容
- [ ] 多节点部署
