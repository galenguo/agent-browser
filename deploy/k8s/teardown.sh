#!/bin/bash
set -euo pipefail

echo "=== Stealth Browser: Teardown ==="
cd "$(dirname "$0")"

# Delete kind cluster (removes all resources)
if kind get clusters 2>/dev/null | grep -q "stealth-browser"; then
  echo "Deleting kind cluster 'stealth-browser'..."
  kind delete cluster --name stealth-browser
else
  echo "Kind cluster 'stealth-browser' not found, nothing to teardown"
fi

# Clean up data directories (optional, uncomment if needed)
# rm -rf data/profiles/* data/logs/*

echo ""
echo "=== Teardown Complete ==="
