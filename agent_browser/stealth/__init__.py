"""Anti-detection stealth layer.

Provides StealthMiddleware (centralized stealth wrapper with circuit breaker),
StealthEnhancer (human behavior simulation), stealth action overrides,
JS runtime patches, and BrowserController.
"""

from agent_browser.stealth.actions import register_stealth_actions
from agent_browser.stealth.browser_controller import ActionResult, BrowserController
from agent_browser.stealth.enhancer import StealthEnhancer
from agent_browser.stealth.middleware import (
    CircuitState,
    StealthMiddleware,
    StealthPageHandle,
    _PerSessionCircuit,
)
from agent_browser.stealth.patches import (
    STEALTH_PATCHES_JS,
    inject_stealth_patches,
    verify_patches,
)

__all__ = [
    # Patches (JS runtime property-level)
    "STEALTH_PATCHES_JS",
    # Controller
    "ActionResult",
    "BrowserController",
    "CircuitState",
    # Enhancer (Layer 6: human behavior)
    "StealthEnhancer",
    # Middleware (Layer 7: centralized stealth)
    "StealthMiddleware",
    "StealthPageHandle",
    "_PerSessionCircuit",
    "inject_stealth_patches",
    # Actions (browser-use overrides)
    "register_stealth_actions",
    "verify_patches",
]
