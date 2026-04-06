# 部署脚本说明

本目录包含 Agent Browser 的所有部署脚本。

## 脚本列表

### 安装脚本

| 脚本 | 描述 | 用途 |
|------|------|------|
| `install.sh` | 主安装脚本 | 跨平台一键安装入口 |
| `install-macos.sh` | macOS 安装脚本 | macOS 平台依赖安装 |
| `install-linux.sh` | Linux 安装脚本 | Linux 平台依赖安装 |

### Docker 部署脚本

| 脚本 | 描述 | 用途 |
|------|------|------|
| `build-multiarch.sh` | 多架构镜像构建 | 构建 linux/amd64 和 darwin/arm64 镜像 |
| `deploy-docker.sh` | Docker 部署脚本 | 部署 All-in-One 或分布式模式 |
| `push-images.sh` | 镜像推送脚本 | 推送镜像到私有 Registry |

### Kubernetes 部署脚本

| 脚本 | 描述 | 用途 |
|------|------|------|
| `deploy-k8s.sh` | K8s 部署脚本 | 部署到 Kubernetes 集群 |

### 测试脚本

| 脚本 | 描述 | 用途 |
|------|------|------|
| `test_openclaw_e2e.sh` | OpenClaw × agent-browser E2E 测试 | 通过 OpenClaw agent CLI 调用 skill，验证 4 个核心场景 |

#### test_openclaw_e2e.sh 使用说明

**前提条件：**
- FastAPI 服务运行中（`localhost:8000`）
- OpenClaw gateway 运行中（`ws://localhost:18789`）
- `openclaw` 命令在 PATH 中
- agent-browser skill 已安装到 `~/.openclaw/skills/agent-browser/`

**运行：**
```bash
bash scripts/test_openclaw_e2e.sh
```

**环境变量（可选）：**
```bash
API_BASE=http://localhost:8000     # FastAPI 地址（默认）
OPENCLAW_TIMEOUT=180               # 单场景超时秒数
OPENCLAW_TIMEOUT_LONG=240          # 多轮交互场景超时
OPENCLAW_TO=+0000000001            # OpenClaw --to 路由参数
```

**测试场景：**

| # | 场景 | 验证点 |
|---|------|--------|
| 1 | Docker 基础 | example.com H1 包含 "Example Domain" |
| 2 | HttpBin 验证 | httpbin.org/get 返回含 "httpbin" |
| 3 | 多轮交互 | 同 session 两次访问，结果含 "Example Domain" + "origin" |
| 4A | 独立 Session UUID | httpbin.org/uuid 返回含 "uuid" |
| 4B | 独立 Session IP | httpbin.org/ip 返回含 "ip" |

**注意：** 场景 4A/4B 顺序执行（非并发），原因是 OpenClaw gateway 不支持同一进程内同时建立两个 agent 连接；FastAPI 层的多 session 隔离通过两次独立调用分别验证。

### 其他脚本

| 脚本 | 描述 | 用途 |
|------|------|------|
| `build-browser-image.sh` | Browser 镜像构建 | 构建独立的 Browser 镜像 |
| `start_api_v2.sh` | 本地 API 启动 | 本地开发模式启动 API |
| `start-distributed.sh` | 分布式启动 | 启动分布式部署 |

## 使用示例

### 一键安装

```bash
# 交互式安装
./scripts/install.sh

# 静默安装（本地模式）
./scripts/install.sh --mode local

# 静默安装（Docker All-in-One）
./scripts/install.sh --mode docker-aio
```

### Docker 部署

```bash
# 构建多架构镜像
./scripts/build-multiarch.sh --registry registry.example.com

# 部署 All-in-One 模式
./scripts/deploy-docker.sh --mode aio

# 部署分布式模式
./scripts/deploy-docker.sh --mode distributed

# 推送镜像到私有 Registry
export REGISTRY_URL=registry.example.com
export REGISTRY_USERNAME=your-username
export REGISTRY_PASSWORD=your-password
./scripts/push-images.sh
```

### Kubernetes 部署

```bash
# 部署 All-in-One 模式
./scripts/deploy-k8s.sh --mode aio --registry registry.example.com

# 部署分布式模式
./scripts/deploy-k8s.sh --mode distributed --registry registry.example.com

# 清理部署
./scripts/deploy-k8s.sh --cleanup
```

## 环境变量

### 通用环境变量

| 变量 | 描述 | 默认值 |
|------|------|--------|
| `REGISTRY_URL` | 镜像仓库 URL | `localhost:5000` |
| `TAG` | 镜像标签 | `latest` |

### Registry 认证

| 变量 | 描述 |
|------|------|
| `REGISTRY_USERNAME` | Registry 用户名 |
| `REGISTRY_PASSWORD` | Registry 密码 |

## 支持的平台

| 平台 | 架构 | 本地 | Docker | K8s |
|------|------|------|--------|-----|
| macOS | arm64 | ✅ | ✅ | ❌ |
| macOS | x64 | ✅ | ✅ | ❌ |
| Linux | x64 | ✅ | ✅ | ✅ |

**注意：** K8s 部署仅支持 linux/amd64 架构。

## 故障排查

### 脚本权限问题

```bash
# 设置所有脚本可执行
chmod +x scripts/*.sh
```

### Docker 构建失败

```bash
# 清理 Docker 缓存
docker builder prune -a

# 重新构建
./scripts/build-multiarch.sh --registry localhost:5000
```

### Kubernetes 部署失败

```bash
# 检查集群连接
kubectl cluster-info

# 查看 Pod 日志
kubectl logs -n agent-browser <pod-name>

# 查看事件
kubectl get events -n agent-browser --sort-by='.lastTimestamp'
```

## 详细文档

- [安装指南](../docs/INSTALL.md)
- [部署文档](../docs/DEPLOYMENT.md)
- [开发指南](../CLAUDE.md)
