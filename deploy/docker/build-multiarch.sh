#!/bin/bash

# Docker 多架构镜像构建脚本

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_info() { echo -e "${BLUE}ℹ️  $1${NC}"; }
print_success() { echo -e "${GREEN}✅ $1${NC}"; }
print_warning() { echo -e "${YELLOW}⚠️  $1${NC}"; }
print_error() { echo -e "${RED}❌ $1${NC}"; }

# 配置
PLATFORMS="linux/amd64,darwin/arm64"
BROWSER_PLATFORM="linux/amd64"  # Browser 仅支持 linux/amd64
REGISTRY_URL=${REGISTRY_URL:-"localhost:5000"}
TAG=${TAG:-"latest"}

# 检查 Docker buildx
check_buildx() {
    print_info "检查 Docker buildx..."
    if ! docker buildx version &> /dev/null; then
        print_error "Docker buildx 未安装"
        print_info "请升级 Docker 到最新版本"
        exit 1
    fi
    print_success "Docker buildx 已安装"
}

# 创建 builder
create_builder() {
    print_info "创建 multiarch builder..."
    if docker buildx inspect multiarch-builder &> /dev/null; then
        print_info "Builder 已存在，使用现有 builder"
        docker buildx use multiarch-builder
    else
        docker buildx create --name multiarch-builder --use
        print_success "Builder 创建完成"
    fi
}

# 构建 All-in-One 镜像
build_aio() {
    print_info "构建 All-in-One 镜像..."
    print_info "平台: $PLATFORMS"
    print_info "镜像: ${REGISTRY_URL}/stealth-browser:${TAG}"

    docker buildx build \
        --platform $PLATFORMS \
        -t ${REGISTRY_URL}/stealth-browser:${TAG} \
        -f docker/Dockerfile \
        --push \
        .

    print_success "All-in-One 镜像构建完成"
}

# 构建 API 镜像
build_api() {
    print_info "构建 API 镜像..."
    print_info "平台: $PLATFORMS"
    print_info "镜像: ${REGISTRY_URL}/stealth-browser-api:${TAG}"

    docker buildx build \
        --platform $PLATFORMS \
        -t ${REGISTRY_URL}/stealth-browser-api:${TAG} \
        -f docker/Dockerfile.api \
        --push \
        .

    print_success "API 镜像构建完成"
}

# 构建 Browser 镜像
build_browser() {
    print_info "构建 Browser 镜像..."
    print_info "平台: $BROWSER_PLATFORM (仅 linux/amd64)"
    print_info "镜像: ${REGISTRY_URL}/stealth-browser-browser:${TAG}"

    docker buildx build \
        --platform $BROWSER_PLATFORM \
        -t ${REGISTRY_URL}/stealth-browser-browser:${TAG} \
        -f docker/Dockerfile.browser \
        --push \
        .

    print_success "Browser 镜像构建完成"
}

# 验证镜像
verify_images() {
    print_info "验证镜像..."

    for image in "stealth-browser" "stealth-browser-api" "stealth-browser-browser"; do
        print_info "检查 ${REGISTRY_URL}/${image}:${TAG}"
        if docker manifest inspect ${REGISTRY_URL}/${image}:${TAG} &> /dev/null; then
            print_success "${image} 镜像验证成功"
        else
            print_warning "${image} 镜像验证失败（可能未推送到 registry）"
        fi
    done
}

# 主函数
main() {
    echo ""
    print_info "Stealth Browser 多架构镜像构建"
    echo ""

    # 检查环境
    check_buildx

    # 创建 builder
    create_builder

    # 构建镜像
    print_info "开始构建镜像..."
    build_aio
    build_api
    build_browser

    # 验证镜像
    verify_images

    echo ""
    print_success "所有镜像构建完成！"
    echo ""
    print_info "镜像列表:"
    echo "  - ${REGISTRY_URL}/stealth-browser:${TAG}"
    echo "  - ${REGISTRY_URL}/stealth-browser-api:${TAG}"
    echo "  - ${REGISTRY_URL}/stealth-browser-browser:${TAG}"
    echo ""
}

# 解析命令行参数
while [[ $# -gt 0 ]]; do
    case $1 in
        --registry)
            REGISTRY_URL="$2"
            shift 2
            ;;
        --tag)
            TAG="$2"
            shift 2
            ;;
        --help)
            echo "用法: $0 [选项]"
            echo ""
            echo "选项:"
            echo "  --registry <url>  Registry URL (默认: localhost:5000)"
            echo "  --tag <tag>       镜像标签 (默认: latest)"
            echo "  --help            显示帮助信息"
            echo ""
            echo "环境变量:"
            echo "  REGISTRY_URL      Registry URL"
            echo "  TAG               镜像标签"
            exit 0
            ;;
        *)
            print_error "未知参数: $1"
            exit 1
            ;;
    esac
done

# 运行主函数
main
