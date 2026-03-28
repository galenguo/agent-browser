#!/bin/bash

# Kubernetes 部署脚本

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
NAMESPACE="agent-browser"

# 检查 kubectl
check_kubectl() {
    print_info "检查 kubectl..."
    if ! command -v kubectl &> /dev/null; then
        print_error "kubectl 未安装"
        print_info "请安装 kubectl: https://kubernetes.io/docs/tasks/tools/"
        exit 1
    fi
    print_success "kubectl 已安装"

    # 检查集群连接
    if ! kubectl cluster-info &> /dev/null; then
        print_error "无法连接到 Kubernetes 集群"
        print_info "请检查 kubeconfig 配置"
        exit 1
    fi
    print_success "已连接到 Kubernetes 集群"
}

# 创建命名空间
create_namespace() {
    print_info "创建命名空间..."
    kubectl apply -f k8s/namespace.yaml
    print_success "命名空间创建完成"
}

# 创建 Secret
create_secret() {
    print_info "创建 Secret..."

    if [[ ! -f k8s/secret.yaml ]]; then
        if [[ -f k8s/secret.yaml.example ]]; then
            print_warning "secret.yaml 不存在"
            print_info "请复制 secret.yaml.example 并填写实际值:"
            print_info "  cp k8s/secret.yaml.example k8s/secret.yaml"
            print_info "  # 编辑 k8s/secret.yaml 填写 API keys"
            exit 1
        else
            print_error "secret.yaml.example 不存在"
            exit 1
        fi
    fi

    kubectl apply -f k8s/secret.yaml
    print_success "Secret 创建完成"
}

# 应用配置
apply_config() {
    print_info "应用配置..."

    # ConfigMap
    kubectl apply -f k8s/configmap.yaml
    print_success "ConfigMap 已应用"

    # PVC
    kubectl apply -f k8s/pvc.yaml
    print_success "PVC 已应用"
}

# 替换镜像 URL
replace_registry() {
    print_info "替换镜像 URL..."

    for file in k8s/*-deployment.yaml; do
        if [[ -f "$file" ]]; then
            sed -i.bak "s|\${REGISTRY_URL}|${REGISTRY_URL}|g" "$file"
        fi
    done

    print_success "镜像 URL 替换完成"
}

# 恢复原始文件
restore_files() {
    for file in k8s/*.bak; do
        if [[ -f "$file" ]]; then
            mv "$file" "${file%.bak}"
        fi
    done
}

# 部署 All-in-One 模式
deploy_aio() {
    print_info "部署 All-in-One 模式..."

    kubectl apply -f k8s/aio-deployment.yaml
    kubectl apply -f k8s/aio-service.yaml

    print_success "All-in-One 模式部署完成"
}

# 部署分布式模式
deploy_distributed() {
    print_info "部署分布式模式..."

    kubectl apply -f k8s/api-deployment.yaml
    kubectl apply -f k8s/api-service.yaml
    kubectl apply -f k8s/browser-deployment.yaml
    kubectl apply -f k8s/browser-service.yaml

    print_success "分布式模式部署完成"
}

# 等待 Pod 就绪
wait_for_pods() {
    print_info "等待 Pod 就绪..."

    kubectl wait --for=condition=ready pod \
        -l app=agent-browser \
        -n $NAMESPACE \
        --timeout=300s

    print_success "所有 Pod 已就绪"
}

# 获取 K8s 服务的可访问地址
get_service_url() {
    local svc_name=$1
    local port=$2
    local svc_type

    svc_type=$(kubectl get svc "$svc_name" -n "$NAMESPACE" -o jsonpath='{.spec.type}' 2>/dev/null)

    case "$svc_type" in
        LoadBalancer)
            # 等待 External IP 分配（最多 60 秒）
            print_info "等待 LoadBalancer IP 分配..."
            local ext_ip=""
            local retries=0
            while [[ -z "$ext_ip" && $retries -lt 30 ]]; do
                ext_ip=$(kubectl get svc "$svc_name" -n "$NAMESPACE" \
                    -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null)
                # 有些云厂商返回 hostname 而非 ip
                if [[ -z "$ext_ip" ]]; then
                    ext_ip=$(kubectl get svc "$svc_name" -n "$NAMESPACE" \
                        -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null)
                fi
                [[ -z "$ext_ip" ]] && sleep 2 && retries=$((retries+1))
            done
            if [[ -n "$ext_ip" ]]; then
                echo "http://${ext_ip}:${port}"
            else
                print_warning "LoadBalancer IP 未分配，请稍后运行: kubectl get svc $svc_name -n $NAMESPACE"
                echo ""
            fi
            ;;
        NodePort)
            local node_port
            node_port=$(kubectl get svc "$svc_name" -n "$NAMESPACE" \
                -o jsonpath='{.spec.ports[?(@.port=='"$port"')].nodePort}' 2>/dev/null)

            # 优先取 ExternalIP，其次 InternalIP
            local node_ip
            node_ip=$(kubectl get nodes \
                -o jsonpath='{.items[0].status.addresses[?(@.type=="ExternalIP")].address}' 2>/dev/null)
            if [[ -z "$node_ip" ]]; then
                node_ip=$(kubectl get nodes \
                    -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}' 2>/dev/null)
            fi

            echo "http://${node_ip}:${node_port}"
            ;;
        ClusterIP)
            # ClusterIP 只能集群内访问，提示用户 port-forward
            echo "CLUSTER_ONLY:${port}"
            ;;
        *)
            echo ""
            ;;
    esac
}

# 显示状态
show_status() {
    echo ""
    print_info "部署状态:"
    kubectl get pods -n $NAMESPACE
    echo ""
    kubectl get svc -n $NAMESPACE
    echo ""

    # 获取实际访问地址
    local svc_name
    if [[ "$MODE" == "aio" ]]; then
        svc_name="agent-browser-aio"
    else
        svc_name="agent-browser-api"
    fi

    local api_url
    api_url=$(get_service_url "$svc_name" 8000)

    print_info "访问地址:"
    if [[ "$api_url" == CLUSTER_ONLY:* ]]; then
        local cluster_port="${api_url#CLUSTER_ONLY:}"
        print_warning "Service 类型为 ClusterIP，仅集群内可访问"
        print_info "使用 port-forward 在本地访问:"
        echo "  kubectl port-forward svc/${svc_name} ${cluster_port}:${cluster_port} -n ${NAMESPACE}"
        echo "  然后访问: http://localhost:${cluster_port}"
    elif [[ -n "$api_url" ]]; then
        echo "  - API:    ${api_url}"
        echo "  - Health: ${api_url}/health"
    fi
}

# 清理部署
cleanup() {
    print_warning "清理部署..."

    if [[ "$MODE" == "aio" ]]; then
        kubectl delete -f k8s/aio-deployment.yaml --ignore-not-found=true
        kubectl delete -f k8s/aio-service.yaml --ignore-not-found=true
    else
        kubectl delete -f k8s/api-deployment.yaml --ignore-not-found=true
        kubectl delete -f k8s/api-service.yaml --ignore-not-found=true
        kubectl delete -f k8s/browser-deployment.yaml --ignore-not-found=true
        kubectl delete -f k8s/browser-service.yaml --ignore-not-found=true
    fi

    print_success "清理完成"
}

# 主函数
main() {
    echo ""
    print_info "Agent Browser Kubernetes 部署"
    echo ""

    # 检查 kubectl
    check_kubectl

    # 创建命名空间
    create_namespace

    # 创建 Secret
    create_secret

    # 应用配置
    apply_config

    # 替换镜像 URL
    replace_registry

    # 部署
    print_info "开始部署 $MODE 模式..."
    if [[ "$MODE" == "aio" ]]; then
        deploy_aio
    else
        deploy_distributed
    fi

    # 恢复原始文件
    restore_files

    # 等待 Pod 就绪
    wait_for_pods

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
        --namespace)
            NAMESPACE="$2"
            shift 2
            ;;
        --cleanup)
            cleanup
            exit 0
            ;;
        --help)
            echo "用法: $0 [选项]"
            echo ""
            echo "选项:"
            echo "  --mode <mode>        部署模式: aio, distributed (默认: aio)"
            echo "  --registry <url>     Registry URL (默认: localhost:5000)"
            echo "  --namespace <ns>     Kubernetes 命名空间 (默认: agent-browser)"
            echo "  --cleanup            清理部署"
            echo "  --help               显示帮助信息"
            exit 0
            ;;
        *)
            print_error "未知参数: $1"
            exit 1
            ;;
    esac
done

# 验证模式
if [[ "$MODE" != "aio" && "$MODE" != "distributed" ]]; then
    print_error "无效的部署模式: $MODE"
    print_info "支持的模式: aio, distributed"
    exit 1
fi

# 运行主函数
main
