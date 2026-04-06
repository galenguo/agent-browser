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

import asyncio
import logging
import random

logger = logging.getLogger(__name__)


class StealthEnhancer:
    """
    Anti-detection enhancer that injects human behavior patterns into every operation.

    Designed as a plugin for BrowserController, using pre_action / post_action
    to add human-like behavior before and after each atomic operation.
    """

    def __init__(
        self,
        min_delay: float = 0.1,
        max_delay: float = 0.5,
        mouse_move: bool = True,
        human_scroll: bool = True,
    ):
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.mouse_move = mouse_move
        self._human_scroll = human_scroll

    # ──────────────────────────────────────────
    # Pre-action delays
    # ──────────────────────────────────────────

    async def pre_action(self, action_type: str = "general") -> None:
        """
        Human delay before an action.

        Different action types have different delay ranges:
        - navigate: 0.5-1.5s (human thinking about which site to visit)
        - click: 0.1-0.3s (human clicks after finding target)
        - input: 0.3-0.8s (human focuses on input field)
        - extract: 0.0s (extraction needs no delay)
        - general: uses min_delay/max_delay
        """
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
        delay = random.uniform(0.05, 0.2)
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
        self, page, start_x: int, start_y: int, end_x: int, end_y: int, steps: int = 20
    ) -> None:
        """Move mouse along a cubic Bezier curve."""
        import math

        ctrl1_x = start_x + (end_x - start_x) * 0.25 + random.randint(-80, 80)
        ctrl1_y = start_y + (end_y - start_y) * 0.25 + random.randint(-80, 80)
        ctrl2_x = start_x + (end_x - start_x) * 0.75 + random.randint(-80, 80)
        ctrl2_y = start_y + (end_y - start_y) * 0.75 + random.randint(-80, 80)

        for i in range(steps + 1):
            t = i / steps
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

        Characteristics:
          - Base speed: 50-250ms per character
          - 10% chance of long pause (500-1500ms) simulating "thinking"
          - 5% chance of typo then backspace correction
        """
        element = page.locator(selector)
        await element.click()
        await asyncio.sleep(random.uniform(0.3, 0.8))

        if clear_first:
            await page.keyboard.press("Control+a")
            await asyncio.sleep(random.uniform(0.1, 0.3))
            await page.keyboard.press("Backspace")
            await asyncio.sleep(random.uniform(0.2, 0.5))

        for char in text:
            # 5% chance of typo then backspace
            if random.random() < 0.05:
                wrong_char = random.choice("abcdef1234567890")
                await page.keyboard.type(wrong_char)
                await asyncio.sleep(random.uniform(0.08, 0.25))
                await page.keyboard.press("Backspace")
                await asyncio.sleep(random.uniform(0.15, 0.4))

            # Variable speed typing
            delay_ms = random.randint(50, 250)
            # 10% chance of long pause
            if random.random() < 0.1:
                delay_ms += random.randint(500, 1500)

            await page.keyboard.type(char, delay=delay_ms)

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
