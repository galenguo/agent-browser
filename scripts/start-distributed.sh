#!/bin/bash
# 启动 Distributed 模式

set -e

echo "🚀 Starting Distributed mode..."
echo ""
echo "This will start:"
echo "  - API server container (manages sessions)"
echo "  - Browser containers (created dynamically)"
echo ""

cd "$(dirname "$0")/../docker"

# 检查浏览器镜像是否存在
if ! docker images | grep -q "agent-browser-browser"; then
    echo "⚠️  Browser image not found. Building..."
    ../scripts/build-browser-image.sh
fi

# 创建 Docker 网络（如果不存在）
if ! docker network ls | grep -q "agent-browser-network"; then
    echo "📡 Creating Docker network..."
    docker network create agent-browser-network
fi

# 启动 API 服务器
echo "🚀 Starting API server..."
docker-compose --profile distributed up -d

echo ""
echo "✅ Distributed mode started"
echo ""
echo "API server: http://localhost:8000"
echo "Health check: curl http://localhost:8000/health"
echo ""
echo "Browser containers will be created automatically when sessions are created."
echo ""
echo "View logs:"
echo "  docker logs -f agent-browser-api"
echo ""
echo "Stop:"
echo "  docker-compose --profile distributed down"
