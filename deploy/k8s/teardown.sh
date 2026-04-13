#!/bin/bash
set -euo pipefail

echo "=== Agent Browser: Teardown ==="
cd "$(dirname "$0")"

# Delete kind cluster (removes all resources)
if kind get clusters 2>/dev/null | grep -q "agent-browser"; then
  echo "Deleting kind cluster 'agent-browser'..."
  kind delete cluster --name agent-browser
else
  echo "Kind cluster 'agent-browser' not found, nothing to teardown"
fi

# Clean up data directories (optional, uncomment if needed)
# rm -rf data/profiles/* data/logs/*

echo ""
echo "=== Teardown Complete ==="
