# Agent Browser 安装指南

本文档提供 Agent Browser 在不同平台、不同部署模式下的详细安装指南。

## 目录

- [系统要求](#系统要求)
- [快速开始](#快速开始)
- [本地部署](#本地部署)
- [Docker 部署](#docker-部署)
- [Kubernetes 部署](#kubernetes-部署)
- [故障排查](#故障排查)
- [性能调优](#性能调优)

---

## 系统要求

### 硬件要求

| 部署模式 | CPU | 内存 | 磁盘 |
|---------|-----|------|------|
| 本地开发 | 2 核 | 4GB | 10GB |
| Docker All-in-One | 2 核 | 4GB | 20GB |
| Docker 分布式 | 4 核+ | 8GB+ | 50GB+ |
| Kubernetes | 4 核+ | 16GB+ | 100GB+ |

### 软件要求

**所有平台：**
- Python 3.11+
- Git

**Docker 部署：**
- Docker 20.10+
- Docker Compose 2.0+

**Kubernetes 部署：**
- kubectl 1.24+
- Kubernetes 集群 1.24+
- Helm 3.0+（可选）

---

## 快速开始

### 一键安装（推荐）

```bash
# 克隆仓库
git clone https://github.com/your-org/agent-browser.git
cd agent-browser

# 运行安装脚本
./bin/install.sh
```

安装脚本会：
1. 自动检测操作系统和架构
2. 安装必要的依赖
3. 提供交互式菜单选择部署模式
4. 自动配置环境变量
5. 启动服务

### 手动安装

如果一键安装失败，请参考下面的详细安装步骤。

---

## 本地部署

### macOS

#### 1. 安装依赖

```bash
# 安装 Homebrew（如果未安装）
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 安装 Python 3.11
brew install python@3.11

# 安装 Python 依赖
python3 -m pip install -e ".[dev]"
```

#### 2. 配置环境

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑 .env 文件，填写 API keys
nano .env
```

#### 3. 启动服务

```bash
# 创建数据目录
mkdir -p /data/profiles /data/logs

# 启动 API
python3 -m uvicorn agent_browser.api:app --reload --port 8000
```

#### 4. 验证

```bash
curl http://localhost:8000/health
```

### Linux (Ubuntu/Debian)

#### 1. 安装依赖

```bash
# 更新包列表
sudo apt-get update

# 安装 Python 3.11
sudo apt-get install -y python3.11 python3.11-venv python3-pip

# 安装 Python 依赖
python3 -m pip install -e ".[dev]"
```

#### 2. 配置环境

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑 .env 文件
nano .env
```

#### 3. 启动服务

```bash
# 创建数据目录
sudo mkdir -p /data/profiles /data/logs
sudo chown -R $USER:$USER /data

# 启动 API
python3 -m uvicorn agent_browser.api:app --reload --port 8000
```

### Linux (CentOS/RHEL)

#### 1. 安装依赖

```bash
# 安装 Python 3.11
sudo yum install -y python3.11 python3-pip

# 安装 Python 依赖
python3 -m pip install -e ".[dev]"
```

#### 2-3. 配置和启动

同 Ubuntu/Debian。

---

## Docker 部署

### 前置条件

确保 Docker 已安装并运行：

```bash
docker --version
docker-compose --version
```

### All-in-One 模式（单容器）

适合：单用户、开发测试

#### 1. 构建镜像

```bash
# 使用脚本构建多架构镜像
./deploy/docker/build-multiarch.sh --registry localhost:5000

# 或手动构建
docker build -f deploy/docker/Dockerfile -t agent-browser:latest .
```

#### 2. 配置环境

```bash
# 复制环境变量模板
cp deploy/docker/.env.example deploy/docker/.env

# 编辑 deploy/docker/.env
nano deploy/docker/.env
```

#### 3. 启动服务

```bash
# 使用脚本部署
./deploy/docker/deploy-docker.sh --mode aio

# 或使用 docker-compose
cd deploy/docker
docker-compose --profile all-in-one up -d
```

#### 4. 验证

```bash
# 检查容器状态
docker ps

# 检查健康状态
curl http://localhost:8000/health

# 访问 noVNC（可视化）
open http://localhost:6080
```

### 分布式模式（多容器）

适合：多用户、生产环境

#### 1. 构建镜像

```bash
# 构建 API 和 Browser 镜像
./deploy/docker/build-multiarch.sh --registry localhost:5000
```

#### 2. 配置环境

```bash
cp deploy/docker/.env.example deploy/docker/.env
nano deploy/docker/.env

# 设置部署模式
# DEPLOYMENT_MODE=distributed
```

#### 3. 启动服务

```bash
# 使用脚本部署
./deploy/docker/deploy-docker.sh --mode distributed

# 或使用 docker-compose
cd deploy/docker
docker-compose --profile distributed up -d
```

#### 4. 验证

```bash
docker ps
curl http://localhost:8000/health
```

### 推送镜像到私有 Registry

```bash
# 设置 Registry URL
export REGISTRY_URL=registry.example.com
export REGISTRY_USERNAME=your-username
export REGISTRY_PASSWORD=your-password

# 推送镜像
./deploy/docker/push-images.sh
```

---

## Kubernetes 部署

### 前置条件

1. Kubernetes 集群已就绪
2. kubectl 已配置
3. 镜像已推送到 Registry

### 使用原生 YAML

#### 1. 配置 Secret

```bash
# 复制 Secret 模板
cp deploy/k8s/secret.yaml.example deploy/k8s/secret.yaml

# 编辑 Secret，填写 API keys
nano deploy/k8s/secret.yaml
```

#### 2. 部署 All-in-One 模式

```bash
# 使用脚本部署
./deploy/k8s/deploy-k8s.sh --mode aio --registry registry.example.com

# 或手动部署
kubectl apply -f deploy/k8s/namespace.yaml
kubectl apply -f deploy/k8s/configmap.yaml
kubectl apply -f deploy/k8s/secret.yaml
kubectl apply -f deploy/k8s/pvc.yaml
kubectl apply -f deploy/k8s/aio-deployment.yaml
kubectl apply -f deploy/k8s/aio-service.yaml
```

#### 3. 部署分布式模式

```bash
# 使用脚本部署
./deploy/k8s/deploy-k8s.sh --mode distributed --registry registry.example.com

# 或手动部署
kubectl apply -f deploy/k8s/namespace.yaml
kubectl apply -f deploy/k8s/configmap.yaml
kubectl apply -f deploy/k8s/secret.yaml
kubectl apply -f deploy/k8s/pvc.yaml
kubectl apply -f deploy/k8s/api-deployment.yaml
kubectl apply -f deploy/k8s/api-service.yaml
kubectl apply -f deploy/k8s/browser-deployment.yaml
kubectl apply -f deploy/k8s/browser-service.yaml
```

#### 4. 验证

```bash
# 检查 Pod 状态
kubectl get pods -n agent-browser

# 检查 Service
kubectl get svc -n agent-browser

# 获取访问地址
kubectl get svc agent-browser-aio -n agent-browser

# 测试健康检查
curl http://<node-ip>:<node-port>/health
```

### 使用 Helm Chart

#### 1. 安装 Helm

```bash
# macOS
brew install helm

# Linux
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
```

#### 2. 配置 values

```bash
# 复制 values 文件
cp deploy/helm/agent-browser/values.yaml my-values.yaml

# 编辑配置
nano my-values.yaml
```

#### 3. 安装 Chart

```bash
# All-in-One 模式
helm install agent-browser ./deploy/helm/agent-browser \
  -f deploy/helm/agent-browser/values-aio.yaml \
  --set secrets.anthropicApiKey=your-key \
  --set secrets.openaiApiKey=your-key \
  --set image.registry=registry.example.com \
  --namespace agent-browser \
  --create-namespace

# 分布式模式
helm install agent-browser ./deploy/helm/agent-browser \
  -f deploy/helm/agent-browser/values-distributed.yaml \
  --set secrets.anthropicApiKey=your-key \
  --set secrets.openaiApiKey=your-key \
  --set image.registry=registry.example.com \
  --namespace agent-browser \
  --create-namespace
```

#### 4. 验证

```bash
# 检查 Release
helm list -n agent-browser

# 检查 Pod
kubectl get pods -n agent-browser

# 检查 Service
kubectl get svc -n agent-browser
```

#### 5. 升级

```bash
helm upgrade agent-browser ./deploy/helm/agent-browser \
  -f my-values.yaml \
  --namespace agent-browser
```

#### 6. 卸载

```bash
helm uninstall agent-browser --namespace agent-browser
```

---

## 故障排查

### 常见问题

#### 1. Docker 构建失败

**问题：** `ERROR: failed to solve: process "/bin/sh -c ..." did not complete successfully`

**解决：**
```bash
# 清理 Docker 缓存
docker builder prune -a

# 重新构建
docker build --no-cache -f deploy/docker/Dockerfile -t agent-browser:latest .
```

#### 2. Kubernetes Pod 无法启动

**问题：** `ImagePullBackOff` 或 `ErrImagePull`

**解决：**
```bash
# 检查镜像是否存在
docker manifest inspect registry.example.com/agent-browser:latest

# 检查 imagePullSecrets
kubectl get secret -n agent-browser

# 创建 imagePullSecret
kubectl create secret docker-registry registry-secret \
  --docker-server=registry.example.com \
  --docker-username=your-username \
  --docker-password=your-password \
  -n agent-browser
```

#### 3. 健康检查失败

**问题：** `/health` 端点返回 500 错误

**解决：**
```bash
# 检查日志
kubectl logs -n agent-browser <pod-name>

# 检查环境变量
kubectl exec -n agent-browser <pod-name> -- env

# 检查 Secret
kubectl get secret agent-browser-secret -n agent-browser -o yaml
```

#### 4. 浏览器无法启动

**问题：** CloakBrowser 启动失败

**解决：**
```bash
# 检查共享内存
kubectl exec -n agent-browser <pod-name> -- df -h /dev/shm

# 增加共享内存
# 在 Deployment 中添加：
# volumes:
# - name: shm
#   emptyDir:
#     medium: Memory
#     sizeLimit: 256Mi
```

### 日志查看

**Docker：**
```bash
docker logs agent-browser
docker logs -f agent-browser  # 实时查看
```

**Kubernetes：**
```bash
kubectl logs -n agent-browser <pod-name>
kubectl logs -n agent-browser <pod-name> -f  # 实时查看
kubectl logs -n agent-browser <pod-name> --previous  # 查看上一个容器的日志
```

---

## 性能调优

### 资源限制

#### Docker

编辑 `docker-compose.yml`：

```yaml
services:
  agent-browser:
    deploy:
      resources:
        limits:
          cpus: '4.0'
          memory: 4G
        reservations:
          cpus: '2.0'
          memory: 2G
```

#### Kubernetes

编辑 Deployment 或 Helm values：

```yaml
resources:
  requests:
    memory: "1Gi"
    cpu: "1000m"
  limits:
    memory: "4Gi"
    cpu: "4000m"
```

### 会话配置

编辑 `.env` 或 ConfigMap：

```bash
# 最大并发会话数
MAX_SESSIONS=20

# 空闲超时（秒）
IDLE_TIMEOUT_SECONDS=600

# 日志级别
LOG_LEVEL=WARNING
```

### 存储优化

#### 使用 SSD

```yaml
# Kubernetes PVC
storageClassName: fast-ssd
```

#### 定期清理

```bash
# 清理旧的 profiles
find /data/profiles -mtime +7 -delete

# 清理日志
find /data/logs -mtime +30 -delete
```

### 网络优化

#### 使用代理池

编辑 `.env`：

```bash
PROXY_LIST=http://proxy1:port,http://proxy2:port,http://proxy3:port
```

#### 配置 DNS

```yaml
# Kubernetes Pod
dnsPolicy: ClusterFirst
dnsConfig:
  nameservers:
    - 8.8.8.8
    - 8.8.4.4
```

---

## 下一步

- 阅读 [API 文档](./API_COMPARISON.md)
- 查看 [部署架构](../deploy/README.md)
- 了解 [开发指南](../CLAUDE.md)

---

**最后更新：** 2026-03-23
