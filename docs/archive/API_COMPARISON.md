# API V1 vs API V2 对比分析

## 📊 核心区别

| 特性 | API V1 (api.py) | API V2 (api_multiuser_v2.py) |
|------|----------------|------------------------------|
| **端口** | 8000 | 8001 |
| **用户模式** | 单用户 | 多用户（基于 API Key） |
| **Profile 管理** | 临时（Session 过期删除） | 持久化（30天保留） |
| **登录状态** | ❌ 每次丢失 | ✅ 自动保留 |
| **密码保存** | ❌ 每次输入 | ✅ 浏览器自动填充 |
| **Cookies** | ❌ 每次重新登录 | ✅ 自动复用 |
| **Session 管理** | 简单（全局单例） | 复杂（Session Pool） |
| **API 认证** | 无 | API Key 验证 |
| **WebSocket 截图** | ✅ 支持 | ❌ 不支持 |
| **人工接管** | ✅ 支持 | ❌ 不支持 |
| **代码行数** | 352 行 | 397 行 |

## 🎯 使用场景

### API V1 适合：
- ✅ 单用户使用
- ✅ 临时任务（不需要保留登录状态）
- ✅ 需要实时截图监控
- ✅ 需要人工接管（验证码等）
- ✅ 简单快速的自动化任务

### API V2 适合：
- ✅ 多用户共享服务
- ✅ 需要保留登录状态（避免重复登录）
- ✅ 长期使用（多天/多周）
- ✅ 需要 API Key 认证
- ✅ SaaS 服务场景

## 🤔 整合方案

### 方案 A：在 API V1 中添加可选的持久化功能（推荐）✅

**优点**：
- ✅ 只需要一个 API 服务器
- ✅ 向后兼容（默认行为不变）
- ✅ 保留所有 V1 功能（WebSocket、人工接管）
- ✅ 通过环境变量控制是否启用持久化

**实现方式**：
```python
# 环境变量控制
ENABLE_PERSISTENT_PROFILE=false  # 默认关闭（V1 行为）
ENABLE_PERSISTENT_PROFILE=true   # 启用持久化（V2 行为）

# API 端点保持不变
POST /tasks  # 提交任务（自动检测是否启用持久化）
```

**改动**：
- 在 api.py 中集成 ProfileManager
- 添加可选的 API Key 验证
- 根据环境变量决定是否使用持久化 Profile

---

### 方案 B：保持两个独立的 API

**优点**：
- ✅ 功能分离清晰
- ✅ 互不影响
- ✅ 用户可以选择

**缺点**：
- ❌ 需要维护两套代码
- ❌ 需要两个端口
- ❌ 功能重复

---

### 方案 C：只使用 API V1（不添加持久化）

**优点**：
- ✅ 最简单
- ✅ 无需改动

**缺点**：
- ❌ 每次都需要重新登录
- ❌ 用户体验差

---

## 💡 推荐方案：方案 A（整合到 API V1）

### 实现步骤

1. **在 api.py 中添加 ProfileManager**
2. **添加环境变量控制**
3. **保持向后兼容**
4. **可选的 API Key 验证**

### 配置示例

**默认模式（V1 行为）**：
```bash
# 不设置环境变量，默认使用临时 Profile
docker-compose up -d

# 或显式禁用
ENABLE_PERSISTENT_PROFILE=false docker-compose up -d
```

**持久化模式（V2 行为）**：
```bash
# 启用持久化 Profile
ENABLE_PERSISTENT_PROFILE=true docker-compose up -d
```

### API 使用

**临时模式（默认）**：
```bash
# 不需要 API Key
curl -X POST http://localhost:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{"task": "打开百度"}'
```

**持久化模式**：
```bash
# 需要 API Key（可选）
curl -X POST http://localhost:8000/tasks \
  -H "X-API-Key: sk-your-key" \
  -H "Content-Type: application/json" \
  -d '{"task": "打开百度"}'

# 如果不提供 API Key，使用默认 Profile
curl -X POST http://localhost:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{"task": "打开百度"}'
```

---

## 📝 结论

**推荐使用方案 A：整合到 API V1**

理由：
1. ✅ 保持简单（只有一个 API）
2. ✅ 向后兼容（默认行为不变）
3. ✅ 功能完整（保留 WebSocket、人工接管）
4. ✅ 灵活配置（环境变量控制）
5. ✅ 用户体验最佳

**下一步**：
- 修改 api.py，集成 ProfileManager
- 添加环境变量控制
- 测试向后兼容性
- 更新文档

---

## 🚀 快速决策

**如果你的使用场景是：**

1. **单用户，临时任务** → 继续使用 API V1（无需改动）
2. **单用户，需要保留登录状态** → 使用方案 A（整合）
3. **多用户，SaaS 服务** → 使用方案 A（整合）+ API Key 验证

**我的建议**：
- 实施方案 A（整合到 API V1）
- 默认禁用持久化（保持现有行为）
- 用户可以通过环境变量启用持久化
- 这样既保持了简单性，又提供了灵活性
