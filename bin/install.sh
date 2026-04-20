#!/bin/bash

# Stealth Browser 一键安装脚本
# 支持 macOS 和 Linux 系统

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 打印函数
print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

# 检测操作系统和架构
detect_os_arch() {
    OS=$(uname -s | tr '[:upper:]' '[:lower:]')
    ARCH=$(uname -m)

    print_info "检测到系统: $OS"
    print_info "检测到架构: $ARCH"

    if [[ "$OS" != "darwin" && "$OS" != "linux" ]]; then
        print_error "不支持的操作系统: $OS"
        exit 1
    fi

    if [[ "$ARCH" == "x86_64" ]]; then
        ARCH="amd64"
    elif [[ "$ARCH" == "aarch64" ]]; then
        ARCH="arm64"
    fi
}

# 检查依赖
check_dependencies() {
    print_info "检查依赖..."

    # 检查 Python
    if command -v python3 &> /dev/null; then
        PYTHON_VERSION=$(python3 --version | awk '{print $2}')
        print_success "Python 已安装: $PYTHON_VERSION"
    else
        print_warning "Python 未安装"
        INSTALL_PYTHON=true
    fi

    # 检查 Docker（如果需要）
    if [[ "$DEPLOY_MODE" == "docker-aio" || "$DEPLOY_MODE" == "docker-distributed" ]]; then
        if command -v docker &> /dev/null; then
            print_success "Docker 已安装"
        else
            print_warning "Docker 未安装"
            INSTALL_DOCKER=true
        fi
    fi
}

# 显示菜单
show_menu() {
    echo ""
    echo "========================================="
    echo "  Stealth Browser 一键安装"
    echo "========================================="
    echo ""
    echo "请选择部署模式："
    echo "  1) local - 本地开发模式"
    echo "  2) docker-aio - Docker 单容器模式"
    echo "  3) docker-distributed - Docker 分布式模式"
    echo "  4) 退出"
    echo ""
    read -p "请选择 [1-4]: " choice

    case $choice in
        1) DEPLOY_MODE="local" ;;
        2) DEPLOY_MODE="docker-aio" ;;
        3) DEPLOY_MODE="docker-distributed" ;;
        4) exit 0 ;;
        *) print_error "无效选择"; exit 1 ;;
    esac

    print_info "选择的部署模式: $DEPLOY_MODE"
}

# 配置环境
setup_environment() {
    print_info "配置环境变量..."

    if [[ ! -f .env ]]; then
        if [[ -f .env.example ]]; then
            cp .env.example .env
            print_success "已创建 .env 文件"
        else
            print_warning ".env.example 不存在，跳过"
        fi
    else
        print_info ".env 文件已存在"
    fi
}

# 主函数
main() {
    echo ""
    print_info "Stealth Browser 一键安装脚本"
    echo ""

    # 检测系统
    detect_os_arch

    # 显示菜单
    if [[ -z "$DEPLOY_MODE" ]]; then
        show_menu
    fi

    # 检查依赖
    check_dependencies

    # 调用平台特定脚本
    if [[ "$OS" == "darwin" ]]; then
        print_info "调用 macOS 安装脚本..."
        source scripts/install-macos.sh
        install_macos
    elif [[ "$OS" == "linux" ]]; then
        print_info "调用 Linux 安装脚本..."
        source scripts/install-linux.sh
        install_linux
    fi

    # 配置环境
    setup_environment

    # 执行部署
    print_info "开始部署..."
    case $DEPLOY_MODE in
        local)
            print_info "本地模式部署"
            if [[ "$OS" == "darwin" ]]; then
                deploy_local_macos
            else
                deploy_local_linux
            fi
            ;;
        docker-aio)
            print_info "Docker All-in-One 模式部署"
            ./scripts/deploy-docker.sh --mode aio
            ;;
        docker-distributed)
            print_info "Docker 分布式模式部署"
            ./scripts/deploy-docker.sh --mode distributed
            ;;
    esac

    echo ""
    print_success "安装完成！"
    echo ""
    print_info "访问 http://localhost:8000/health 检查服务状态"
    echo ""
}

# 解析命令行参数
while [[ $# -gt 0 ]]; do
    case $1 in
        --mode)
            DEPLOY_MODE="$2"
            shift 2
            ;;
        --os)
            OS="$2"
            shift 2
            ;;
        --non-interactive)
            NON_INTERACTIVE=true
            shift
            ;;
        --config)
            CONFIG_PATH="$2"
            shift 2
            ;;
        --help)
            echo "用法: $0 [选项]"
            echo ""
            echo "选项:"
            echo "  --mode <mode>          部署模式: local, docker-aio, docker-distributed"
            echo "  --os <os>              操作系统: macos, linux"
            echo "  --non-interactive      非交互模式：从 config.yaml 读取配置，跳过菜单"
            echo "  --config <path>        指定 config.yaml 路径 (默认: ~/.stealth-browser/config.yaml)"
            echo "  --help                 显示帮助信息"
            exit 0
            ;;
        *)
            print_error "未知参数: $1"
            exit 1
            ;;
    esac
done

# 非交互模式：从 config.yaml 读取部署模式
if [[ "$NON_INTERACTIVE" == "true" ]]; then
    CFG_FILE="${CONFIG_PATH:-$HOME/.stealth-browser/config.yaml}"
    if [[ -f "$CFG_FILE" ]]; then
        # 用 grep+awk 提取 deployment.mode（兼容无 yq 的环境）
        READ_MODE=$(grep -E '^\s*mode:' "$CFG_FILE" | head -1 | awk -F': '{print $2}' | tr -d ' "')
        if [[ -n "$READ_MODE" && "$READ_MODE" != "" ]]; then
            DEPLOY_MODE="$READ_MODE"
            print_info "从 config.yaml 读取部署模式: $DEPLOY_MODE"
        else
            print_warning "config.yaml 中未找到 mode 字段，使用默认: local"
            DEPLOY_MODE="local"
        fi
    else
        print_warning "config.yaml 不存在 ($CFG_FILE)，使用默认: local"
        DEPLOY_MODE="local"
    fi
fi

# 运行主函数
main
