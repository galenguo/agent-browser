#!/bin/bash
# 构建浏览器容器镜像

set -e

echo "🔨 Building browser container image..."

cd "$(dirname "$0")/.."

docker build \
  -f docker/Dockerfile.browser \
  -t agent-browser-browser:latest \
  ../..

echo "✅ Browser container image built successfully"
echo ""
echo "Image: agent-browser-browser:latest"
echo ""
echo "Test the image:"
echo "  docker run --rm -p 19222:19222 agent-browser-browser:latest"
