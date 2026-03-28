#!/bin/bash
set -e

# 多架构 Docker 镜像构建脚本
# 支持: linux/amd64 (x86_64), linux/arm64 (Apple Silicon)

PLATFORMS="linux/amd64,linux/arm64"
REGISTRY="${DOCKER_REGISTRY:-}"
VERSION="${VERSION:-latest}"

echo "🔨 Building multi-architecture Docker images..."
echo "📦 Platforms: $PLATFORMS"
echo "🏷️  Version: $VERSION"

# 创建并使用 buildx builder
if ! docker buildx inspect multiarch-builder > /dev/null 2>&1; then
    echo "📐 Creating buildx builder..."
    docker buildx create --name multiarch-builder --use
else
    echo "📐 Using existing buildx builder..."
    docker buildx use multiarch-builder
fi

# 构建函数
build_image() {
    local dockerfile=$1
    local image_name=$2
    local context=${3:-.}

    echo ""
    echo "🚀 Building $image_name..."

    if [ -n "$REGISTRY" ]; then
        full_name="$REGISTRY/$image_name:$VERSION"
    else
        full_name="$image_name:$VERSION"
    fi

    docker buildx build \
        --platform "$PLATFORMS" \
        --file "$dockerfile" \
        --tag "$full_name" \
        --load \
        "$context"

    echo "✅ Built $full_name"
}

# 构建所有镜像
echo ""
echo "=== CloakBrowser 镜像 ==="
build_image "docker/Dockerfile" "agent-browser-aio" ".."
build_image "docker/Dockerfile.api" "agent-browser-api" ".."
build_image "docker/Dockerfile.browser" "agent-browser-browser" ".."

echo ""
echo "🎉 All images built successfully!"
echo ""
echo "📋 Built images:"
docker images | grep agent-browser
