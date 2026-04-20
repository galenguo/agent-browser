#!/bin/bash
set -euo pipefail

echo "=== Stealth Browser: Setup kind Cluster ==="
cd "$(dirname "$0")"

# Step 1: Install kind
if ! command -v kind &>/dev/null; then
  echo "Installing kind..."
  brew install kind || { echo "ERROR: kind installation failed"; exit 1; }
fi

# Step 2: Create data directories
mkdir -p data/profiles data/logs

# Step 3: Delete existing cluster if present
if kind get clusters 2>/dev/null | grep -q "stealth-browser"; then
  echo "Deleting existing stealth-browser cluster..."
  kind delete cluster --name stealth-browser
fi

# Step 4: Create cluster
echo "Creating kind cluster..."
kind create cluster --config kind-config.yaml

# Step 5: Verify
echo ""
echo "=== Cluster Ready ==="
kind get clusters
kubectl get nodes
kubectl get pods -A
