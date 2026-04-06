#!/bin/bash

# Docker 部署脚本

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

# 默认配置
MODE="aio"  # aio 或 distributed
REGISTRY_URL=${REGISTRY_URL:-"localhost:5000"}
CONFIG_PATH=""  # config.yaml 路径（--config 参数）


# 从 config.yaml 读取 Docker 配置
load_config_from_yaml() {
    local cfg_file="$1"
    if [[ ! -f "$cfg_file" ]]; then
        return 1
    fi

    # 提取 docker.* 设置（grep+awk 兼容无 yq 的环境）
    local registry image_tag shm_size memory cpu

    registry=$(grep -A5 '^docker:' "$cfg_file" | grep 'registry:' | awk -F": " '{print $2}' | tr -d '" ')
    image_tag=$(grep -A10 '^docker:' "$cfg_file" | grep 'image_tag:' | awk -F": " '{print $2}' | tr -d '" ')
    shm_size=$(grep -A15 '^docker:' "$cfg_file" | grep 'shm_size:' | awk -F": " '{print $2}' | tr -d '" ')
    memory=$(grep -E '^\s*memory:' "$cfg_file" | tail -1 | awk -F": " '{print $2}' | tr -d '" ')
    cpu=$(grep -E '^\s*cpu:' "$cfg_file" | tail -1 | awk -F": " '{print $2}' | tr -d '" ')

    [[ -n "$registry" ]] && REGISTRY_URL="$registry"
    [[ -n "$image_tag" ]] && DOCKER_IMAGE_TAG="$image_tag"
    [[ -n "$shm_size" ]] && DOCKER_SHM_SIZE="$shm_size"
    [[ -n "$memory" ]] && DOCKER_MEMORY="$memory"
    [[ -n "$cpu" ]] && DOCKER_CPU="$cpu"

    print_info "已从 $cfg_file 加载 Docker 配置"
}

# 检查 Docker
check_docker() {
    print_info "检查 Docker..."
    if ! docker info &> /dev/null; then
        print_error "Docker 未运行"
        print_info "请启动 Docker 后重试"
        exit 1
    fi
    print_success "Docker 已运行"
}

# 检查镜像
check_images() {
    print_info "检查镜像..."

    if [[ "$MODE" == "aio" ]]; then
        REQUIRED_IMAGES=("agent-browser:latest")
    else
        REQUIRED_IMAGES=("agent-browser-api:latest" "agent-browser-browser:latest")
    fi

    MISSING_IMAGES=()
    for image in "${REQUIRED_IMAGES[@]}"; do
        if ! docker image inspect ${REGISTRY_URL}/${image} &> /dev/null; then
            MISSING_IMAGES+=("$image")
        fi
    done

    if [[ ${#MISSING_IMAGES[@]} -gt 0 ]]; then
        print_warning "以下镜像不存在:"
        for image in "${MISSING_IMAGES[@]}"; do
            echo "  - ${REGISTRY_URL}/${image}"
        done
        print_info "是否构建镜像? [y/N]"
        read -r response
        if [[ "$response" =~ ^[Yy]$ ]]; then
            ./scripts/build-multiarch.sh --registry $REGISTRY_URL
        else
            print_error "缺少必需的镜像"
            exit 1
        fi
    else
        print_success "所有镜像已就绪"
    fi
}

# 配置环境
setup_env() {
    print_info "配置环境..."

    # 复制 .env 文件
    if [[ ! -f docker/.env ]]; then
        if [[ -f docker/.env.example ]]; then
            cp docker/.env.example docker/.env
            print_success "已创建 docker/.env 文件"
        else
            print_warning "docker/.env.example 不存在"
        fi
    fi

    # 设置部署模式
    if [[ -f docker/.env ]]; then
        sed -i.bak "s/^DEPLOYMENT_MODE=.*/DEPLOYMENT_MODE=${MODE}/" docker/.env
        print_success "部署模式设置为: $MODE"
    fi
}

# 启动服务
start_services() {
    print_info "启动服务..."

    cd docker

    if [[ "$MODE" == "aio" ]]; then
        print_info "启动 All-in-One 模式..."
        docker-compose --profile all-in-one up -d
    else
        print_info "启动分布式模式..."
        docker-compose --profile distributed up -d
    fi

    cd ..

    print_success "服务已启动"
}

# 获取宿主机可访问 IP
get_host_ip() {
    local ip=""

    # 优先使用用户指定的 HOST_IP
    if [[ -n "$HOST_IP" ]]; then
        echo "$HOST_IP"
        return
    fi

    # macOS
    if [[ "$(uname -s)" == "Darwin" ]]; then
        ip=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null)
    else
        # Linux: 优先取默认路由出口 IP
        ip=$(ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") {print $(i+1); exit}}')
        # 兜底：取第一个非 loopback 的 IPv4
        if [[ -z "$ip" ]]; then
            ip=$(hostname -I 2>/dev/null | awk '{print $1}')
        fi
    fi

    echo "${ip:-localhost}"
}

# 等待服务就绪
wait_for_service() {
    print_info "等待服务就绪..."

    MAX_RETRIES=30
    RETRY_COUNT=0

    while [[ $RETRY_COUNT -lt $MAX_RETRIES ]]; do
        if curl -s http://localhost:8000/health &> /dev/null; then
            print_success "服务已就绪"
            return 0
        fi
        RETRY_COUNT=$((RETRY_COUNT + 1))
        sleep 2
    done

    print_error "服务启动超时"
    return 1
}

# 显示状态
show_status() {
    local host_ip
    host_ip=$(get_host_ip)

    print_info "服务状态:"
    docker ps --filter "name=agent-browser"

    echo ""
    print_info "访问地址:"
    echo "  - API:    http://${host_ip}:8000"
    echo "  - Health: http://${host_ip}:8000/health"
    if [[ "$MODE" == "aio" ]]; then
        echo "  - noVNC:  http://${host_ip}:6080"
    fi

    if [[ "$host_ip" == "localhost" || "$host_ip" == "127.0.0.1" ]]; then
        print_warning "未能检测到外部 IP，如需远程访问请设置: export HOST_IP=<your-server-ip>"
    fi
}

# 主函数
main() {
    echo ""
    print_info "Agent Browser Docker 部署"
    echo ""

    # 检查 Docker
    check_docker

    # 检查镜像
    check_images

    # 配置环境
    setup_env

    # 启动服务
    start_services

    # 等待服务就绪
    wait_for_service

    # 显示状态
    show_status

    echo ""
    print_success "部署完成！"
    echo ""
}

# 解析命令行参数
while [[ $# -gt 0 ]]; do
    case $1 in
        --mode)
            MODE="$2"
            shift 2
            ;;
        --registry)
            REGISTRY_URL="$2"
            shift 2
            ;;
        --config)
            CONFIG_PATH="$2"
            shift 2
            ;;
        --validate)
            # 验证 config.yaml 中 Docker 相关字段是否存在
            CFG="${CONFIG_PATH:-$HOME/.agent-browser/config.yaml}"
            if [[ -f "$CFG" ]]; then
                print_info "验证配置文件: $CFG"
                for key in docker registry image_tag; do
                    if grep -q "$key:" "$CFG"; then
                        print_success "  $key: 存在"
                    else
                        print_warning "  $key: 缺失（将使用默认值）"
                    fi
                done
                exit 0
            else
                print_error "配置文件不存在: $CFG"
                exit 1
            fi
            ;;
        --help)
            echo "用法: $0 [选项]"
            echo ""
            echo "选项:"
            echo "  --mode <mode>      部署模式: aio, distributed (默认: aio)"
            echo "  --registry <url>   Registry URL (默认: localhost:5000)"
            echo "  --config <path>   从 config.yaml 读取 Docker 配置"
            echo "  --validate         验证 config.yaml 中 Docker 字段完整性"
            echo "  --help             显示帮助信息"
            exit 0
            ;;
        *)
            print_error "未知参数: $1"
            exit 1
            ;;
    esac
done

# 如果指定了 --config，加载配置
if [[ -n "$CONFIG_PATH" ]]; then
    load_config_from_yaml "$CONFIG_PATH"
fi

# 验证模式
if [[ "$MODE" != "aio" && "$MODE" != "distributed" ]]; then
    print_error "无效的部署模式: $MODE"
    print_info "支持的模式: aio, distributed"
    exit 1
fi

# 运行主函数
main
