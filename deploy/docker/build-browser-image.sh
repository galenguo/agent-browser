#!/bin/bash
# 构建浏览器容器镜像

set -e

echo "🔨 Building browser container image..."

cd "$(dirname "$0")/.."

docker build \
  -f docker/Dockerfile.browser \
  -t stealth-browser-browser:latest \
  ../..

echo "✅ Browser container image built successfully"
echo ""
echo "Image: stealth-browser-browser:latest"
echo ""
echo "Test the image:"
echo "  docker run --rm -p 19222:19222 stealth-browser-browser:latest"
