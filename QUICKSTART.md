# Agent Browser - Quick Start

## 模式 1：本地开发

```python
from agent_browser import create_session, open_page, snapshot, click

# 创建会话
session_id = await create_session()

# 打开页面
await open_page(session_id, "https://example.com")

# 获取快照
snap = await snapshot(session_id, interactive_only=True)
print(snap["elements"])  # [@e1, @e2, ...]

# 点击元素
await click(session_id, "@e1")
```

## 模式 2：远程浏览器

```python
# 连接远程 Docker 浏览器
session_id = await create_session("ws://remote-host:19222")
```

## 模式 3：API 网关

```bash
# 启动 API
cd src && uvicorn api:app --host 0.0.0.0 --port 8000

# REST API (JSON)
curl -X POST http://localhost:8000/sessions/create \
  -H "Content-Type: application/json" \
  -d '{"user_id": "my-user"}'
```

## 部署

```bash
# Docker
docker-compose up

# K8s
kubectl apply -f k8s/
```
