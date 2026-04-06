"""Anti-detection stealth layer.

Provides StealthMiddleware (centralized stealth wrapper with circuit breaker),
StealthEnhancer (human behavior simulation), stealth action overrides,
JS runtime patches, and BrowserController.
"""

from agent_browser.stealth.middleware import (
    CircuitState,
    StealthMiddleware,
    StealthPageHandle,
    _PerSessionCircuit,
)
from agent_browser.stealth.enhancer import StealthEnhancer
from agent_browser.stealth.actions import register_stealth_actions
from agent_browser.stealth.patches import (
    STEALTH_PATCHES_JS,
    inject_stealth_patches,
    verify_patches,
)
from agent_browser.stealth.browser_controller import ActionResult, BrowserController

__all__ = [
    # Middleware (Layer 7: centralized stealth)
    "StealthMiddleware",
    "StealthPageHandle",
    "CircuitState",
    "_PerSessionCircuit",
    # Enhancer (Layer 6: human behavior)
    "StealthEnhancer",
    # Actions (browser-use overrides)
    "register_stealth_actions",
    # Patches (JS runtime property-level)
    "STEALTH_PATCHES_JS",
    "inject_stealth_patches",
    "verify_patches",
    # Controller
    "ActionResult",
    "BrowserController",
]
