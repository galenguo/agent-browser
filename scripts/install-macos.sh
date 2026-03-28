#!/bin/bash

# macOS 安装脚本

# 安装 Homebrew（如果未安装）
install_homebrew() {
    if ! command -v brew &> /dev/null; then
        print_info "安装 Homebrew..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        print_success "Homebrew 安装完成"
    else
        print_success "Homebrew 已安装"
    fi
}

# 安装 Python
install_python_macos() {
    if [[ "$INSTALL_PYTHON" == "true" ]]; then
        print_info "安装 Python 3.11..."
        brew install python@3.11
        print_success "Python 安装完成"
    fi
}

# 安装 Docker
install_docker_macos() {
    if [[ "$INSTALL_DOCKER" == "true" ]]; then
        print_info "安装 Docker Desktop..."
        brew install --cask docker
        print_warning "请手动启动 Docker Desktop 应用"
        print_info "等待 Docker 启动..."
        while ! docker info &> /dev/null; do
            sleep 2
        done
        print_success "Docker 已启动"
    fi
}

# 安装 Python 依赖
install_python_deps_macos() {
    print_info "安装 Python 依赖..."
    python3 -m pip install --upgrade pip
    python3 -m pip install -r requirements.txt
    print_success "Python 依赖安装完成"
}

# macOS 本地部署
deploy_local_macos() {
    print_info "配置本地开发环境..."

    # 安装 Python 依赖
    install_python_deps_macos

    # 创建数据目录
    mkdir -p /data/profiles /data/logs
    print_success "数据目录创建完成"

    # 启动 API
    print_info "启动 API 服务..."
    python3 -m uvicorn src.api:app --reload --port 8000 &
    API_PID=$!
    print_success "API 服务已启动 (PID: $API_PID)"

    # 保存 PID
    echo $API_PID > .api.pid
}

# macOS 安装主函数
install_macos() {
    print_info "开始 macOS 安装..."

    # 安装 Homebrew
    install_homebrew

    # 安装 Python
    install_python_macos

    # 安装 Docker（如果需要）
    if [[ "$DEPLOY_MODE" == "docker-aio" || "$DEPLOY_MODE" == "docker-distributed" ]]; then
        install_docker_macos
    fi

    print_success "macOS 依赖安装完成"
}
