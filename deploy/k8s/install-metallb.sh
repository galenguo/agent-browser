#!/bin/bash
set -euo pipefail

echo "=== Agent Browser: Install MetalLB ==="

# Step 1: Apply MetalLB manifest (Namespace + CRDs + Controller)
echo "Applying MetalLB manifests..."
kubectl apply -f https://raw.githubusercontent.com/metallb/metallb/v0.14.8/config/manifests/metallb-native.yaml

# Step 2: Wait for controller to be ready
echo "Waiting for MetalLB controller..."
kubectl rollout status deployment/controller -n metallb-system --timeout=60s

# Step 3: Create IPAddressPool for kind network
echo "Configuring IPAddressPool..."
cat <<'EOF' | kubectl apply -f -
apiVersion: metallb.io/v1beta1
kind: IPAddressPool
metadata:
  name: agent-browser-pool
  namespace: metallb-system
spec:
  addresses:
  - 172.18.255.200-172.18.255.210
---
apiVersion: metallb.io/v1beta1
kind: L2Advertisement
metadata:
  name: agent-browser-advert
  namespace: metallb-system
spec:
  ipAddressPools:
  - agent-browser-pool
EOF

echo ""
echo "=== MetalLB Ready ==="
kubectl get all -n metallb-system
