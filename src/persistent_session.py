"""
持久单 CDP 会话管理器。

关键反检测规则：不要频繁 attach/detach CDP 会话。

每次 Target.attachToTarget / Target.detachFromTarget 都会在浏览器内部状态
中留下可检测痕迹。Boss 直聘（Akamai Bot Manager + 同盾科技）可以观察这些模式。

策略：
  - 连接一次，在整个任务生命周期中维持单一持久会话
  - 全程操作同一个 page，不新建 context/page
  - 只在任务结束时执行单次 context.close()
"""
import asyncio
import logging
from typing import Optional

from patchright.async_api import Browser, BrowserContext, Page

logger = logging.getLogger(__name__)


class PersistentCDPSession:
    """
    维持单一 CDP 会话，贯穿整个任务生命周期。

    Usage:
        session = PersistentCDPSession(browser)
        page = await session.initialize()
        # 使用 page 进行操作
        await session.navigate("https://www.zhipin.com")
        # 任务结束
        await session.close()
    """

    def __init__(self, browser: Browser):
        self._browser = browser
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._initialized = False

    async def initialize(
        self,
        viewport_width: int = 1920,
        viewport_height: int = 1080,
        locale: str = "zh-CN",
        timezone_id: str = "Asia/Shanghai",
        extra_http_headers: Optional[dict] = None,
    ) -> Page:
        """
        创建唯一 context 和 page — 全程不再创建新会话。

        Args:
            viewport_width/height: 屏幕分辨率（配合 CloakBrowser C++ 指纹）
            locale: 浏览器语言（与代理 IP 地理位置一致）
            timezone_id: 时区（与代理 IP 地理位置一致）
        """
        if self._initialized:
            logger.warning("PersistentCDPSession already initialized, returning existing page")
            return self._page

        # 单个 context = 单个 CDP 会话
        # CloakBrowser 的 C++ 补丁负责处理 UA、Canvas、WebGL 等指纹
        # 这里只设置与 IP 地理位置一致的参数
        self._context = await self._browser.new_context(
            viewport={"width": viewport_width, "height": viewport_height},
            locale=locale,
            timezone_id=timezone_id,
            extra_http_headers=extra_http_headers or {},
            # 不设置 user_agent，让 CloakBrowser C++ 层处理
        )

        self._page = await self._context.new_page()
        self._initialized = True

        logger.info(f"PersistentCDPSession initialized: viewport={viewport_width}x{viewport_height}, "
                    f"locale={locale}, tz={timezone_id}")
        return self._page

    async def get_page(self) -> Page:
        """始终返回同一 page — 绝不创建新会话"""
        if not self._initialized or not self._page:
            return await self.initialize()
        return self._page

    async def navigate(self, url: str, wait_until: str = "networkidle") -> Page:
        """在现有会话中导航（不新建 page）"""
        page = await self.get_page()
        try:
            await page.goto(url, wait_until=wait_until, timeout=30_000)
        except Exception as e:
            logger.warning(f"Navigation to {url} failed: {e}, retrying with domcontentloaded")
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        return page

    async def screenshot(self, path: Optional[str] = None, type: str = "png") -> bytes:
        """截取当前页面截图"""
        page = await self.get_page()
        return await page.screenshot(path=path, type=type)

    async def close(self) -> None:
        """生命周期结束时单次清理（不频繁 detach）"""
        if self._context:
            try:
                await self._context.close()
                logger.info("PersistentCDPSession closed")
            except Exception as e:
                logger.warning(f"Session close error: {e}")
            finally:
                self._context = None
                self._page = None
                self._initialized = False

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def page(self) -> Optional[Page]:
        return self._page
