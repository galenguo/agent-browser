#!/bin/bash
set -e

# 本地单架构构建脚本
# 用法: cd agent-browser && bash docker/build-local.sh [all|aio|distributed]

# 自动切换到项目根目录（docker/ 的父目录）
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"
echo "📂 Project root: $PROJECT_ROOT"

# 检测架构
PLATFORM=$(uname -m)
if [ "$PLATFORM" = "arm64" ] || [ "$PLATFORM" = "aarch64" ]; then
    DOCKER_PLATFORM="linux/arm64"
    echo "🍎 Detected ARM64 (Apple Silicon)"
elif [ "$PLATFORM" = "x86_64" ]; then
    DOCKER_PLATFORM="linux/amd64"
    echo "🐧 Detected x86_64"
else
    echo "❌ Unsupported platform: $PLATFORM"
    exit 1
fi

VERSION="${VERSION:-latest}"
echo "🏷️  Version: $VERSION"
echo "📦 Platform: $DOCKER_PLATFORM"

# 构建函数
build_image() {
    local dockerfile=$1
    local image_name=$2

    echo ""
    echo "🚀 Building $image_name from $dockerfile ..."

    docker build \
        --platform "$DOCKER_PLATFORM" \
        --file "$dockerfile" \
        --tag "$image_name:$VERSION" \
        .

    echo "✅ Built $image_name:$VERSION"
}

# 解析命令行参数
TARGET="${1:-all}"

case "$TARGET" in
    all)
        echo ""
        echo "=== Building all images ==="
        build_image "docker/Dockerfile" "agent-browser-aio"
        build_image "docker/Dockerfile.api" "agent-browser-api"
        build_image "docker/Dockerfile.browser" "agent-browser-browser"
        ;;
    aio)
        build_image "docker/Dockerfile" "agent-browser-aio"
        ;;
    distributed)
        build_image "docker/Dockerfile.api" "agent-browser-api"
        build_image "docker/Dockerfile.browser" "agent-browser-browser"
        ;;
    *)
        echo "❌ Unknown target: $TARGET"
        echo ""
        echo "Usage: $0 [all|aio|distributed]"
        echo "  all            - Build all images (default)"
        echo "  aio            - Build All-in-One (CloakBrowser)"
        echo "  distributed    - Build API + Browser containers"
        exit 1
        ;;
esac

echo ""
echo "🎉 Build completed!"
docker images | grep -E "agent-browser|REPOSITORY" | head -10
