#!/bin/bash

# Linux 安装脚本

# 检测 Linux 发行版
detect_distro() {
    if [[ -f /etc/os-release ]]; then
        . /etc/os-release
        DISTRO=$ID
        print_info "检测到 Linux 发行版: $DISTRO"
    else
        print_error "无法检测 Linux 发行版"
        exit 1
    fi
}

# 安装 Python (Ubuntu/Debian)
install_python_debian() {
    print_info "安装 Python 3.11..."
    sudo apt-get update
    sudo apt-get install -y python3.11 python3.11-venv python3-pip
    print_success "Python 安装完成"
}

# 安装 Python (CentOS/RHEL)
install_python_rhel() {
    print_info "安装 Python 3.11..."
    sudo yum install -y python3.11 python3-pip
    print_success "Python 安装完成"
}

# 安装 Docker (Ubuntu/Debian)
install_docker_debian() {
    print_info "安装 Docker..."
    sudo apt-get update
    sudo apt-get install -y ca-certificates curl gnupg
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg

    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
      sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    # 启动 Docker
    sudo systemctl start docker
    sudo systemctl enable docker

    # 添加当前用户到 docker 组
    sudo usermod -aG docker $USER
    print_success "Docker 安装完成"
    print_warning "请重新登录以使 docker 组生效"
}

# 安装 Docker (CentOS/RHEL)
install_docker_rhel() {
    print_info "安装 Docker..."
    sudo yum install -y yum-utils
    sudo yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
    sudo yum install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    # 启动 Docker
    sudo systemctl start docker
    sudo systemctl enable docker

    # 添加当前用户到 docker 组
    sudo usermod -aG docker $USER
    print_success "Docker 安装完成"
    print_warning "请重新登录以使 docker 组生效"
}

# 安装 Python 依赖
install_python_deps_linux() {
    print_info "安装 Python 依赖..."
    python3 -m pip install --upgrade pip
    python3 -m pip install -r requirements.txt
    print_success "Python 依赖安装完成"
}

# Linux 本地部署
deploy_local_linux() {
    print_info "配置本地开发环境..."

    # 安装 Python 依赖
    install_python_deps_linux

    # 创建数据目录
    sudo mkdir -p /data/profiles /data/logs
    sudo chown -R $USER:$USER /data
    print_success "数据目录创建完成"

    # 启动 API
    print_info "启动 API 服务..."
    python3 -m uvicorn src.api:app --reload --port 8000 &
    API_PID=$!
    print_success "API 服务已启动 (PID: $API_PID)"

    # 保存 PID
    echo $API_PID > .api.pid
}

# Linux 安装主函数
install_linux() {
    print_info "开始 Linux 安装..."

    # 检测发行版
    detect_distro

    # 安装 Python
    if [[ "$INSTALL_PYTHON" == "true" ]]; then
        case $DISTRO in
            ubuntu|debian)
                install_python_debian
                ;;
            centos|rhel|fedora)
                install_python_rhel
                ;;
            *)
                print_error "不支持的 Linux 发行版: $DISTRO"
                exit 1
                ;;
        esac
    fi

    # 安装 Docker（如果需要）
    if [[ "$INSTALL_DOCKER" == "true" ]]; then
        case $DISTRO in
            ubuntu|debian)
                install_docker_debian
                ;;
            centos|rhel|fedora)
                install_docker_rhel
                ;;
            *)
                print_error "不支持的 Linux 发行版: $DISTRO"
                exit 1
                ;;
        esac
    fi

    print_success "Linux 依赖安装完成"
}
