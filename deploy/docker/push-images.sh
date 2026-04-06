#!/bin/bash

# 推送镜像到私有 Registry

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
REGISTRY_URL=${REGISTRY_URL:-""}
REGISTRY_USERNAME=${REGISTRY_USERNAME:-""}
REGISTRY_PASSWORD=${REGISTRY_PASSWORD:-""}
TAG=${TAG:-"latest"}

# 检查配置
check_config() {
    if [[ -z "$REGISTRY_URL" ]]; then
        print_error "未设置 REGISTRY_URL"
        print_info "请设置环境变量: export REGISTRY_URL=registry.example.com"
        exit 1
    fi

    print_info "Registry URL: $REGISTRY_URL"
}

# 登录 Registry
login_registry() {
    print_info "登录 Registry..."

    if [[ -n "$REGISTRY_USERNAME" && -n "$REGISTRY_PASSWORD" ]]; then
        echo "$REGISTRY_PASSWORD" | docker login $REGISTRY_URL -u $REGISTRY_USERNAME --password-stdin
        print_success "登录成功"
    else
        print_warning "未设置认证信息，尝试匿名推送"
    fi
}

# 推送镜像
push_images() {
    IMAGES=(
        "agent-browser:${TAG}"
        "agent-browser-api:${TAG}"
        "agent-browser-browser:${TAG}"
    )

    for image in "${IMAGES[@]}"; do
        print_info "推送 ${REGISTRY_URL}/${image}..."
        docker push ${REGISTRY_URL}/${image}
        print_success "${image} 推送完成"
    done
}

# 主函数
main() {
    echo ""
    print_info "推送镜像到私有 Registry"
    echo ""

    # 检查配置
    check_config

    # 登录 Registry
    login_registry

    # 推送镜像
    push_images

    echo ""
    print_success "所有镜像推送完成！"
    echo ""
}

# 解析命令行参数
while [[ $# -gt 0 ]]; do
    case $1 in
        --registry)
            REGISTRY_URL="$2"
            shift 2
            ;;
        --username)
            REGISTRY_USERNAME="$2"
            shift 2
            ;;
        --password)
            REGISTRY_PASSWORD="$2"
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
            echo "  --registry <url>    Registry URL"
            echo "  --username <user>   Registry 用户名"
            echo "  --password <pass>   Registry 密码"
            echo "  --tag <tag>         镜像标签 (默认: latest)"
            echo "  --help              显示帮助信息"
            echo ""
            echo "环境变量:"
            echo "  REGISTRY_URL        Registry URL"
            echo "  REGISTRY_USERNAME   Registry 用户名"
            echo "  REGISTRY_PASSWORD   Registry 密码"
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
