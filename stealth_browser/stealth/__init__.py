"""Anti-detection stealth layer.

Provides StealthMiddleware (centralized stealth wrapper with circuit breaker),
StealthEnhancer (human behavior simulation), stealth action overrides,
JS runtime patches, and BrowserController.
"""

from stealth_browser.stealth.actions import register_stealth_actions
from stealth_browser.stealth.browser_controller import ActionResult, BrowserController
from stealth_browser.stealth.enhancer import StealthEnhancer
from stealth_browser.stealth.middleware import (
    CircuitState,
    StealthMiddleware,
    StealthPageHandle,
    _PerSessionCircuit,
)
from stealth_browser.stealth.patches import (
    STEALTH_PATCHES_JS,
    inject_stealth_patches,
    verify_patches,
)
from stealth_browser.stealth.profiles import (
    BUILTIN_PROFILES,
    BALANCED_PROFILE,
    FULL_PROFILE,
    MINIMAL_PROFILE,
    OFF_PROFILE,
    StealthProfile,
    profile_from_env,
    resolve_stealth_profile,
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
    # Profiles (named delay presets)
    "StealthProfile",
    "BUILTIN_PROFILES",
    "FULL_PROFILE",
    "BALANCED_PROFILE",
    "MINIMAL_PROFILE",
    "OFF_PROFILE",
    "resolve_stealth_profile",
    "profile_from_env",
    # Middleware (Layer 7: centralized stealth)
    "StealthMiddleware",
    "StealthPageHandle",
    "_PerSessionCircuit",
    "inject_stealth_patches",
    # Actions (browser-use overrides)
    "register_stealth_actions",
    "verify_patches",
]
