"""
行为模拟层：模拟真人操作的"不完美性"，对抗同盾科技行为分析。

同盾科技分析：
  - 鼠标轨迹熵值（直线运动 = 机器人）
  - 滚动模式（匀速 = 机器人）
  - 点击时序（固定间隔 = 机器人）
  - 打字节奏（等速 = 机器人）
  - 页面停留时间分布

对策：
  - 变速打字 + 偶尔退格（5% 概率）
  - 非匀速滚动 + 随机停顿 + 偶尔回滚（20% 概率）
  - 预热浏览（先访问百度/新闻网站，建立正常用户基线）
  - 随机长停顿模拟"阅读"行为
"""
import asyncio
import logging
import math
import random
from typing import Optional

from patchright.async_api import Page

logger = logging.getLogger(__name__)


class HumanBehaviorSimulator:
    """模拟真人不完美行为，对抗行为分析反爬"""

    # 预热 URL 列表：先建立正常用户基线（精简到2个，减少预热时间）
    WARMUP_URLS = [
        "https://www.baidu.com",
        "https://www.zhipin.com",  # Boss 直聘首页预热（不直接搜索）
    ]

    async def warmup_browsing(
        self,
        page: Page,
        urls: Optional[list[str]] = None,
    ) -> None:
        """
        预热浏览：在 Akamai/同盾行为模型中建立"正常用户"基线。

        流程：
          Step 1: 访问百度 → 搜索 → 浏览结果 (3-5 min)
          Step 2: 访问新闻网站 → 随机浏览 (2-3 min)
          Step 3: 访问 zhipin.com 首页 → 不搜索，只浏览推荐 (2-3 min)
          Step 4: 正式开始任务
        """
        warmup_list = urls or self.WARMUP_URLS

        for url in warmup_list:
            try:
                logger.info(f"Warmup: visiting {url}")
                await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
                await self._random_scroll(page)
                await asyncio.sleep(random.uniform(2, 5))

                # 随机鼠标游走
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
        """
        真人打字模拟：变速 + 偶尔退格 + 停顿思考。

        特征：
          - 基础速度：50-250ms/字符
          - 10% 概率长停顿（500-1500ms）模拟"思考"
          - 5% 概率打错再退格
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
            # 10% 概率长停顿（模拟思考）
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
        """
        真人点击模拟：先悬停 → 随机延迟 → 点击。
        """
        element = page.locator(selector)

        if pre_hover:
            # 先悬停在元素上
            await element.hover()
            await asyncio.sleep(random.uniform(0.2, 0.8))

        await element.click()
        await asyncio.sleep(random.uniform(0.3, 1.0))

    async def _random_scroll(
        self,
        page: Page,
        scroll_count: Optional[int] = None,
    ) -> None:
        """
        非匀速滚动：变速 + 随机停顿 + 20% 概率回滚。
        """
        count = scroll_count or random.randint(2, 5)

        for _ in range(count):
            distance = random.randint(100, 600)
            await page.evaluate(f"window.scrollBy(0, {distance})")
            await asyncio.sleep(random.uniform(0.3, 2.0))

            # 20% 概率回滚（真人经常这样：看到感兴趣的往上翻）
            if random.random() < 0.2:
                back = random.randint(50, 200)
                await page.evaluate(f"window.scrollBy(0, -{back})")
                await asyncio.sleep(random.uniform(0.3, 1.2))

    async def _random_mouse_move(self, page: Page) -> None:
        """随机鼠标游走（使用贝塞尔曲线模拟真人轨迹）"""
        viewport = page.viewport_size or {"width": 1920, "height": 1080}
        moves = random.randint(1, 2)

        # 起始位置
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
        """沿三次贝塞尔曲线移动鼠标（模拟人类手部运动轨迹）"""
        # 生成 2 个随机控制点，偏移直线路径
        ctrl1_x = start_x + (end_x - start_x) * 0.25 + random.randint(-80, 80)
        ctrl1_y = start_y + (end_y - start_y) * 0.25 + random.randint(-80, 80)
        ctrl2_x = start_x + (end_x - start_x) * 0.75 + random.randint(-80, 80)
        ctrl2_y = start_y + (end_y - start_y) * 0.75 + random.randint(-80, 80)

        for i in range(steps + 1):
            t = i / steps
            # 三次贝塞尔公式
            x = ((1 - t) ** 3 * start_x
                 + 3 * (1 - t) ** 2 * t * ctrl1_x
                 + 3 * (1 - t) * t ** 2 * ctrl2_x
                 + t ** 3 * end_x)
            y = ((1 - t) ** 3 * start_y
                 + 3 * (1 - t) ** 2 * t * ctrl1_y
                 + 3 * (1 - t) * t ** 2 * ctrl2_y
                 + t ** 3 * end_y)
            await page.mouse.move(int(x), int(y))
            # ease-in-out 变速：起点和终点慢，中间快
            base_delay = 0.002 + 0.010 * math.sin(math.pi * t)
            await asyncio.sleep(base_delay + random.uniform(0, 0.003))

    async def reading_pause(self, min_sec: float = 2.0, max_sec: float = 8.0) -> None:
        """模拟阅读停顿"""
        duration = random.uniform(min_sec, max_sec)
        logger.debug(f"Reading pause: {duration:.1f}s")
        await asyncio.sleep(duration)

    async def natural_browse_zhipin(self, page: Page, keyword: str, city: str = "") -> None:
        """
        Boss 直聘专项：模拟自然搜索流程（非直达目标）。

        流程：首页 → 随机浏览推荐 → 搜索框 → 输入（真人打字）→ 搜索
        """
        # 1. 访问首页
        await page.goto("https://www.zhipin.com", wait_until="networkidle", timeout=30_000)
        await self.reading_pause(2, 5)

        # 2. 随机滚动首页（模拟浏览推荐职位）
        await self._random_scroll(page, scroll_count=2)
        await self.reading_pause(1, 3)

        # 3. 找到搜索框并输入（真人打字）
        search_selectors = [
            "input[name='query']",
            "input[placeholder*='搜索']",
            "input[placeholder*='职位']",
            ".search-input input",
        ]
        for sel in search_selectors:
            try:
                if await page.locator(sel).count() > 0:
                    await self.human_type(page, sel, keyword)
                    break
            except Exception:
                continue

        await asyncio.sleep(random.uniform(0.5, 1.5))

        # 4. 回车搜索
        await page.keyboard.press("Enter")
        await asyncio.sleep(random.uniform(2, 4))

        # 5. 搜索结果页随机浏览
        await self._random_scroll(page, scroll_count=2)
        await self.reading_pause(2, 5)

    @staticmethod
    async def inject_timing_noise(page: Page, max_offset_ms: int = 5) -> None:
        """
        注入定时器噪声，防御基于 JS 时序的指纹检测。

        在 Date.now() 和 performance.now() 上加随机偏移，
        使得基于时间差的指纹计算每次都略有不同。
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
