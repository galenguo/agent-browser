"""
StealthEnhancer — 反侦察增强器（从 src/core/stealth_enhancer.py 移植）

纯 Python 实现，零重依赖（仅 asyncio/random）。
为 Skill 包提供与 src/ 一致的隐匿增强。

整合能力：
- 人类操作延迟（按操作类型差异化）
- 贝塞尔曲线鼠标移动
- 真人打字模拟（变速 + 退格 + 停顿）
- 非匀速滚动
- 预热浏览
- JS 定时器噪声注入
"""
import asyncio
import math
import random
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class StealthEnhancer:
    """
    反侦察增强器，注入人类行为模式到每次操作。

    两种集成方式：
    - LLM 模式：通过 pre_action/post_action 集成到 BrowserPageHandle
    - Agent 模式：通过 stealth_actions.py 覆盖 browser-use 默认操作
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

    # ── 操作延迟 ──

    async def pre_action(self, action_type: str = "general") -> None:
        """
        操作前的人类延迟。不同操作类型有不同延迟范围。
        - navigate: 0.5-1.5s
        - click: 0.1-0.3s
        - input: 0.3-0.8s
        - scroll: 0.3-1.0s
        - extract: 0.0s
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
            await asyncio.sleep(random.uniform(low, high))

    async def post_action(self, action_type: str = "general") -> None:
        """操作后短暂停顿"""
        await asyncio.sleep(random.uniform(0.05, 0.2))

    # ── 鼠标移动 ──

    async def random_mouse_move(self, page) -> None:
        """贝塞尔曲线鼠标移动，对抗鼠标轨迹熵值分析"""
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
        """沿三次贝塞尔曲线移动鼠标"""
        ctrl1_x = start_x + (end_x - start_x) * 0.25 + random.randint(-80, 80)
        ctrl1_y = start_y + (end_y - start_y) * 0.25 + random.randint(-80, 80)
        ctrl2_x = start_x + (end_x - start_x) * 0.75 + random.randint(-80, 80)
        ctrl2_y = start_y + (end_y - start_y) * 0.75 + random.randint(-80, 80)

        for i in range(steps + 1):
            t = i / steps
            x = (
                (1 - t) ** 3 * start_x
                + 3 * (1 - t) ** 2 * t * ctrl1_x
                + 3 * (1 - t) * t**2 * ctrl2_x
                + t**3 * end_x
            )
            y = (
                (1 - t) ** 3 * start_y
                + 3 * (1 - t) ** 2 * t * ctrl1_y
                + 3 * (1 - t) * t**2 * ctrl2_y
                + t**3 * end_y
            )
            await page.mouse.move(int(x), int(y))
            base_delay = 0.005 + 0.02 * math.sin(math.pi * t)
            await asyncio.sleep(base_delay + random.uniform(0, 0.008))

    # ── 人类打字 ──

    async def human_type(self, page, selector: str, text: str, clear_first: bool = True) -> None:
        """
        真人打字模拟：50-250ms/字符 + 10% 长停顿 + 5% 退格。
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
            # 5% 概率打错再退格
            if random.random() < 0.05:
                wrong_char = random.choice("abcdef1234567890")
                await page.keyboard.type(wrong_char)
                await asyncio.sleep(random.uniform(0.08, 0.25))
                await page.keyboard.press("Backspace")
                await asyncio.sleep(random.uniform(0.15, 0.4))

            # 变速打字
            delay_ms = random.randint(50, 250)
            # 10% 概率长停顿
            if random.random() < 0.1:
                delay_ms += random.randint(500, 1500)
            await page.keyboard.type(char, delay=delay_ms)

    # ── 人类滚动 ──

    async def human_scroll(self, page, scroll_count: Optional[int] = None) -> None:
        """非匀速滚动 + 随机停顿 + 20% 回滚"""
        if not self._human_scroll:
            return

        count = scroll_count or random.randint(2, 5)
        for _ in range(count):
            distance = random.randint(100, 600)
            await page.evaluate(f"window.scrollBy(0, {distance})")
            await asyncio.sleep(random.uniform(0.5, 3.0))
            # 20% 回滚
            if random.random() < 0.2:
                back = random.randint(50, 200)
                await page.evaluate(f"window.scrollBy(0, -{back})")
                await asyncio.sleep(random.uniform(0.3, 1.2))

    # ── 阅读停顿 ──

    async def reading_pause(self, min_sec: float = 2.0, max_sec: float = 8.0) -> None:
        duration = random.uniform(min_sec, max_sec)
        logger.debug(f"Reading pause: {duration:.1f}s")
        await asyncio.sleep(duration)

    # ── 预热浏览 ──

    WARMUP_URLS = [
        "https://www.baidu.com",
        "https://www.163.com",
    ]

    async def warmup_browsing(self, page, urls: Optional[list] = None) -> None:
        """预热浏览：建立"正常用户"基线"""
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

    # ── JS 定时器噪声 ──

    @staticmethod
    async def inject_timing_noise(page, max_offset_ms: int = 5) -> None:
        """注入 JS 定时器噪声，防御时序指纹检测"""
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
