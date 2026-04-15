"""
StealthEnhancer -- Anti-detection behavior enhancer.

Integrates human behavior simulation capabilities to provide a unified
stealth interface for BrowserController:
- Human operation delays (random wait)
- Mouse movement simulation (Bezier curves)
- Typing rhythm simulation (variable speed + backspace)
- Scroll behavior simulation (non-uniform + rollback)
- Warmup browsing

Corresponds to the "anti-detection (stealth)" guarantee in core features.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_browser.stealth.profiles import StealthProfile

logger = logging.getLogger(__name__)


class StealthEnhancer:
    """
    Anti-detection enhancer that injects human behavior patterns into every operation.

    Designed as a plugin for BrowserController, using pre_action / post_action
    to add human-like behavior before and after each atomic operation.

    When a ``StealthProfile`` is provided, all delay/behaviour parameters are
    loaded from it.  When no profile is given, the legacy hardcoded defaults
    are used (100 % backward-compatible).
    """

    def __init__(
        self,
        min_delay: float = 0.1,
        max_delay: float = 0.5,
        mouse_move: bool = True,
        human_scroll: bool = True,
        profile: StealthProfile | None = None,
    ):
        if profile is not None:
            self._profile = profile
            self._delay_map: dict[str, tuple[float, float]] = dict(profile.delay_map)
            self._post_delay_range: tuple[float, float] = profile.post_delay_range
            self.mouse_move = profile.mouse_move_enabled
            self._human_scroll = profile.human_scroll_enabled
            self._human_type_enabled = profile.human_type_enabled
            self._mouse_move_steps: int = profile.mouse_move_steps
            self._typing_delay_range: tuple[int, int] = profile.typing_delay_range
            self._typo_probability: float = profile.typo_probability
            self._long_pause_probability: float = profile.long_pause_probability
            # Keep min/max for general fallback
            general = profile.delay_map.get("general", (min_delay, max_delay))
            self.min_delay = general[0]
            self.max_delay = general[1]
        else:
            # Legacy path -- exact historical defaults
            self._profile = None
            self._delay_map = {}
            self._post_delay_range = (0.05, 0.2)
            self.mouse_move = mouse_move
            self._human_scroll = human_scroll
            self._human_type_enabled = True
            self._mouse_move_steps = 20
            self._typing_delay_range = (50, 250)
            self._typo_probability = 0.05
            self._long_pause_probability = 0.10
            self.min_delay = min_delay
            self.max_delay = max_delay

    # ──────────────────────────────────────────
    # Pre-action delays
    # ──────────────────────────────────────────

    async def pre_action(self, action_type: str = "general") -> None:
        """
        Human delay before an action.

        Different action types have different delay ranges.
        When a profile is set, delays come from the profile's delay_map;
        otherwise the legacy hardcoded values are used.
        """
        if self._delay_map:
            low, high = self._delay_map.get(
                action_type, self._delay_map.get("general", (0.0, 0.0))
            )
        else:
            # Legacy fallback
            delay_map = {
                "navigate": (0.5, 1.5),
                "click": (0.1, 0.3),
                "input": (0.3, 0.8),
                "scroll": (0.3, 1.0),
                "extract": (0.0, 0.0),
                "general": (self.min_delay, self.max_delay),
            }
            low, high = delay_map.get(action_type, (self.min_delay, self.max_delay))

        if low > 0 or high > 0:
            delay = random.uniform(low, high)
            await asyncio.sleep(delay)

    async def post_action(self, action_type: str = "general") -> None:
        """Brief pause after an action."""
        low, high = self._post_delay_range
        if low > 0 or high > 0:
            delay = random.uniform(low, high)
            await asyncio.sleep(delay)

    # ──────────────────────────────────────────
    # Mouse movement
    # ──────────────────────────────────────────

    async def random_mouse_move(self, page) -> None:
        """
        Random mouse wandering (Bezier curve simulating real human trajectory).
        Counters Tongdun Technology's mouse trajectory entropy analysis.
        """
        if not self.mouse_move:
            return

        try:
            viewport = page.viewport_size or {"width": 1920, "height": 1080}
            moves = random.randint(1, 3)

            cx = random.randint(200, viewport["width"] - 200)
            cy = random.randint(200, viewport["height"] - 200)

            for _ in range(moves):
                tx = random.randint(100, viewport["width"] - 100)
                ty = random.randint(100, viewport["height"] - 100)
                await self._bezier_mouse_move(page, cx, cy, tx, ty)
                cx, cy = tx, ty
                await asyncio.sleep(random.uniform(0.2, 0.8))
        except Exception as e:
            logger.debug(f"Mouse move failed (non-critical): {e}")

    async def _bezier_mouse_move(
        self, page, start_x: int, start_y: int, end_x: int, end_y: int, steps: int | None = None
    ) -> None:
        """Move mouse along a cubic Bezier curve."""
        import math

        actual_steps = steps if steps is not None else self._mouse_move_steps
        if actual_steps <= 0:
            return

        ctrl1_x = start_x + (end_x - start_x) * 0.25 + random.randint(-80, 80)
        ctrl1_y = start_y + (end_y - start_y) * 0.25 + random.randint(-80, 80)
        ctrl2_x = start_x + (end_x - start_x) * 0.75 + random.randint(-80, 80)
        ctrl2_y = start_y + (end_y - start_y) * 0.75 + random.randint(-80, 80)

        for i in range(actual_steps + 1):
            t = i / actual_steps
            x = (1 - t) ** 3 * start_x + 3 * (1 - t) ** 2 * t * ctrl1_x + 3 * (1 - t) * t**2 * ctrl2_x + t**3 * end_x
            y = (1 - t) ** 3 * start_y + 3 * (1 - t) ** 2 * t * ctrl1_y + 3 * (1 - t) * t**2 * ctrl2_y + t**3 * end_y
            await page.mouse.move(int(x), int(y))
            base_delay = 0.005 + 0.02 * math.sin(math.pi * t)
            await asyncio.sleep(base_delay + random.uniform(0, 0.008))

    # ──────────────────────────────────────────
    # Human typing
    # ──────────────────────────────────────────

    async def human_type(self, page, selector: str, text: str, clear_first: bool = True) -> None:
        """
        Realistic typing simulation: variable speed + occasional typo + pause to think.

        When ``human_type_enabled`` is False in the profile, falls back to a simple
        Playwright ``fill()`` with no character-by-character delay.
        """
        element = page.locator(selector)
        await element.click()

        if not self._human_type_enabled:
            # Fast path: use Playwright's native fill
            if clear_first:
                await element.fill("")
            await element.fill(text)
            return

        await asyncio.sleep(random.uniform(0.3, 0.8))

        if clear_first:
            await page.keyboard.press("Control+a")
            await asyncio.sleep(random.uniform(0.1, 0.3))
            await page.keyboard.press("Backspace")
            await asyncio.sleep(random.uniform(0.2, 0.5))

        delay_lo, delay_hi = self._typing_delay_range
        for char in text:
            # Typo simulation
            if random.random() < self._typo_probability:
                wrong_char = random.choice("abcdef1234567890")
                await page.keyboard.type(wrong_char)
                await asyncio.sleep(random.uniform(0.08, 0.25))
                await page.keyboard.press("Backspace")
                await asyncio.sleep(random.uniform(0.15, 0.4))

            # Variable speed typing
            delay_ms = random.randint(delay_lo, delay_hi) if delay_hi > 0 else 0
            # Long pause
            if random.random() < self._long_pause_probability:
                delay_ms += random.randint(500, 1500)

            if delay_ms > 0:
                await page.keyboard.type(char, delay=delay_ms)
            else:
                await page.keyboard.type(char)

    # ──────────────────────────────────────────
    # Human scrolling
    # ──────────────────────────────────────────

    async def human_scroll(self, page, scroll_count: int | None = None) -> None:
        """
        Non-uniform scrolling: variable speed + random pauses + 20% chance of rollback.
        Counters Tongdun Technology's scroll pattern analysis.
        """
        if not self._human_scroll:
            return

        count = scroll_count or random.randint(2, 5)

        for _ in range(count):
            distance = random.randint(100, 600)
            await page.evaluate(f"window.scrollBy(0, {distance})")
            await asyncio.sleep(random.uniform(0.5, 3.0))

            # 20% chance of rollback
            if random.random() < 0.2:
                back = random.randint(50, 200)
                await page.evaluate(f"window.scrollBy(0, -{back})")
                await asyncio.sleep(random.uniform(0.3, 1.2))

    # ──────────────────────────────────────────
    # Reading pause
    # ──────────────────────────────────────────

    async def reading_pause(self, min_sec: float = 2.0, max_sec: float = 8.0) -> None:
        """Simulate a reading pause."""
        duration = random.uniform(min_sec, max_sec)
        logger.debug(f"Reading pause: {duration:.1f}s")
        await asyncio.sleep(duration)

    # ──────────────────────────────────────────
    # Warmup browsing
    # ──────────────────────────────────────────

    WARMUP_URLS = [
        "https://www.baidu.com",
        "https://www.163.com",
    ]

    async def warmup_browsing(self, page, urls: list[str] | None = None) -> None:
        """
        Warmup browsing: establish a "normal user" baseline in anti-bot models.
        """
        warmup_list = urls or self.WARMUP_URLS

        for url in warmup_list:
            try:
                logger.info(f"Warmup: visiting {url}")
                await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
                await self.human_scroll(page)
                await self.reading_pause(3, 8)
                await self.random_mouse_move(page)
                await asyncio.sleep(random.uniform(1, 3))
            except Exception as e:
                logger.warning(f"Warmup URL {url} failed (non-fatal): {e}")

    # ──────────────────────────────────────────
    # Timing noise injection
    # ──────────────────────────────────────────

    @staticmethod
    async def inject_timing_noise(page, max_offset_ms: int = 5) -> None:
        """
        Inject timing noise to defend against JS timing-based fingerprinting.
        """
        await page.add_init_script(f"""
            (function() {{
                const _origDateNow = Date.now;
                const _origPerfNow = performance.now.bind(performance);
                const _maxOff = {max_offset_ms};
                Date.now = function() {{
                    return _origDateNow() + Math.floor(Math.random() * _maxOff);
                }};
                performance.now = function() {{
                    return _origPerfNow() + Math.random() * _maxOff;
                }};
            }})();
        """)
