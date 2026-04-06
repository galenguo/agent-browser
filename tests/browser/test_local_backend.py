"""
Phase 2: LocalCDPBackend 集成测试

测试目标：
- B1.1 CDP 连接
- B1.2 页面导航
- B1.3 DOM Snapshot
- B1.4 Click 操作
- B1.5 Fill 操作
- B1.6 StealthEnhancer 集成（反检测验证）

前置条件：CloakBrowser 运行在 127.0.0.1:19222
"""

import asyncio

import pytest


@pytest.mark.requires_browser
class TestCloakBrowserConnection:
    """B1.1 CDP 连接测试"""

    @pytest.mark.asyncio
    async def test_cdp_endpoint_available(self):
        """CDP 端点可达"""
        import aiohttp

        async with (
            aiohttp.ClientSession() as session,
            session.get("http://127.0.0.1:19222/json/version", timeout=aiohttp.ClientTimeout(total=5)) as resp,
        ):
            assert resp.status == 200
            data = await resp.json()
            assert "webSocketDebuggerUrl" in data

    @pytest.mark.asyncio
    async def test_playwright_can_connect(self):
        """Playwright 可以连接"""
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:19222")
            assert browser is not None
            contexts = browser.contexts
            assert contexts is not None
            await browser.close()


class TestAntiDetection:
    """B1.6 反检测验证"""

    @pytest.mark.asyncio
    async def test_navigator_webdriver_false(self):
        """navigator.webdriver 应该是 false/undefined"""
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:19222")
            context = await browser.new_context()
            page = await context.new_page()

            await page.goto("https://example.com")
            webdriver = await page.evaluate("navigator.webdriver")

            assert webdriver is False or webdriver is None, f"navigator.webdriver = {webdriver}"

            await context.close()
            await browser.close()

    @pytest.mark.asyncio
    async def test_no_playwright_binding(self):
        """window.__playwright__binding__ 应该是 undefined"""
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:19222")
            context = await browser.new_context()
            page = await context.new_page()

            await page.goto("https://example.com")
            binding = await page.evaluate("typeof window.__playwright__binding__")

            assert binding == "undefined", f"__playwright__binding__ type = {binding}"

            await context.close()
            await browser.close()

    @pytest.mark.asyncio
    async def test_no_cdc_vars(self):
        """CDC 变量应该被清理"""
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:19222")
            context = await browser.new_context()
            page = await context.new_page()

            await page.goto("https://example.com")
            cdc_vars = await page.evaluate("""
                Object.keys(window).filter(k => k.includes('cdc') || k.includes('CDC'))
            """)

            assert len(cdc_vars) == 0, f"CDC vars found: {cdc_vars}"

            await context.close()
            await browser.close()


class TestPageNavigation:
    """B1.2 页面导航测试"""

    @pytest.mark.asyncio
    async def test_navigate_to_url(self):
        """导航到 URL"""
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:19222")
            context = await browser.new_context()
            page = await context.new_page()

            await page.goto("https://example.com", wait_until="domcontentloaded")

            url = page.url
            assert "example.com" in url

            await context.close()
            await browser.close()

    @pytest.mark.asyncio
    async def test_get_page_title(self):
        """获取页面标题"""
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:19222")
            context = await browser.new_context()
            page = await context.new_page()

            await page.goto("https://example.com", wait_until="domcontentloaded")
            title = await page.title()

            assert len(title) > 0

            await context.close()
            await browser.close()

    @pytest.mark.asyncio
    async def test_get_current_url(self):
        """获取当前 URL"""
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:19222")
            context = await browser.new_context()
            page = await context.new_page()

            await page.goto("https://example.com")
            url = page.url

            assert url.startswith("https://")

            await context.close()
            await browser.close()


class TestDOMSnapshot:
    """B1.3 DOM Snapshot 测试"""

    @pytest.mark.asyncio
    async def test_extract_elements(self):
        """提取页面元素"""
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:19222")
            context = await browser.new_context()
            page = await context.new_page()

            await page.goto("https://example.com", wait_until="domcontentloaded")

            # 获取所有链接和按钮
            elements = await page.evaluate("""
                () => {
                    const results = [];
                    document.querySelectorAll('a, button, input').forEach((el, i) => {
                        results.push({
                            ref: '@e' + i,
                            tag: el.tagName.toLowerCase(),
                            text: (el.textContent || el.value || '').substring(0, 50)
                        });
                    });
                    return results;
                }
            """)

            assert len(elements) > 0

            # 验证 ref 格式
            for elem in elements:
                assert elem["ref"].startswith("@e")

            await context.close()
            await browser.close()

    @pytest.mark.asyncio
    async def test_extract_interactive_elements_only(self):
        """只提取可交互元素"""
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:19222")
            context = await browser.new_context()
            page = await context.new_page()

            await page.goto("https://example.com", wait_until="domcontentloaded")

            # 获取可交互元素
            elements = await page.evaluate("""
                () => {
                    const selectors = 'button, a, input, textarea, select, [role="button"], [onclick]';
                    const results = [];
                    document.querySelectorAll(selectors).forEach((el, i) => {
                        results.push({
                            ref: '@e' + i,
                            tag: el.tagName.toLowerCase(),
                            is_visible: el.offsetParent !== null
                        });
                    });
                    return results;
                }
            """)

            # 验证所有元素都是可交互类型
            for elem in elements:
                assert elem["tag"] in ["button", "a", "input", "textarea", "select"]

            await context.close()
            await browser.close()


class TestClickOperation:
    """B1.4 Click 操作测试"""

    @pytest.mark.asyncio
    async def test_click_element(self):
        """点击元素"""
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:19222")
            context = await browser.new_context()
            page = await context.new_page()

            await page.goto("https://example.com")

            # 点击 body 元素（页面总是有）
            await page.click("body", timeout=5000)

            await context.close()
            await browser.close()


class TestFillOperation:
    """B1.5 Fill 操作测试"""

    @pytest.mark.asyncio
    async def test_fill_input_field(self):
        """填充输入框"""
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:19222")
            context = await browser.new_context()
            page = await context.new_page()

            # 使用 DuckDuckGo（比百度更稳定）
            await page.goto("https://duckduckgo.com", wait_until="domcontentloaded")

            # 查找搜索框
            input_box = page.locator("input[name='q']")
            await input_box.wait_for(timeout=10000)

            await input_box.fill("test query")
            value = await input_box.input_value()

            assert value == "test query"

            await context.close()
            await browser.close()

    @pytest.mark.asyncio
    async def test_evaluate_javascript(self):
        """执行 JavaScript"""
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:19222")
            context = await browser.new_context()
            page = await context.new_page()

            await page.goto("https://example.com")
            result = await page.evaluate("1 + 1")

            assert result == 2

            await context.close()
            await browser.close()


class TestConcurrentOperations:
    """并发操作测试"""

    @pytest.mark.asyncio
    async def test_concurrent_javascript_eval(self):
        """并发执行 JavaScript"""
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:19222")
            context = await browser.new_context()
            page = await context.new_page()

            await page.goto("https://example.com")

            # 并发执行多个 evaluate
            tasks = [
                page.evaluate("1 + 1"),
                page.evaluate("2 + 2"),
                page.evaluate("3 + 3"),
            ]
            results = await asyncio.gather(*tasks)

            assert results == [2, 4, 6]

            await context.close()
            await browser.close()


class TestErrorHandling:
    """错误处理测试"""

    @pytest.mark.asyncio
    async def test_navigate_invalid_url(self):
        """导航到无效 URL"""
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:19222")
            context = await browser.new_context()
            page = await context.new_page()

            with pytest.raises(Exception, match=""):
                await page.goto("not-a-valid-url", timeout=5000)

            await context.close()
            await browser.close()

    @pytest.mark.asyncio
    async def test_click_nonexistent_element(self):
        """点击不存在元素"""
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:19222")
            context = await browser.new_context()
            page = await context.new_page()

            await page.goto("https://example.com")

            with pytest.raises(Exception, match=""):
                await page.click("#nonexistent-element-xyz", timeout=5000)

            await context.close()
            await browser.close()
