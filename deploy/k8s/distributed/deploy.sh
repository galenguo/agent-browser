#!/bin/bash
# deploy/k8s/distributed/deploy.sh
# Distributed k8s mode deployment script
# Manages: RBAC, ConfigMap, CP StatefulSet, BR headless service
# BR pods are created dynamically by K8sBrowserNodeManager at runtime.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAMESPACE="agent-browser"
IMAGE="${IMAGE:-registry-cn-gimc-local.gimccloud.com/library/agent-browser:latest}"
ACTION="${1:-deploy}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]  $*${NC}"; }
success() { echo -e "${GREEN}[OK]    $*${NC}"; }
warn()    { echo -e "${YELLOW}[WARN]  $*${NC}"; }
error()   { echo -e "${RED}[ERROR] $*${NC}"; exit 1; }

# ── Helpers ──────────────────────────────────────────────────────────

wait_rollout() {
    local resource="$1"
    info "Waiting for $resource to be ready..."
    kubectl rollout status "$resource" -n "$NAMESPACE" --timeout=120s
}

patch_image() {
    # Substitute IMAGE placeholder in a manifest and pipe to kubectl
    sed "s|IMAGE_PLACEHOLDER|${IMAGE}|g" "$1"
}

# ── Deploy ────────────────────────────────────────────────────────────

deploy() {
    info "=== Deploying agent-browser (distributed k8s mode) ==="
    info "Namespace : $NAMESPACE"
    info "Image     : $IMAGE"
    echo ""

    # 1. Namespace
    kubectl apply -f "$SCRIPT_DIR/namespace.yaml"
    success "Namespace ready"

    # 2. Secret (skip if already exists — contains real credentials)
    if ! kubectl get secret agent-browser-secret -n "$NAMESPACE" &>/dev/null; then
        warn "Secret 'agent-browser-secret' not found."
        warn "Create it before deploying:"
        warn "  kubectl create secret generic agent-browser-secret -n $NAMESPACE \\"
        warn "    --from-literal=ANTHROPIC_API_KEY=<key> \\"
        warn "    --from-literal=OPENAI_API_KEY=<key> \\"
        warn "    --from-literal=OPENAI_BASE_URL=https://api.openai.com/v1"
        error "Aborting — secret missing"
    fi
    success "Secret exists"

    # 3. RBAC (ServiceAccount + Role + RoleBinding for CP pod to manage BR pods/PVCs)
    kubectl apply -f "$SCRIPT_DIR/rbac.yaml"
    success "RBAC applied"

    # 4. ConfigMap
    kubectl apply -f "$SCRIPT_DIR/configmap.yaml"
    success "ConfigMap applied"

    # 4b. API Keys ConfigMap (keys.yaml → /app/config/keys.yaml in CP pod)
    KEYS_FILE="$SCRIPT_DIR/../../../config/keys.yaml"
    if [[ -f "$KEYS_FILE" ]]; then
        kubectl create configmap agent-browser-api-keys \
            --from-file=keys.yaml="$KEYS_FILE" \
            -n "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
        success "API keys ConfigMap applied"
    else
        warn "config/keys.yaml not found — skipping API keys ConfigMap (auth will reject all requests)"
    fi

    # 5. Services
    kubectl apply -f "$SCRIPT_DIR/service-api.yaml"
    kubectl apply -f "$SCRIPT_DIR/service-headless.yaml"
    kubectl apply -f "$SCRIPT_DIR/browser-service-headless.yaml"
    success "Services applied"

    # 6. HTTPRoute / networking (optional — skip if Gateway API CRDs not installed)
    if kubectl api-resources | grep -q "httproutes"; then
        kubectl apply -f "$SCRIPT_DIR/httproute.yaml"
        success "HTTPRoute applied"
    else
        warn "Gateway API CRDs not found — skipping httproute.yaml"
    fi

    # 7. Control Plane StatefulSet
    #    NOTE: StatefulSet spec is largely immutable. If a previous version exists,
    #    we delete it with --cascade=orphan (preserves running pods) then recreate.
    if kubectl get statefulset agent-browser-cp -n "$NAMESPACE" &>/dev/null; then
        CURRENT_IMAGE=$(kubectl get statefulset agent-browser-cp -n "$NAMESPACE" \
            -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null)
        if [[ "$CURRENT_IMAGE" != "$IMAGE" ]]; then
            info "Image changed ($CURRENT_IMAGE → $IMAGE), performing rolling restart..."
            kubectl set image statefulset/agent-browser-cp \
                agent-browser="$IMAGE" -n "$NAMESPACE"
            wait_rollout "statefulset/agent-browser-cp"
        else
            info "CP StatefulSet already up-to-date, applying config changes..."
            kubectl apply -f "$SCRIPT_DIR/control-plane-statefulset.yaml"
        fi
    else
        kubectl apply -f "$SCRIPT_DIR/control-plane-statefulset.yaml"
        wait_rollout "statefulset/agent-browser-cp"
    fi
    success "Control plane ready"

    # 8. Wait for warm pool (CP creates BR pods on startup; wait for at least 1 BR pod)
    info "Waiting for warm BR pods to be created (up to 120s)..."
    local elapsed=0
    while [[ $elapsed -lt 120 ]]; do
        BR_COUNT=$(kubectl get pods -n "$NAMESPACE" -l app=agent-browser-br \
            --field-selector=status.phase=Running --no-headers 2>/dev/null | wc -l | tr -d ' ')
        if [[ "$BR_COUNT" -ge 1 ]]; then
            success "Warm pool active ($BR_COUNT BR pod(s) running)"
            break
        fi
        sleep 5
        elapsed=$((elapsed + 5))
    done
    if [[ "$BR_COUNT" -lt 1 ]]; then
        warn "No BR pods running yet — they may still be starting. Check: kubectl get pods -n $NAMESPACE"
    fi

    echo ""
    show_status
    success "=== Deployment complete ==="
}

# ── Upgrade (image only) ──────────────────────────────────────────────

upgrade() {
    info "=== Upgrading CP image to $IMAGE ==="
    kubectl set image statefulset/agent-browser-cp \
        agent-browser="$IMAGE" -n "$NAMESPACE"
    wait_rollout "statefulset/agent-browser-cp"
    success "Upgrade complete"
}

# ── Teardown ──────────────────────────────────────────────────────────

teardown() {
    warn "=== Tearing down distributed deployment ==="
    warn "This will delete the CP StatefulSet and all dynamically-created BR pods."
    read -r -p "Continue? [y/N] " confirm
    [[ "$confirm" =~ ^[Yy]$ ]] || { info "Aborted."; exit 0; }

    # Delete CP StatefulSet (cascade=foreground removes pods too)
    kubectl delete statefulset agent-browser-cp -n "$NAMESPACE" \
        --ignore-not-found=true --cascade=foreground

    # Delete all dynamically-created BR pods and their PVCs
    info "Deleting BR pods..."
    kubectl delete pods -n "$NAMESPACE" -l app=agent-browser-br \
        --ignore-not-found=true
    info "Deleting BR PVCs..."
    kubectl delete pvc -n "$NAMESPACE" -l app=agent-browser-br \
        --ignore-not-found=true

    # Delete services and RBAC
    kubectl delete -f "$SCRIPT_DIR/service-api.yaml" --ignore-not-found=true
    kubectl delete -f "$SCRIPT_DIR/service-headless.yaml" --ignore-not-found=true
    kubectl delete -f "$SCRIPT_DIR/browser-service-headless.yaml" --ignore-not-found=true
    kubectl delete -f "$SCRIPT_DIR/rbac.yaml" --ignore-not-found=true
    kubectl delete -f "$SCRIPT_DIR/configmap.yaml" --ignore-not-found=true
    kubectl delete configmap agent-browser-api-keys -n "$NAMESPACE" --ignore-not-found=true

    if kubectl api-resources | grep -q "httproutes"; then
        kubectl delete -f "$SCRIPT_DIR/httproute.yaml" --ignore-not-found=true
    fi

    success "Teardown complete"
}

# ── Status ────────────────────────────────────────────────────────────

show_status() {
    echo ""
    info "--- Pods ---"
    kubectl get pods -n "$NAMESPACE" 2>/dev/null || true
    echo ""
    info "--- Services ---"
    kubectl get svc -n "$NAMESPACE" 2>/dev/null || true
    echo ""
    API_URL=$(kubectl get httproute agent-browser-api-route -n "$NAMESPACE" \
        -o jsonpath='{.spec.hostnames[0]}' 2>/dev/null || echo "")
    VNC_URL=$(kubectl get httproute agent-browser-vnc-route -n "$NAMESPACE" \
        -o jsonpath='{.spec.hostnames[0]}' 2>/dev/null || echo "")
    if [[ -n "$API_URL" ]]; then
        info "API endpoint : http://$API_URL"
        info "VNC endpoint : http://$VNC_URL"
    fi
}

# ── Dispatch ──────────────────────────────────────────────────────────

case "$ACTION" in
    deploy)   deploy ;;
    upgrade)  upgrade ;;
    teardown) teardown ;;
    status)   show_status ;;
    *)
        echo "Usage: $0 [deploy|upgrade|teardown|status]"
        echo ""
        echo "Environment variables:"
        echo "  IMAGE      Container image (default: registry-cn-gimc-local.gimccloud.com/library/agent-browser:latest)"
        echo ""
        echo "Examples:"
        echo "  $0 deploy"
        echo "  IMAGE=my-registry/agent-browser:v2 $0 upgrade"
        echo "  $0 teardown"
        exit 1
        ;;
esac
