"""Persistent single CDP session manager.

Key anti-detection rule: do not frequently attach/detach CDP sessions.

Every Target.attachToTarget / Target.detachFromTarget leaves detectable traces
in the browser's internal state. Boss Zhipin (Akamai Bot Manager + Tongdun
Technology) can observe these patterns.

Strategy:
  - Connect once, maintain a single persistent session throughout the task lifecycle
  - Operate on the same page throughout, never create new context/page
  - Only execute a single context.close() at task end
"""
import logging

try:
    from patchright.async_api import Browser, BrowserContext, Page
    _HAS_PATCHRIGHT = True
except ImportError:
    from playwright.async_api import Browser, BrowserContext, Page
    _HAS_PATCHRIGHT = False

logger = logging.getLogger(__name__)


class PersistentCDPSession:
    """
    Maintains a single CDP session across the entire task lifecycle.

    Usage:
        session = PersistentCDPSession(browser)
        page = await session.initialize()
        # Use page for operations
        await session.navigate("https://www.zhipin.com")
        # Task ends
        await session.close()
    """

    def __init__(self, browser: Browser):
        self._browser = browser
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._initialized = False

    async def initialize(
        self,
        viewport_width: int = 1920,
        viewport_height: int = 1080,
        locale: str = "zh-CN",
        timezone_id: str = "Asia/Shanghai",
        extra_http_headers: dict | None = None,
    ) -> Page:
        """
        Create the only context and page -- no new sessions created afterward.

        Args:
            viewport_width/height: Screen resolution (matches CloakBrowser C++ fingerprint)
            locale: Browser language (consistent with proxy IP geolocation)
            timezone_id: Timezone (consistent with proxy IP geolocation)
        """
        if self._initialized:
            logger.warning("PersistentCDPSession already initialized, returning existing page")
            return self._page

        # Single context = single CDP session
        # CloakBrowser's C++ patches handle UA, Canvas, WebGL fingerprints
        # Here we only set parameters consistent with IP geolocation
        self._context = await self._browser.new_context(
            viewport={"width": viewport_width, "height": viewport_height},
            locale=locale,
            timezone_id=timezone_id,
            extra_http_headers=extra_http_headers or {},
            # Do not set user_agent -- let CloakBrowser C++ layer handle it
        )

        self._page = await self._context.new_page()
        self._initialized = True

        logger.info(f"PersistentCDPSession initialized: viewport={viewport_width}x{viewport_height}, "
                    f"locale={locale}, tz={timezone_id}")
        return self._page

    async def get_page(self) -> Page:
        """Always return the same page -- never create a new session."""
        if not self._initialized or not self._page:
            return await self.initialize()
        return self._page

    async def navigate(self, url: str, wait_until: str = "networkidle") -> Page:
        """Navigate within the existing session (no new page created)."""
        page = await self.get_page()
        try:
            await page.goto(url, wait_until=wait_until, timeout=30_000)
        except Exception as e:
            logger.warning(f"Navigation to {url} failed: {e}, retrying with domcontentloaded")
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        return page

    async def screenshot(self, path: str | None = None, type: str = "png") -> bytes:
        """Take a screenshot of the current page."""
        page = await self.get_page()
        return await page.screenshot(path=path, type=type)

    async def close(self) -> None:
        """Single cleanup at end of lifecycle (no frequent detach)."""
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
    def page(self) -> Page | None:
        return self._page
