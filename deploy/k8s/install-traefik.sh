#!/bin/bash
set -euo pipefail

echo "=== Agent Browser: Install Traefik (Gateway API) ==="

# Step 1: Install Gateway API CRDs (standard)
echo "Installing Gateway API CRDs..."
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.1.0/standard-install.yaml

# Step 2: Ensure Helm is installed
if ! command -v helm &>/dev/null; then
  echo "Installing Helm..."
  brew install helm || { echo "ERROR: Helm installation failed"; exit 1; }
fi

# Step 3: Add Traefik Helm repo
helm repo add traefik https://traefik.github.io/charts 2>/dev/null || true
helm repo update

# Step 4: Install Traefik with Gateway API provider
SCRIPT_DIR="$(dirname "$0")"
helm install traefik traefik/traefik \
  -n traefik --create-namespace \
  -f "$SCRIPT_DIR/traefik-values.yaml" \
  --wait --timeout=120s

echo ""
echo "=== Traefik Ready ==="
kubectl get gatewayclass
kubectl get pods -n traefik
