"""Shared state store for distributed K8s deployment.

Provides K8s-native (ConfigMap + CAS) and in-memory implementations
for cross-replica state coordination.
"""

from stealth_browser.state.store import (
    InMemoryStateStore,
    K8sSharedState,
    StateStore,
    create_state_store,
)

__all__ = [
    "StateStore",
    "InMemoryStateStore",
    "K8sSharedState",
    "create_state_store",
]
