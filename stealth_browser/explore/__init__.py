"""Site exploration module.

Explores target sites, analyzes DOM structure, generates cascade CSS
selectors, and synthesizes YAML adapters.
"""

from .analysis import (
    DiscoveredStore,
    InferredCapability,
    detect_auth_indicators,
    detect_site_name,
    infer_capabilities_from_endpoints,
)
from .cascade import cascade as cascade_explore
from .explorer import Endpoint, ExplorationResult, explore
from .synthesizer import synthesize

__all__ = [
    "DiscoveredStore",
    "Endpoint",
    "ExplorationResult",
    "InferredCapability",
    "cascade_explore",
    "detect_auth_indicators",
    "detect_site_name",
    "explore",
    "infer_capabilities_from_endpoints",
    "synthesize",
]
