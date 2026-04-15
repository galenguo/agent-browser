"""Stealth profile system -- named delay presets for different deployment scenarios.

Provides fine-grained control over stealth delay parameters via environment
variable ``AGENT_BROWSER_STEALTH_PROFILE``.  Presets:

  - ``full``     Maximum anti-detection (default, identical to historical behaviour)
  - ``balanced`` K8s-optimised, ~60-70 % less delay overhead
  - ``minimal``  Near-zero delays for trusted / internal targets
  - ``off``      All delays disabled (equivalent to stealth_enabled=False)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StealthProfile:
    """Immutable configuration for stealth delay behaviour."""

    name: str

    # Per-action pre-delay ranges (seconds)
    delay_map: dict[str, tuple[float, float]] = field(default_factory=dict)

    # Post-action delay range (seconds)
    post_delay_range: tuple[float, float] = (0.05, 0.2)

    # Feature toggles
    mouse_move_enabled: bool = True
    human_scroll_enabled: bool = True
    human_type_enabled: bool = True
    warmup_enabled: bool = True

    # Mouse move tuning
    mouse_move_steps: int = 20  # Bezier curve interpolation steps

    # Human typing tuning
    typing_delay_range: tuple[int, int] = (50, 250)  # ms per character
    typo_probability: float = 0.05
    long_pause_probability: float = 0.10


# ── Built-in presets ────────────────────────────────────────────


FULL_PROFILE = StealthProfile(
    name="full",
    delay_map={
        "navigate": (0.5, 1.5),
        "click": (0.1, 0.3),
        "input": (0.3, 0.8),
        "scroll": (0.3, 1.0),
        "extract": (0.0, 0.0),
        "general": (0.1, 0.5),
    },
    post_delay_range=(0.05, 0.2),
    mouse_move_enabled=True,
    human_scroll_enabled=True,
    human_type_enabled=True,
    warmup_enabled=True,
    mouse_move_steps=20,
    typing_delay_range=(50, 250),
    typo_probability=0.05,
    long_pause_probability=0.10,
)

BALANCED_PROFILE = StealthProfile(
    name="balanced",
    delay_map={
        "navigate": (0.1, 0.3),
        "click": (0.02, 0.08),
        "input": (0.05, 0.15),
        "scroll": (0.05, 0.15),
        "extract": (0.0, 0.0),
        "general": (0.02, 0.1),
    },
    post_delay_range=(0.01, 0.05),
    mouse_move_enabled=True,
    human_scroll_enabled=True,
    human_type_enabled=True,
    warmup_enabled=True,
    mouse_move_steps=10,
    typing_delay_range=(20, 80),
    typo_probability=0.01,
    long_pause_probability=0.02,
)

MINIMAL_PROFILE = StealthProfile(
    name="minimal",
    delay_map={
        "navigate": (0.0, 0.05),
        "click": (0.0, 0.02),
        "input": (0.0, 0.03),
        "scroll": (0.0, 0.03),
        "extract": (0.0, 0.0),
        "general": (0.0, 0.02),
    },
    post_delay_range=(0.0, 0.01),
    mouse_move_enabled=True,
    human_scroll_enabled=True,
    human_type_enabled=True,
    warmup_enabled=True,
    mouse_move_steps=3,
    typing_delay_range=(20, 30),
    typo_probability=0.01,
    long_pause_probability=0.01,
)

OFF_PROFILE = StealthProfile(
    name="off",
    delay_map={
        "navigate": (0.0, 0.0),
        "click": (0.0, 0.0),
        "input": (0.0, 0.0),
        "scroll": (0.0, 0.0),
        "extract": (0.0, 0.0),
        "general": (0.0, 0.0),
    },
    post_delay_range=(0.0, 0.0),
    mouse_move_enabled=False,
    human_scroll_enabled=False,
    human_type_enabled=False,
    warmup_enabled=False,
    mouse_move_steps=0,
    typing_delay_range=(0, 0),
    typo_probability=0.0,
    long_pause_probability=0.0,
)


BUILTIN_PROFILES: dict[str, StealthProfile] = {
    "full": FULL_PROFILE,
    "balanced": BALANCED_PROFILE,
    "minimal": MINIMAL_PROFILE,
    "off": OFF_PROFILE,
}


def resolve_stealth_profile(name: str) -> StealthProfile:
    """Look up a built-in profile by name.

    Raises ``ValueError`` for unknown names.
    """
    profile = BUILTIN_PROFILES.get(name)
    if profile is None:
        raise ValueError(
            f"Unknown stealth profile '{name}'. "
            f"Available: {', '.join(sorted(BUILTIN_PROFILES))}"
        )
    return profile


def profile_from_env() -> StealthProfile:
    """Read ``AGENT_BROWSER_STEALTH_PROFILE`` env var and return the profile.

    Defaults to ``"minimal"`` when unset, and warns on unrecognised values.
    """
    name = os.getenv("AGENT_BROWSER_STEALTH_PROFILE", "minimal")
    try:
        return resolve_stealth_profile(name)
    except ValueError:
        logger.warning(
            "Unrecognised AGENT_BROWSER_STEALTH_PROFILE='%s', falling back to 'full'",
            name,
        )
        return FULL_PROFILE
