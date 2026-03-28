# Docker 构建指南

## 快速开始

### 本地构建（单架构）

```bash
# 从项目根目录运行
cd agent-browser

# 构建 CloakBrowser All-in-One
bash docker/build-local.sh aio

# 构建分布式模式镜像（API + Browser）
bash docker/build-local.sh distributed

# 构建所有镜像
bash docker/build-local.sh all
```

### 多架构构建（ARM64 + x86_64）

```bash
# 同时构建 ARM64 和 x86_64 镜像
bash docker/build-multiarch.sh
```

## 镜像列表

| 镜像名称 | 大小 | 用途 |
|---------|------|------|
| `agent-browser-aio` | 3.6GB | CloakBrowser All-in-One (API + 浏览器 + VNC) |
| `agent-browser-api` | 773MB | 分布式 API 服务 |
| `agent-browser-browser` | 3.01GB | 分布式浏览器容器 (CloakBrowser) |

## 架构支持

所有镜像支持以下架构：
- **linux/arm64** - Apple Silicon (M1/M2/M3)
- **linux/amd64** - Intel/AMD x86_64

构建脚本会自动检测当前平台架构。

## 构建要求

### 系统依赖
- Docker 20.10+
- 8GB+ 可用磁盘空间
- 稳定的网络连接（下载浏览器二进制）

### 构建时间
- All-in-One 镜像：~15-20 分钟
- 分布式镜像：~10-15 分钟
- 多架构构建：~30-40 分钟

## 故障排除

### 网络超时
如果遇到 pip 或浏览器下载超时：
```bash
# 重新运行构建，已内置重试机制
bash docker/build-local.sh <target>
```

### 磁盘空间不足
```bash
# 清理未使用的镜像
docker system prune -a

# 查看磁盘使用
docker system df
```

## 高级选项

### 自定义版本标签
```bash
VERSION=v1.0.0 bash docker/build-local.sh all
```

### 推送到镜像仓库
```bash
# 设置镜像仓库
DOCKER_REGISTRY=your-registry.com bash docker/build-multiarch.sh

# 推送镜像
docker push your-registry.com/agent-browser-aio:latest
```

## 构建优化

所有 Dockerfile 已优化：
- ✅ 升级 pip/setuptools/wheel 到最新版本
- ✅ 添加编译依赖（gcc, python3-dev）
- ✅ 网络超时重试（--timeout 120 --retries 5）
- ✅ 多阶段缓存优化
- ✅ 最小化镜像层数

## 验证构建

```bash
# 查看构建的镜像
docker images | grep agent-browser

# 测试 All-in-One 镜像
docker run --rm -p 8000:8000 agent-browser-aio:latest

# 访问 API
curl http://localhost:8000/health
```
