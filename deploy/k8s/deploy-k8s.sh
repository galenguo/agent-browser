#!/bin/bash
# deploy/k8s/deploy-k8s.sh
#
# Kubernetes deployment script — supports two modes:
#
#   aio          All-in-one: single pod runs API + browser (Xvfb + CloakBrowser + noVNC)
#                Uses: k8s/aio-deployment.yaml + k8s/aio-service.yaml
#
#   distributed  Distributed: 1 CP pod manages N BR pods dynamically via k8s API.
#                CP pod creates/deletes BR pods on demand; warm pool of 3 idle BR pods.
#                Uses: k8s/distributed/ directory (RBAC, ConfigMap, StatefulSet, Services)
#
# Usage:
#   ./deploy-k8s.sh --mode aio [--registry <url>] [--namespace <ns>]
#   ./deploy-k8s.sh --mode distributed [--image <image>] [--namespace <ns>]
#   ./deploy-k8s.sh --mode aio --cleanup
#   ./deploy-k8s.sh --mode distributed --cleanup

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Colors ────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]  $*${NC}"; }
success() { echo -e "${GREEN}[OK]    $*${NC}"; }
warn()    { echo -e "${YELLOW}[WARN]  $*${NC}"; }
error()   { echo -e "${RED}[ERROR] $*${NC}"; exit 1; }

# ── Defaults ──────────────────────────────────────────────────────────
MODE="aio"
REGISTRY_URL="${REGISTRY_URL:-localhost:5000}"
# Distributed mode: full image reference (overrides REGISTRY_URL for distributed)
IMAGE="${IMAGE:-registry-cn-gimc-local.gimccloud.com/library/stealth-browser:latest}"
NAMESPACE="stealth-browser"
CLEANUP=false

# ── Prereq checks ─────────────────────────────────────────────────────

check_kubectl() {
    if ! command -v kubectl &>/dev/null; then
        error "kubectl not found. Install: https://kubernetes.io/docs/tasks/tools/"
    fi
    if ! kubectl cluster-info &>/dev/null; then
        error "Cannot reach Kubernetes cluster. Check your kubeconfig."
    fi
    success "kubectl connected to cluster"
}

# ── All-in-One mode ───────────────────────────────────────────────────

deploy_aio() {
    info "=== Deploying All-in-One mode ==="
    info "Namespace : $NAMESPACE"
    info "Registry  : $REGISTRY_URL"
    echo ""

    # Namespace + Secret + ConfigMap + PVC
    kubectl apply -f "$SCRIPT_DIR/namespace.yaml"

    _require_secret

    kubectl apply -f "$SCRIPT_DIR/configmap.yaml"
    kubectl apply -f "$SCRIPT_DIR/pvc.yaml"

    # Substitute registry URL in deployment manifest
    sed "s|\${REGISTRY_URL}|${REGISTRY_URL}|g" \
        "$SCRIPT_DIR/aio-deployment.yaml" | kubectl apply -f -

    kubectl apply -f "$SCRIPT_DIR/aio-service.yaml"

    info "Waiting for pod to be ready..."
    kubectl rollout status deployment/stealth-browser-aio \
        -n "$NAMESPACE" --timeout=180s

    echo ""
    _show_aio_status
    success "=== All-in-One deployment complete ==="
}

cleanup_aio() {
    warn "Deleting All-in-One deployment..."
    kubectl delete deployment stealth-browser-aio -n "$NAMESPACE" --ignore-not-found=true
    kubectl delete -f "$SCRIPT_DIR/aio-service.yaml" --ignore-not-found=true
    success "All-in-One resources removed"
}

_show_aio_status() {
    kubectl get pods -n "$NAMESPACE" -l "app=stealth-browser,mode=all-in-one" 2>/dev/null || true
    echo ""
    local url
    url=$(_get_service_url "stealth-browser-aio" 8000)
    if [[ -n "$url" ]]; then
        info "API    : $url"
        info "Health : $url/health"
    fi
}

# ── Distributed mode ──────────────────────────────────────────────────
#
# Architecture:
#   - 1 CP pod (stealth-browser-cp-0): runs FastAPI, manages BR pod lifecycle via k8s API
#   - N BR pods (stealth-browser-br-{uuid8}): each runs Xvfb + CloakBrowser + noVNC + node_api
#   - Warm pool: CP maintains 3 idle BR pods at all times
#   - On session create: CP picks idle BR pod → calls /browser/start → returns cdp_url (pod IP)
#   - On session delete: CP calls /browser/stop → deletes BR pod + PVC
#   - BR pod DNS: {pod_name}.stealth-browser-br-headless.{namespace}.svc.cluster.local
#     (requires hostname + subdomain set in pod spec — handled by K8sBrowserNodeManager)
#   - CDP access: via pod IP (Chrome rejects non-IP Host headers on CDP port)
#   - VNC routing: token → session → pod_name → headless DNS :6080 (proxied by CP FastAPI)

deploy_distributed() {
    info "=== Deploying Distributed mode ==="
    info "Namespace : $NAMESPACE"
    info "Image     : $IMAGE"
    echo ""

    # Delegate to the distributed-specific deploy script
    IMAGE="$IMAGE" NAMESPACE="$NAMESPACE" \
        bash "$SCRIPT_DIR/distributed/deploy.sh" deploy
}

cleanup_distributed() {
    IMAGE="$IMAGE" NAMESPACE="$NAMESPACE" \
        bash "$SCRIPT_DIR/distributed/deploy.sh" teardown
}

# ── Shared helpers ────────────────────────────────────────────────────

_require_secret() {
    local secret_file="$SCRIPT_DIR/secret.yaml"
    if kubectl get secret stealth-browser-secret -n "$NAMESPACE" &>/dev/null; then
        success "Secret 'stealth-browser-secret' exists"
        return
    fi
    if [[ ! -f "$secret_file" ]]; then
        if [[ -f "${secret_file}.example" ]]; then
            warn "secret.yaml not found. Copy and fill in credentials:"
            warn "  cp $secret_file.example $secret_file"
            warn "  # edit $secret_file with real API keys"
        fi
        error "Secret missing — cannot deploy"
    fi
    kubectl apply -f "$secret_file"
    success "Secret applied"
}

_get_service_url() {
    local svc_name="$1" port="$2"
    local svc_type
    svc_type=$(kubectl get svc "$svc_name" -n "$NAMESPACE" \
        -o jsonpath='{.spec.type}' 2>/dev/null) || return

    case "$svc_type" in
        LoadBalancer)
            local ext=""
            local retries=0
            while [[ -z "$ext" && $retries -lt 15 ]]; do
                ext=$(kubectl get svc "$svc_name" -n "$NAMESPACE" \
                    -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null)
                [[ -z "$ext" ]] && ext=$(kubectl get svc "$svc_name" -n "$NAMESPACE" \
                    -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null)
                [[ -z "$ext" ]] && sleep 2 && retries=$((retries+1))
            done
            [[ -n "$ext" ]] && echo "http://${ext}:${port}" ;;
        NodePort)
            local node_port node_ip
            node_port=$(kubectl get svc "$svc_name" -n "$NAMESPACE" \
                -o jsonpath="{.spec.ports[?(@.port==${port})].nodePort}" 2>/dev/null)
            node_ip=$(kubectl get nodes \
                -o jsonpath='{.items[0].status.addresses[?(@.type=="ExternalIP")].address}' 2>/dev/null)
            [[ -z "$node_ip" ]] && node_ip=$(kubectl get nodes \
                -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}' 2>/dev/null)
            [[ -n "$node_ip" && -n "$node_port" ]] && echo "http://${node_ip}:${node_port}" ;;
        ClusterIP)
            warn "Service '$svc_name' is ClusterIP — use port-forward to access locally:"
            warn "  kubectl port-forward svc/$svc_name $port:$port -n $NAMESPACE" ;;
    esac
}

# ── Main ──────────────────────────────────────────────────────────────

# Parse args
while [[ $# -gt 0 ]]; do
    case "$1" in
        --mode)      MODE="$2";         shift 2 ;;
        --registry)  REGISTRY_URL="$2"; shift 2 ;;
        --image)     IMAGE="$2";        shift 2 ;;
        --namespace) NAMESPACE="$2";    shift 2 ;;
        --cleanup)   CLEANUP=true;      shift ;;
        --help)
            sed -n '2,20p' "$0" | grep '^#' | sed 's/^# \?//'
            exit 0 ;;
        *) error "Unknown argument: $1" ;;
    esac
done

[[ "$MODE" != "aio" && "$MODE" != "distributed" ]] && \
    error "Invalid mode '$MODE'. Use: aio | distributed"

check_kubectl

if $CLEANUP; then
    case "$MODE" in
        aio)         cleanup_aio ;;
        distributed) cleanup_distributed ;;
    esac
else
    case "$MODE" in
        aio)         deploy_aio ;;
        distributed) deploy_distributed ;;
    esac
fi
