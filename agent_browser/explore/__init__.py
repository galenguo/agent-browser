"""Site exploration module.

Explores target sites, analyzes DOM structure, generates cascade CSS
selectors, and synthesizes YAML adapters.
"""
from .explorer import explore, Endpoint, ExplorationResult
from .analysis import (
    DiscoveredStore,
    InferredCapability,
    detect_site_name,
    detect_auth_indicators,
    infer_capabilities_from_endpoints,
)
from .cascade import cascade as cascade_explore
from .synthesizer import synthesize

__all__ = [
    "explore",
    "Endpoint",
    "ExplorationResult",
    "DiscoveredStore",
    "InferredCapability",
    "detect_site_name",
    "detect_auth_indicators",
    "infer_capabilities_from_endpoints",
    "cascade_explore",
    "synthesize",
]
