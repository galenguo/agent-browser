#!/bin/bash
set -euo pipefail

echo "============================================="
echo "  Agent Browser on kind + Traefik Deployer"
echo "============================================="
cd "$(dirname "$0")"

# ── Step 1: Kind Cluster ────────────────────────────────
if ! kind get clusters 2>/dev/null | grep -q "agent-browser"; then
  echo ""
  echo "[1/6] Creating kind cluster..."
  bash setup-cluster.sh
else
  echo "[1/6] Kind cluster already exists, skipping"
fi

# ── Step 2: MetalLB ──────────────────────────────────────
if ! kubectl get ns metallb-system &>/dev/null; then
  echo ""
  echo "[2/6] Installing MetalLB..."
  bash install-metallb.sh
else
  echo "[2/6] MetalLB already installed, skipping"
fi

# ── Step 3: Traefik + Gateway API ────────────────────────
if ! kubectl get ns traefik &>/dev/null; then
  echo ""
  echo "[3/6] Installing Traefik with Gateway API..."
  bash install-traefik.sh
else
  echo "[3/6] Traefik already installed, skipping"
fi

# ── Step 4: Load Docker images into kind ─────────────────
echo ""
echo "[4/6] Loading Docker images into kind..."
kind load docker-image agent-browser-api:latest --name agent-browser 2>/dev/null || \
  { echo "WARNING: agent-browser-api image not found locally. Build it first with: cd deploy/docker && bash build-local.sh"; }
kind load docker-image agent-browser-browser:latest --name agent-browser 2>/dev/null || \
  { echo "WARNING: agent-browser-browser image not found locally. Build it first."; }

# ── Step 5: Apply Agent Browser manifests ────────────────
echo ""
echo "[5/6] Applying Agent Browser manifests..."
kubectl apply -f namespace.yaml
kubectl apply -f configmap-distributed.yaml

# Check if secret exists before applying
if [ -f secret.yaml ]; then
  kubectl apply -f secret.yaml 2>/dev/null || \
    echo "NOTE: Copy secret.yaml.example to secret.yaml and fill in your keys"
elif [ -f secret.yaml.example ]; then
  echo "NOTE: Create a secret file: cp secret.yaml.example secret.yaml && edit secret.yaml"
fi

kubectl apply -f pvc.yaml
kubectl apply -f api-deployment.yaml
kubectl apply -f api-service.yaml
kubectl apply -f gateway.yaml
kubectl apply -f httproute-api.yaml
kubectl apply -f httproute-browser.yaml

# ── Step 6: Wait for rollout ─────────────────────────────
echo ""
echo "[6/6] Waiting for deployment to be ready..."
kubectl rollout status deployment/agent-browser-api -n agent-browser --timeout=120s || true

# ── Summary ───────────────────────────────────────────────
echo ""
echo "============================================="
echo "  Deployment Complete!"
echo "============================================="
echo ""
echo "Cluster:"
kind get clusters
echo ""
echo "Nodes:"
kubectl get nodes
echo ""
echo "Agent Browser pods:"
kubectl get pods -n agent-browser -o wide
echo ""
echo "Gateway & Routes:"
kubectl get gateway,httproute -n agent-browser 2>/dev/null || true
echo ""
echo "--- Access URLs ---"
echo "  API (HTTPRoute):   http://api.agent-browser.local/"
echo "  Health check:     http://api.agent-browser.local/health"
echo "  API (NodePort):    http://localhost:30801/"
echo "  noVNC (NodePort):  http://localhost:30680/vnc.html"
echo ""
echo "--- DNS Configuration ---"
echo '  Add to /etc/hosts:'
echo "    127.0.0.1 api.agent-browser.local browser-*.agent-browser.local"
echo ""
echo "--- Test Commands ---"
echo '  # Health check (public, no key needed):'
echo "  curl http://localhost:30801/health"
echo ''
echo '  # With API Key:'
echo '  curl -H "X-API-Key: YOUR_KEY" -H "Host: api.agent-browser.local" \\'
echo '    http://localhost/health'
echo ''
echo '  # Create session:'
echo '  curl -X POST -H "X-API-Key: YOUR_KEY" -H "Host: api.agent-browser.local" \\'
echo '    http://localhost/sessions/create -d "{\"user_id\":\"test\"}"'
