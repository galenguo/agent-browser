"""Behavior simulation layer: simulates the "imperfections" of real human operation to counter behavior analysis.

Behavior analysis systems (e.g., Tongdun) detect:
  - Mouse trajectory entropy (straight lines = bot)
  - Scroll patterns (constant speed = bot)
  - Click timing (fixed intervals = bot)
  - Typing rhythm (uniform speed = bot)
  - Page dwell time distribution

Countermeasures:
  - Variable typing speed + occasional backspace (5% probability)
  - Non-uniform scrolling + random pauses + occasional scroll-back (20% probability)
  - Warmup browsing (visit Baidu/news sites first to establish normal user baseline)
  - Random long pauses to simulate "reading" behavior
"""
import asyncio
import logging
import math
import random

# Conditional patchright import (fallback to playwright)
try:
    from patchright.async_api import Page
except ImportError:
    from playwright.async_api import Page

logger = logging.getLogger(__name__)


class HumanBehaviorSimulator:
    """Simulates imperfect human behavior to counter behavioral-analysis anti-bot systems."""

    # Warmup URL list: establish a normal user baseline first (trimmed to 2 to reduce warmup time)
    WARMUP_URLS = [
        "https://www.baidu.com",
        "https://www.zhipin.com",  # Boss Zhipin homepage warmup (no direct search)
    ]

    async def warmup_browsing(
        self,
        page: Page,
        urls: list[str] | None = None,
    ) -> None:
        """Warmup browsing: establish a "normal user" baseline in Akamai/Tongdun behavior models.

        Flow:
          Step 1: Visit Baidu -> search -> browse results (3-5 min)
          Step 2: Visit news site -> random browse (2-3 min)
          Step 3: Visit zhipin.com homepage -> no search, just browse recommendations (2-3 min)
          Step 4: Begin actual task
        """
        warmup_list = urls or self.WARMUP_URLS

        for url in warmup_list:
            try:
                logger.info(f"Warmup: visiting {url}")
                await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
                await self._random_scroll(page)
                await asyncio.sleep(random.uniform(2, 5))

                # Random mouse wandering
                await self._random_mouse_move(page)
                await asyncio.sleep(random.uniform(1, 3))
            except Exception as e:
                logger.warning(f"Warmup URL {url} failed (non-fatal): {e}")

    async def human_type(
        self,
        page: Page,
        selector: str,
        text: str,
        clear_first: bool = True,
    ) -> None:
        """Human-like typing simulation: variable speed + occasional backspace + thinking pauses.

        Characteristics:
          - Base speed: 50-250ms per character
          - 10% chance of long pause (500-1500ms) to simulate "thinking"
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

            # Variable-speed typing
            delay_ms = random.randint(50, 250)
            # 10% chance of long pause (simulate thinking)
            if random.random() < 0.1:
                delay_ms += random.randint(500, 1500)

            await page.keyboard.type(char, delay=delay_ms)

    async def human_click(
        self,
        page: Page,
        selector: str,
        *,
        pre_hover: bool = True,
    ) -> None:
        """Human-like click simulation: hover first -> random delay -> click."""
        element = page.locator(selector)

        if pre_hover:
            # Hover over element first
            await element.hover()
            await asyncio.sleep(random.uniform(0.2, 0.8))

        await element.click()
        await asyncio.sleep(random.uniform(0.3, 1.0))

    async def _random_scroll(
        self,
        page: Page,
        scroll_count: int | None = None,
    ) -> None:
        """Non-uniform scrolling: variable speed + random pauses + 20% chance of scroll-back."""
        count = scroll_count or random.randint(2, 5)

        for _ in range(count):
            distance = random.randint(100, 600)
            await page.evaluate(f"window.scrollBy(0, {distance})")
            await asyncio.sleep(random.uniform(0.3, 2.0))

            # 20% chance of scroll-back (real humans often do this when they see something interesting)
            if random.random() < 0.2:
                back = random.randint(50, 200)
                await page.evaluate(f"window.scrollBy(0, -{back})")
                await asyncio.sleep(random.uniform(0.3, 1.2))

    async def _random_mouse_move(self, page: Page) -> None:
        """Random mouse wandering (uses Bezier curves to simulate realistic human trajectories)."""
        viewport = page.viewport_size or {"width": 1920, "height": 1080}
        moves = random.randint(1, 2)

        # Starting position
        cx = random.randint(200, viewport["width"] - 200)
        cy = random.randint(200, viewport["height"] - 200)

        for _ in range(moves):
            tx = random.randint(100, viewport["width"] - 100)
            ty = random.randint(100, viewport["height"] - 100)
            await self._bezier_mouse_move(page, cx, cy, tx, ty)
            cx, cy = tx, ty
            await asyncio.sleep(random.uniform(0.1, 0.5))

    async def _bezier_mouse_move(
        self,
        page: Page,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        steps: int = 8,
    ) -> None:
        """Move mouse along a cubic Bezier curve (simulates human hand movement trajectory)."""
        # Generate 2 random control points offsetting from the straight-line path
        ctrl1_x = start_x + (end_x - start_x) * 0.25 + random.randint(-80, 80)
        ctrl1_y = start_y + (end_y - start_y) * 0.25 + random.randint(-80, 80)
        ctrl2_x = start_x + (end_x - start_x) * 0.75 + random.randint(-80, 80)
        ctrl2_y = start_y + (end_y - start_y) * 0.75 + random.randint(-80, 80)

        for i in range(steps + 1):
            t = i / steps
            # Cubic Bezier formula
            x = ((1 - t) ** 3 * start_x
                 + 3 * (1 - t) ** 2 * t * ctrl1_x
                 + 3 * (1 - t) * t ** 2 * ctrl2_x
                 + t ** 3 * end_x)
            y = ((1 - t) ** 3 * start_y
                 + 3 * (1 - t) ** 2 * t * ctrl1_y
                 + 3 * (1 - t) * t ** 2 * ctrl2_y
                 + t ** 3 * end_y)
            await page.mouse.move(int(x), int(y))
            # ease-in-out variable speed: slow at start/end, fast in middle
            base_delay = 0.002 + 0.010 * math.sin(math.pi * t)
            await asyncio.sleep(base_delay + random.uniform(0, 0.003))

    async def reading_pause(self, min_sec: float = 2.0, max_sec: float = 8.0) -> None:
        """Simulate a reading pause."""
        duration = random.uniform(min_sec, max_sec)
        logger.debug(f"Reading pause: {duration:.1f}s")
        await asyncio.sleep(duration)

    @staticmethod
    async def inject_timing_noise(page: Page, max_offset_ms: int = 5) -> None:
        """Inject timing noise to defend against JS timing-based fingerprint detection.

        Adds random offsets to Date.now() and performance.now(),
        making timing-difference fingerprint calculations slightly different each time.
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
