"""
快速验证脚本 — 不需要 CloakBrowser，测试其他组件是否正常工作。

用法：
    cd /Users/galen/OpenSource/browser-controller/agent-browser
    python tests/test_anti_detection.py
"""
import asyncio
import logging
import os
import sys

# 激活 rebrowser Runtime.Enable addBinding 修复（环境变量方式）
os.environ.setdefault("REBROWSER_PATCHES_RUNTIME_FIX_MODE", "addBinding")

from patchright.async_api import async_playwright

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

DETECTION_TESTS = [
    ("navigator.webdriver", "() => navigator.webdriver"),
    ("__playwright__binding__", "() => !!window.__playwright__binding__"),
    ("window.cdc_ variables", "() => Object.keys(window).filter(k => k.startsWith('cdc_')).length > 0"),
    ("automation flag", "() => navigator.userAgent.includes('HeadlessChrome')"),
    ("chrome.runtime", "() => !!(window.chrome && window.chrome.runtime)"),
]


async def test_with_patchright(browser_path: str | None = None):
    """使用 patchright 测试反检测能力"""
    logger.info(f"Testing with patchright (browser={browser_path or 'default chromium'})")

    async with async_playwright() as pw:
        if browser_path and os.path.exists(browser_path):
            browser = await pw.chromium.launch(
                executable_path=browser_path,
                headless=False,
                args=[
                    "--remote-debugging-port=19222",
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ],
                ignore_default_args=["--enable-automation"],
            )
        else:
            # 无 CloakBrowser 时用默认 Chromium 测试 patchright 效果
            logger.warning("CloakBrowser not found, testing with default Chromium")
            browser = await pw.chromium.launch(
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
                ignore_default_args=["--enable-automation"],
            )

        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )
        page = await context.new_page()

        try:
            await page.goto("about:blank")
            logger.info("\n── Anti-Detection Test Results ──")

            all_passed = True
            for name, js in DETECTION_TESTS:
                result = await page.evaluate(js)
                # navigator.webdriver 应该是 None/undefined/False
                # automation bindings 应该是 False
                # chrome.runtime 应该是 True
                if name == "chrome.runtime":
                    passed = result is True
                else:
                    passed = not result

                status = "✅ PASS" if passed else "❌ FAIL"
                if not passed:
                    all_passed = False
                logger.info(f"  {status}  {name}: {result}")

            logger.info("\n── Canvas Fingerprint Consistency ──")
            fp1 = await page.evaluate("""() => {
                const c = document.createElement('canvas');
                const ctx = c.getContext('2d');
                ctx.fillStyle = 'red';
                ctx.fillRect(0, 0, 100, 100);
                ctx.fillText('fingerprint test', 10, 50);
                return c.toDataURL();
            }""")
            fp2 = await page.evaluate("""() => {
                const c = document.createElement('canvas');
                const ctx = c.getContext('2d');
                ctx.fillStyle = 'red';
                ctx.fillRect(0, 0, 100, 100);
                ctx.fillText('fingerprint test', 10, 50);
                return c.toDataURL();
            }""")
            consistent = fp1 == fp2
            logger.info(f"  {'✅' if consistent else '❌'}  Canvas consistent within session: {consistent}")

            logger.info("\n── Test Sites (manual check) ──")
            logger.info("  Open these in the browser window:")
            logger.info("  1. https://bot.sannysoft.com")
            logger.info("  2. https://fingerprintjs.com/demo")
            logger.info("  3. https://nowsecure.nl")

            if all_passed:
                logger.info("\n✅ All automated checks passed!")
            else:
                logger.warning("\n⚠️  Some checks failed. With CloakBrowser these should all pass.")

            # 等待用户查看
            logger.info("\nPress Enter to close...")
            await asyncio.get_event_loop().run_in_executor(None, input)

        finally:
            await context.close()
            await browser.close()


if __name__ == "__main__":
    browser_path = os.getenv("CLOAKBROWSER_PATH", "/opt/cloakbrowser/chrome")
    asyncio.run(test_with_patchright(browser_path))
