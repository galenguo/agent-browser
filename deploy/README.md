# 多用户会话架构部署指南 (v2)

## 架构概述

v2 架构支持多用户隔离，每个用户拥有独立的浏览器会话、Profile、Cookie 和指纹。

### 核心特性

- **多用户隔离**：每个用户独立 Session，互不干扰
- **灵活部署**：支持本地/Docker 浏览器模式
- **资源管理**：自动超时回收、并发限制
- **向后兼容**：保留旧版 `/tasks` API

### 部署模式

| 模式 | API 部署 | Browser 部署 | 场景 | 成本 |
|------|---------|-------------|------|------|
| **All-in-One** | Docker | 容器内本地 | 单用户/开发 | $7.5/月 |
| **Distributed** | Docker | 独立容器 | 多用户生产 | $30+/月 |

## 快速开始（All-in-One 模式）

### 1. 配置环境变量

```bash
cd deploy/docker
cp .env.v2.example .env
```

编辑 `.env` 文件：

```bash
# LLM API
OPENAI_API_KEY=your_key_here
OPENAI_BASE_URL=https://open.bigmodel.cn/api/coding/paas/v4

# 部署模式
DEPLOYMENT_MODE=all-in-one
BROWSER_MODE=local

# 会话配置
MAX_SESSIONS=10
IDLE_TIMEOUT_SECONDS=1800
```

### 2. 启动服务

```bash
docker-compose -f docker-compose-v2.yml up -d
```

### 3. 验证服务

```bash
# 健康检查
curl http://localhost:8000/health

# 创建会话
curl -X POST http://localhost:8000/sessions/create \
  -H "Content-Type: application/json" \
  -d '{"user_id": "user001"}'

# 提交任务
curl -X POST http://localhost:8000/sessions/{session_id}/task \
  -H "Content-Type: application/json" \
  -d '{
    "task": "打开 https://www.baidu.com",
    "model": "glm-5-turbo",
    "max_steps": 10
  }'
```

### 4. 访问 noVNC

浏览器打开：`http://localhost:6080/vnc.html`

## API 文档

### Session 管理

#### 创建会话

```bash
POST /sessions/create
Content-Type: application/json

{
  "user_id": "user001",
  "profile_config": {}  # 可选
}

# 响应
{
  "session_id": "user001_abc123",
  "user_id": "user001",
  "status": "created"
}
```

#### 查询会话状态

```bash
GET /sessions/{session_id}

# 响应
{
  "session_id": "user001_abc123",
  "user_id": "user001",
  "created_at": 1234567890.0,
  "last_activity": 1234567890.0,
  "idle_time": 120.5,
  "tasks": {
    "task_abc": {
      "status": "completed",
      "task": "打开百度",
      "created_at": 1234567890.0
    }
  }
}
```

#### 删除会话

```bash
DELETE /sessions/{session_id}

# 响应
{
  "status": "deleted",
  "session_id": "user001_abc123"
}
```

#### 列出所有会话

```bash
GET /sessions

# 响应
{
  "sessions": [
    {
      "session_id": "user001_abc123",
      "user_id": "user001",
      "created_at": 1234567890.0,
      "last_activity": 1234567890.0,
      "task_count": 3
    }
  ],
  "total": 1
}
```

### 任务管理

#### 提交任务到会话

```bash
POST /sessions/{session_id}/task
Content-Type: application/json

{
  "task": "打开 https://www.baidu.com 并搜索 Python",
  "model": "glm-5-turbo",
  "max_steps": 50
}

# 响应
{
  "task_id": "task_xyz789",
  "session_id": "user001_abc123",
  "status": "running"
}
```

#### 查询任务状态

```bash
GET /sessions/{session_id}/tasks/{task_id}

# 响应
{
  "task_id": "task_xyz789",
  "status": "completed",
  "result": "任务执行结果...",
  "error": null
}
```

### 向后兼容 API（旧版）

#### 创建任务（自动创建临时 Session）

```bash
POST /tasks
Content-Type: application/json
X-API-Key: optional_user_key

{
  "task": "打开 https://www.google.com",
  "model": "glm-5-turbo",
  "max_steps": 50
}

# 响应
{
  "task_id": "task_xyz789",
  "session_id": "legacy_user_abc_xyz123",
  "status": "running"
}
```

#### 查询任务状态

```bash
GET /tasks/{task_id}

# 响应
{
  "task_id": "task_xyz789",
  "status": "completed",
  "result": "任务执行结果...",
  "error": null
}
```

## 配置说明

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DEPLOYMENT_MODE` | `all-in-one` | 部署模式：`all-in-one` 或 `distributed` |
| `BROWSER_MODE` | `local` | 浏览器模式：`local` 或 `docker` |
| `MAX_SESSIONS` | `10` | 最大并发会话数 |
| `IDLE_TIMEOUT_SECONDS` | `1800` | 会话空闲超时（秒） |
| `PROFILE_STORAGE` | `/data/profiles` | Profile 存储目录 |
| `LOG_LEVEL` | `info` | 日志级别 |

### 资源限制

All-in-One 模式（推荐配置）：

```yaml
deploy:
  resources:
    limits:
      memory: 1G        # 硬限制
      cpus: '1.0'
    reservations:
      memory: 512M      # 软限制
```

## 测试

### 运行自动化测试

```bash
# 安装测试依赖
pip install pytest httpx pytest-asyncio

# 运行测试
pytest tests/test_v2_api.py -v
```

### 手动测试

```bash
# 运行测试脚本
python tests/test_v2_api.py
```

## 监控

### 健康检查

```bash
curl http://localhost:8000/health
```

响应示例：

```json
{
  "status": "ok",
  "sessions": 3,
  "max_sessions": 10,
  "browser_mode": "local"
}
```

### 日志查看

```bash
# 查看容器日志
docker logs -f agent-browser-v2-all-in-one

# 查看应用日志
docker exec agent-browser-v2-all-in-one tail -f /data/logs/info.log
```

## 故障排查

### 会话创建失败

**问题**：`ResourceExhaustedError: Max concurrent sessions reached`

**解决**：
1. 增加 `MAX_SESSIONS` 配置
2. 删除空闲会话：`DELETE /sessions/{session_id}`
3. 等待自动超时回收

### 浏览器启动失败

**问题**：浏览器实例无法启动

**解决**：
1. 检查 Xvfb 是否运行：`docker exec <container> ps aux | grep Xvfb`
2. 检查 CDP 端口：`docker exec <container> netstat -tlnp | grep 19222`
3. 查看日志：`docker logs <container>`

### 内存不足

**问题**：容器 OOM（Out of Memory）

**解决**：
1. 减少 `MAX_SESSIONS`
2. 增加容器内存限制
3. 减少 `shm_size`

## 升级指南

### 从 v1 升级到 v2

1. **备份数据**

```bash
docker cp agent-browser-scheme1:/data/profiles ./backup/profiles
docker cp agent-browser-scheme1:/data/logs ./backup/logs
```

2. **停止旧容器**

```bash
docker-compose down
```

3. **启动 v2 容器**

```bash
docker-compose -f docker-compose-v2.yml up -d
```

4. **验证服务**

```bash
curl http://localhost:8000/health
```

### 向后兼容性

v2 完全兼容 v1 的 `/tasks` API，无需修改客户端代码。

## 成本估算

### All-in-One 模式

- **VPS**: $7.5/月（1 vCPU, 1GB RAM）
- **适用场景**: 单用户、开发测试、低并发

### Distributed 模式（未来）

- **API 容器**: $7.5/月
- **浏览器容器**: $7.5/月 × N
- **总成本**: $7.5 × (1 + N)
- **适用场景**: 多用户、生产环境、高并发

## 下一步

- [ ] 实现 Distributed 模式（独立浏览器容器）
- [ ] 添加用户认证和授权
- [ ] 实现任务队列和优先级
- [ ] 添加 Prometheus 监控指标

---

## Kubernetes 部署

Agent Browser 支持在 Kubernetes 集群中部署，提供更强的可扩展性和高可用性。

### 部署模式

| 模式 | 描述 | 适用场景 |
|------|------|----------|
| **All-in-One** | 单 Pod 包含 API + Browser | 开发测试、小规模生产 |
| **Distributed** | API 和 Browser 分离部署 | 大规模生产、高并发 |

### 前置条件

1. Kubernetes 集群 1.24+
2. kubectl 已配置
3. 镜像已推送到 Registry
4. 持久化存储（PVC）

### 使用原生 YAML 部署

#### 1. 准备配置

```bash
# 复制 Secret 模板
cp k8s/secret.yaml.example k8s/secret.yaml

# 编辑 Secret，填写 API keys
nano k8s/secret.yaml
```

#### 2. 部署 All-in-One 模式

```bash
# 使用脚本（推荐）
./k8s/deploy-k8s.sh --mode aio --registry registry.example.com

# 或手动部署
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secret.yaml
kubectl apply -f k8s/pvc.yaml
kubectl apply -f k8s/aio-deployment.yaml
kubectl apply -f k8s/aio-service.yaml
```

#### 3. 部署分布式模式

```bash
# 使用脚本（推荐）
./k8s/deploy-k8s.sh --mode distributed --registry registry.example.com

# 或手动部署
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secret.yaml
kubectl apply -f k8s/pvc.yaml
kubectl apply -f k8s/api-deployment.yaml
kubectl apply -f k8s/api-service.yaml
kubectl apply -f k8s/browser-deployment.yaml
kubectl apply -f k8s/browser-service.yaml
```

#### 4. 验证部署

```bash
# 检查 Pod 状态
kubectl get pods -n agent-browser

# 检查 Service
kubectl get svc -n agent-browser

# 获取访问地址
NODE_PORT=$(kubectl get svc agent-browser-aio -n agent-browser -o jsonpath='{.spec.ports[0].nodePort}')
echo "API: http://<node-ip>:${NODE_PORT}"

# 测试健康检查
curl http://<node-ip>:${NODE_PORT}/health
```

### 使用 Helm Chart 部署

#### 1. 安装 Helm

```bash
# macOS
brew install helm

# Linux
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
```

#### 2. 部署 All-in-One 模式

```bash
helm install agent-browser ./helm/agent-browser \
  -f helm/agent-browser/values-aio.yaml \
  --set secrets.anthropicApiKey=your-anthropic-key \
  --set secrets.openaiApiKey=your-openai-key \
  --set image.registry=registry.example.com \
  --namespace agent-browser \
  --create-namespace
```

#### 3. 部署分布式模式

```bash
helm install agent-browser ./helm/agent-browser \
  -f helm/agent-browser/values-distributed.yaml \
  --set secrets.anthropicApiKey=your-anthropic-key \
  --set secrets.openaiApiKey=your-openai-key \
  --set image.registry=registry.example.com \
  --namespace agent-browser \
  --create-namespace
```

#### 4. 升级部署

```bash
helm upgrade agent-browser ./helm/agent-browser \
  -f my-values.yaml \
  --namespace agent-browser
```

#### 5. 卸载

```bash
helm uninstall agent-browser --namespace agent-browser
```

### 资源配置

#### All-in-One 模式

```yaml
resources:
  requests:
    memory: "512Mi"
    cpu: "500m"
  limits:
    memory: "2Gi"
    cpu: "2000m"
```

#### 分布式模式

**API Pod:**
```yaml
resources:
  requests:
    memory: "256Mi"
    cpu: "250m"
  limits:
    memory: "1Gi"
    cpu: "1000m"
```

**Browser Pod:**
```yaml
resources:
  requests:
    memory: "512Mi"
    cpu: "500m"
  limits:
    memory: "2Gi"
    cpu: "2000m"
```

### 持久化存储

```yaml
persistence:
  enabled: true
  profiles:
    size: 10Gi
    storageClass: "fast-ssd"
  logs:
    size: 5Gi
    storageClass: "standard"
```

### 自动扩缩容（HPA）

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: agent-browser-api
  namespace: agent-browser
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: agent-browser-api
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
```

### 监控和日志

#### 查看日志

```bash
# 查看 Pod 日志
kubectl logs -n agent-browser <pod-name>

# 实时查看日志
kubectl logs -n agent-browser <pod-name> -f

# 查看上一个容器的日志
kubectl logs -n agent-browser <pod-name> --previous
```

#### 监控指标

```bash
# 查看资源使用情况
kubectl top pods -n agent-browser
kubectl top nodes
```

### 故障排查

#### Pod 无法启动

```bash
# 查看 Pod 事件
kubectl describe pod -n agent-browser <pod-name>

# 查看 Pod 日志
kubectl logs -n agent-browser <pod-name>

# 检查镜像拉取
kubectl get events -n agent-browser --sort-by='.lastTimestamp'
```

#### 健康检查失败

```bash
# 进入容器调试
kubectl exec -it -n agent-browser <pod-name> -- /bin/bash

# 检查环境变量
kubectl exec -n agent-browser <pod-name> -- env

# 测试健康检查端点
kubectl exec -n agent-browser <pod-name> -- curl http://localhost:8000/health
```

### 成本估算

#### All-in-One 模式

- **节点**: 2 vCPU, 4GB RAM
- **成本**: ~$30/月（云服务商）
- **并发会话**: 10

#### 分布式模式

- **API 节点**: 1 vCPU, 1GB RAM × 2 = $30/月
- **Browser 节点**: 2 vCPU, 2GB RAM × 3 = $90/月
- **总成本**: ~$120/月
- **并发会话**: 50+

### 详细文档

更多详细信息请参考：
- [Kubernetes 配置](./k8s/)
- [Helm Chart](./helm/agent-browser/)
- [ ] 实现自动扩缩容
