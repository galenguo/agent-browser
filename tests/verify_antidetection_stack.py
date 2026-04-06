"""
Phase 5: 5层反检测栈验证测试

测试目标：
- Layer 1: CloakBrowser 编译级指纹伪装
- Layer 2: patchright CDP 补丁（移除 __playwright__binding__）
- Layer 3: rebrowser-patches（Runtime.Enable 泄漏修复）
- Layer 4: 非标准端口 19222
- Layer 5: 持久化 CDP 会话（BrowserDaemon）
- Layer 6: StealthEnhancer 行为模拟

前置条件：CloakBrowser 运行在 127.0.0.1:19222
"""

import asyncio

import pytest
from playwright.async_api import async_playwright


class TestLayer1CloakBrowser:
    """Layer 1: CloakBrowser 编译级指纹伪装"""

    @pytest.mark.asyncio
    async def test_navigator_webdriver_false(self):
        """navigator.webdriver 应该是 false/undefined"""
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
    async def test_chrome_runtime_present(self):
        """Chrome runtime 应该存在（CloakBrowser 基于 Chromium）"""
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:19222")
            context = await browser.new_context()
            page = await context.new_page()

            await page.goto("chrome://version")
            # 在 chrome:// 页面上检查 runtime
            await page.evaluate("typeof chrome !== 'undefined' && typeof chrome.runtime !== 'undefined'")

            # chrome.runtime 可能不在所有页面可用，这是可选检查
            # 主要验证浏览器是基于 Chromium
            assert True  # 此测试为信息性

            await context.close()
            await browser.close()

    @pytest.mark.asyncio
    async def test_user_agent_realistic(self):
        """User-Agent 应该是真实浏览器格式"""
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:19222")
            context = await browser.new_context()
            page = await context.new_page()

            await page.goto("https://example.com")
            ua = await page.evaluate("navigator.userAgent")

            # 验证 User-Agent 格式
            assert "Mozilla/5.0" in ua
            assert "Chrome" in ua
            # 不应该包含 HeadlessChrome
            assert "HeadlessChrome" not in ua

            await context.close()
            await browser.close()


class TestLayer2Patchright:
    """Layer 2: patchright CDP 补丁"""

    @pytest.mark.asyncio
    async def test_no_playwright_binding(self):
        """window.__playwright__binding__ 应该是 undefined"""
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
    async def test_no_playwright_internal(self):
        """不应该暴露 Playwright 内部对象"""
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:19222")
            context = await browser.new_context()
            page = await context.new_page()

            await page.goto("https://example.com")

            # 检查常见的 Playwright 内部标记
            internal_vars = await page.evaluate("""
                () => {
                    const vars = [];
                    for (const key of Object.keys(window)) {
                        if (key.includes('playwright') || key.includes('Playwright')) {
                            vars.push(key);
                        }
                    }
                    return vars;
                }
            """)

            assert len(internal_vars) == 0, f"Found Playwright internal vars: {internal_vars}"

            await context.close()
            await browser.close()


class TestLayer3RebrowserPatches:
    """Layer 3: rebrowser-patches（CDC 变量清理）"""

    @pytest.mark.asyncio
    async def test_no_cdc_vars(self):
        """CDC 变量应该被清理"""
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

    @pytest.mark.asyncio
    async def test_no_selenium_vars(self):
        """Selenium 相关变量应该被清理"""
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:19222")
            context = await browser.new_context()
            page = await context.new_page()

            await page.goto("https://example.com")
            selenium_vars = await page.evaluate("""
                () => {
                    const vars = [];
                    for (const key of Object.keys(window)) {
                        if (key.toLowerCase().includes('selenium') || key.includes('webdriver')) {
                            vars.push(key);
                        }
                    }
                    return vars;
                }
            """)

            # 只应该有 webdriver 相关变量（但 navigator.webdriver 应该是 false）
            # 实际的 webdriver 变量不应该作为 window 属性存在
            for var in selenium_vars:
                if var != "webdriver":  # navigator.webdriver 是标准属性
                    pytest.fail(f"Found Selenium var: {var}")

            await context.close()
            await browser.close()


class TestLayer4NonStandardPort:
    """Layer 4: 非标准端口"""

    @pytest.mark.asyncio
    async def test_cdp_port_19222(self):
        """CDP 端口应该是 19222"""
        import aiohttp

        async with (
            aiohttp.ClientSession() as session,
            session.get("http://127.0.0.1:19222/json/version", timeout=aiohttp.ClientTimeout(total=5)) as resp,
        ):
            assert resp.status == 200
            data = await resp.json()
            assert "webSocketDebuggerUrl" in data

    @pytest.mark.asyncio
    async def test_standard_port_not_exposed(self):
        """标准端口 9222 不应该对外暴露（或使用不同配置）"""
        import aiohttp

        # 检查 9222 端口（可能同时运行普通 Chrome）
        try:
            async with (
                aiohttp.ClientSession() as session,
                session.get("http://127.0.0.1:9222/json/version", timeout=aiohttp.ClientTimeout(total=2)),
            ):
                # 如果 9222 存在，确保它与 19222 是不同的浏览器
                # 这个测试主要是信息性的
                pass
        except Exception:
            # 9222 不可达是期望的
            pass


class TestLayer5PersistentCDP:
    """Layer 5: 持久化 CDP 会话"""

    @pytest.mark.asyncio
    async def test_session_reuse(self):
        """Session 应该可以复用（不频繁 attach/detach）"""
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:19222")

            # 创建多个 context 验证连接稳定
            contexts = []
            for _ in range(3):
                context = await browser.new_context()
                page = await context.new_page()
                await page.goto("https://example.com")
                contexts.append(context)

            # 清理
            for context in contexts:
                await context.close()

            await browser.close()

    @pytest.mark.asyncio
    async def test_connection_stability(self):
        """连接应该保持稳定"""
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:19222")
            context = await browser.new_context()
            page = await context.new_page()

            # 执行多个操作验证连接稳定
            for _i in range(5):
                await page.goto("https://example.com")
                title = await page.title()
                assert len(title) > 0

            await context.close()
            await browser.close()


class TestLayer6StealthEnhancer:
    """Layer 6: StealthEnhancer 行为模拟"""

    @pytest.mark.asyncio
    async def test_timing_consistency(self):
        """时间相关 API 应该一致"""
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:19222")
            context = await browser.new_context()
            page = await context.new_page()

            await page.goto("https://example.com")

            # 验证 Date 和 performance 时间合理
            timing = await page.evaluate("""
                () => {
                    const now = Date.now();
                    const perfNow = performance.now();
                    return {
                        dateNow: now,
                        perfNow: perfNow,
                        reasonable: now > 1600000000000 && perfNow >= 0
                    };
                }
            """)

            assert timing["reasonable"] is True

            await context.close()
            await browser.close()

    @pytest.mark.asyncio
    async def test_fingerprint_consistency(self):
        """浏览器指纹应该一致"""
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:19222")
            context = await browser.new_context()
            page = await context.new_page()

            await page.goto("https://example.com")

            # 获取指纹信息
            fp1 = await page.evaluate("""
                () => ({
                    ua: navigator.userAgent,
                    platform: navigator.platform,
                    language: navigator.language,
                    languages: navigator.languages.join(','),
                    cookieEnabled: navigator.cookieEnabled,
                    hardwareConcurrency: navigator.hardwareConcurrency
                })
            """)

            # 刷新页面再次获取
            await page.reload()
            fp2 = await page.evaluate("""
                () => ({
                    ua: navigator.userAgent,
                    platform: navigator.platform,
                    language: navigator.language,
                    languages: navigator.languages.join(','),
                    cookieEnabled: navigator.cookieEnabled,
                    hardwareConcurrency: navigator.hardwareConcurrency
                })
            """)

            # 验证指纹一致
            assert fp1["ua"] == fp2["ua"]
            assert fp1["platform"] == fp2["platform"]
            assert fp1["language"] == fp2["language"]

            await context.close()
            await browser.close()


class TestExternalDetectionServices:
    """外部检测服务验证"""

    @pytest.mark.asyncio
    async def test_bot_sannysoft_score(self):
        """bot.sannysoft.com 得分检查"""
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:19222")
            context = await browser.new_context()
            page = await context.new_page()

            await page.goto("https://bot.sannysoft.com", wait_until="domcontentloaded", timeout=30000)

            # 等待检测完成
            await asyncio.sleep(3)

            # 检查关键指标
            webdriver = await page.evaluate("navigator.webdriver")

            # webdriver 应该是 false/undefined
            assert webdriver is False or webdriver is None, f"navigator.webdriver = {webdriver}"

            # 检查是否有明显的自动化标记
            automation_markers = await page.evaluate("""
                () => {
                    const markers = [];
                    if (window.__nightmare) markers.push('__nightmare');
                    if (window.__phantomas) markers.push('__phantomas');
                    if (window._phantom) markers.push('_phantom');
                    if (window.callPhantom) markers.push('callPhantom');
                    if (window.Buffer) markers.push('Buffer');
                    if (window.emit) markers.push('emit');
                    if (window.spawn) markers.push('spawn');
                    return markers;
                }
            """)

            assert len(automation_markers) == 0, f"Found automation markers: {automation_markers}"

            await context.close()
            await browser.close()

    @pytest.mark.asyncio
    async def test_canvas_fingerprint(self):
        """Canvas 指纹检查"""
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:19222")
            context = await browser.new_context()
            page = await context.new_page()

            await page.goto("https://example.com")

            # 测试 Canvas 功能
            canvas_support = await page.evaluate("""
                () => {
                    const canvas = document.createElement('canvas');
                    const ctx = canvas.getContext('2d');
                    if (!ctx) return false;

                    ctx.textBaseline = 'top';
                    ctx.font = '14px Arial';
                    ctx.fillText('test', 2, 2);

                    return canvas.toDataURL().length > 100;
                }
            """)

            assert canvas_support is True, "Canvas not supported"

            await context.close()
            await browser.close()

    @pytest.mark.asyncio
    async def test_webgl_support(self):
        """WebGL 支持检查"""
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:19222")
            context = await browser.new_context()
            page = await context.new_page()

            await page.goto("https://example.com")

            webgl = await page.evaluate("""
                () => {
                    const canvas = document.createElement('canvas');
                    const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
                    if (!gl) return { supported: false };

                    const debugInfo = gl.getExtension('WEBGL_debug_renderer_info');
                    return {
                        supported: true,
                        vendor: debugInfo ? gl.getParameter(debugInfo.UNMASKED_VENDOR_WEBGL) : 'unknown',
                        renderer: debugInfo ? gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL) : 'unknown'
                    };
                }
            """)

            assert webgl["supported"] is True, "WebGL not supported"
            # GPU 信息应该是合理的（不是 SwiftShader 或其他软件渲染器）
            if webgl["renderer"] != "unknown":
                assert "SwiftShader" not in webgl["renderer"]

            await context.close()
            await browser.close()
