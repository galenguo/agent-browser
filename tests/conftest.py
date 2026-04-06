"""
测试配置

提供共享 fixtures：
- event_loop: 异步事件循环
- mock_browser: Mock Playwright Browser
- mock_page: Mock Playwright Page
- mock_context: Mock BrowserContext
- skill_config: 默认 SkillConfig
- temp_state_path: 临时 daemon 状态文件路径

Real browser fixtures (headed CloakBrowser):
- cdp_url: Session-scoped CloakBrowser CDP URL (autouse)
- browser_context: Per-test browser context (real CDP)
- browser_page: Per-test page (real CDP)
- docker_api_url: FastAPI gateway URL (if Docker running)
"""

import asyncio
import contextlib
import json
import os
import socket
import tempfile
from datetime import datetime
from pathlib import Path
from unittest import mock

import pytest

# pytest-asyncio 配置
pytest_plugins = ("pytest_asyncio",)


# ── 输出目录 ──

_SCREENSHOT_DIR = Path(__file__).parent / "screenshots"
_RESULT_DIR = Path(__file__).parent / "results"


@pytest.fixture(scope="session")
def event_loop():
    """创建事件循环"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def skill_config():
    """默认 SkillConfig"""
    from agent_browser.config import SkillConfig

    return SkillConfig()


@pytest.fixture
def mock_page():
    """Mock Playwright Page"""
    page = mock.MagicMock()
    page.goto = mock.AsyncMock()
    page.evaluate = mock.AsyncMock(return_value=None)
    page.mouse = mock.MagicMock()
    page.mouse.move = mock.AsyncMock()
    page.mouse.wheel = mock.AsyncMock()
    page.keyboard = mock.MagicMock()
    page.keyboard.type = mock.AsyncMock()
    page.keyboard.press = mock.AsyncMock()
    page.viewport_size = {"width": 1920, "height": 1080}
    page.add_init_script = mock.AsyncMock()
    page.locator = mock.MagicMock()
    page.locator.return_value.click = mock.AsyncMock()
    return page


@pytest.fixture
def mock_context(mock_page):
    """Mock BrowserContext"""
    context = mock.MagicMock()
    context.new_page = mock.AsyncMock(return_value=mock_page)
    context.close = mock.AsyncMock()
    return context


@pytest.fixture
def mock_browser(mock_context):
    """Mock Playwright Browser"""
    browser = mock.MagicMock()
    browser.new_context = mock.AsyncMock(return_value=mock_context)
    browser.close = mock.AsyncMock()
    browser.contexts = []
    return browser


@pytest.fixture
def temp_state_path():
    """临时 daemon 状态文件路径"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir) / "daemon-state.json"


@pytest.fixture
def reset_daemon():
    """每个测试后重置 BrowserDaemon singleton"""
    from agent_browser.daemon import BrowserDaemon

    yield
    BrowserDaemon.reset()


@pytest.fixture
def clean_env():
    """清理环境变量"""
    env_keys = [k for k in os.environ if k.startswith("AGENT_BROWSER_")]
    original_values = {k: os.environ.get(k) for k in env_keys}

    # 清理
    for k in env_keys:
        del os.environ[k]

    yield

    # 恢复
    for k, v in original_values.items():
        if v is not None:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)


# ── Tier 3: CloakBrowser lifecycle management ──

_CDP_PORT = 19222
_CDP_URL = f"http://127.0.0.1:{_CDP_PORT}"
_session_pw = None
_session_browser = None
_we_started_it = False


def _port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """检查端口是否已被占用（非阻塞）"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex((host, port)) == 0


@pytest.fixture(scope="session", autouse=True)
def cdp_url(request):
    """
    Session-scoped CloakBrowser 生命周期管理。

    行为：
    1. 检查端口 {_CDP_PORT} 是否空闲
       - 空闲：通过 Playwright 启动有头 CloakBrowser，yield URL
       - 占用：假设用户手动启动了浏览器，直接 yield URL（不关闭）
    2. Session 结束后（无论成功或失败）：
       - 仅关闭我们启动的浏览器实例
       - 用户手动启动的浏览器不受影响
    """
    global _session_pw, _session_browser, _we_started_it

    if _port_in_use(_CDP_PORT):
        print(f"\n[CloakBrowser] Port {_CDP_PORT} in use, using existing instance")
        yield _CDP_URL
        return

    # 端口空闲 — 通过 Playwright 启动有头模式（macOS 兼容）
    print(f"\n[CloakBrowser] Port {_CDP_PORT} free, launching headed browser...")
    try:
        from agent_browser.browser.stealth_launcher import close_browser, launch_stealth_browser

        loop = asyncio.new_event_loop()
        try:
            pw, browser, url = loop.run_until_complete(launch_stealth_browser(headless=False, cdp_port=_CDP_PORT))
        finally:
            loop.close()

        _session_pw = pw
        _session_browser = browser
        _we_started_it = True
        print(f"[CloakBrowser] Headed browser ready at {url}")

        yield url

    finally:
        if _we_started_it and _session_browser is not None:
            print("\n[CloakBrowser] Closing browser (session teardown)...")
            loop = asyncio.new_event_loop()
            try:

                async def _force_close():
                    with contextlib.suppress(TimeoutError, Exception):
                        await asyncio.wait_for(close_browser(_session_pw, _session_browser), timeout=15)

                loop.run_until_complete(_force_close())
            except Exception as e:
                print(f"[CloakBrowser] Warning during close: {e}")
            finally:
                loop.close()
            # 确保进程被杀（有头模式可能阻塞 browser.close()）
            import subprocess

            subprocess.run(
                ["pkill", "-f", f"Chromium.*remote-debugging-port={_CDP_PORT}"], capture_output=True, timeout=5
            )
            _session_pw = None
            _session_browser = None
            _we_started_it = False
            print("[CloakBrowser] Closed")


@pytest.fixture
async def browser_context(cdp_url):
    """
    Per-test 浏览器 context fixture（带 try/finally 保证清理）。

    用法：
        async def test_xxx(browser_context):
            page = await browser_context.new_page()
            await page.goto("https://example.com")
            # ... test logic ...
            # 不需要手动 close — fixture 自动处理
    """
    from playwright.async_api import async_playwright

    pw = None
    browser = None
    context = None
    try:
        pw = await async_playwright().start()
        browser = await pw.chromium.connect_over_cdp(cdp_url)
        context = await browser.new_context(ignore_https_errors=True)
        yield context
    finally:
        if context:
            with contextlib.suppress(Exception):
                await context.close()
        if browser:
            with contextlib.suppress(Exception):
                await browser.close()
        if pw:
            with contextlib.suppress(Exception):
                await pw.stop()


@pytest.fixture
async def browser_page(browser_context):
    """
    Per-test page fixture（基于 browser_context，自动创建新页面）。
    同样带 try/finally 保证清理。
    """
    page = None
    try:
        page = await browser_context.new_page()
        yield page
    finally:
        if page:
            with contextlib.suppress(Exception):
                await page.close()


# ══════════════════════════════════════════
#  Real Browser Test Helpers
# ════════════════════════════════════════

_SCREENSHOT_DIR = Path(__file__).parent / "screenshots"
_RESULT_DIR = Path(__file__).parent / "results"


def ensure_screenshot_dir() -> Path:
    """确保截图目录存在，返回路径"""
    _SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    (_SCREENSHOT_DIR / ".gitkeep").touch(exist_ok=True)
    return _SCREENSHOT_DIR


def ensure_result_dir() -> Path:
    """确保结果目录存在，返回路径"""
    _RESULT_DIR.mkdir(parents=True, exist_ok=True)
    return _RESULT_DIR


async def save_screenshot(page, name: str) -> Path:
    """保存页面截图到 tests/screenshots/，返回文件路径"""
    d = ensure_screenshot_dir()
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_name = name.replace("/", "_").replace(" ", "_")
    path = d / f"{ts}-{safe_name}.png"
    try:
        await page.screenshot(path=str(path), full_page=False)
    except Exception:
        path = d / f"{ts}-{safe_name}-FAILED.png"
    return path


def write_scorecard(results: list) -> Path:
    """写入 JSON scorecard 到 tests/results/，返回路径"""
    d = ensure_result_dir()
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = d / f"scorecard-{ts}.json"
    card = {
        "timestamp": datetime.now().isoformat(),
        "total": len(results),
        "passed": sum(1 for r in results if r.get("status") == "PASS"),
        "failed": sum(1 for r in results if r.get("status") == "FAIL"),
        "detected": sum(1 for r in results if r.get("status") == "DETECTED"),
        "blocked": sum(1 for r in results if r.get("status") == "BLOCKED"),
        "results": results,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(card, f, indent=2, ensure_ascii=False)
    return path


@pytest.fixture
async def docker_api_url():
    """
    FastAPI Gateway URL（Docker/Remote 模式）。

    检测 localhost:8000 是否有 FastAPI 服务运行。
    如果没有，返回 None — 测试应通过 @pytest.mark.skipif 跳过。
    """
    import aiohttp

    try:
        async with (
            aiohttp.ClientSession() as session,
            session.get(
                "http://localhost:8000/health",
                timeout=aiohttp.ClientTimeout(total=3),
            ) as resp,
        ):
            if resp.status == 200:
                return "http://localhost:8000"
    except Exception:
        pass
    return None


@pytest.fixture
def scorecard_writer():
    """提供 scorecard 写入函数给测试使用"""
    _entries: list[dict] = []

    class Writer:
        def record(self, entry: dict):
            _entries.append(entry)

        def flush(self) -> Path | None:
            if _entries:
                return write_scorecard(_entries)
            return None

    return Writer()


# ── Skip 统计 + Marker 注册 ──

_collected_skips: list[str] = []


def pytest_configure(config):
    """注册自定义 marker"""
    config.addinivalue_line("markers", "requires_browser: mark test as needing real CloakBrowser")
    config.addinivalue_line("markers", "manual: mark test as manual (e.g., Boss Zhipin - high flake risk)")


def pytest_runtest_logreport(report):
    """追踪 skipped 测试及原因"""
    global _collected_skips
    if report.when == "call" and report.skipped:
        reason = str(report.longrepr) if report.longrepr else ""
        if hasattr(report, "wasxfail"):
            _collected_skips.append(f"  XFAIL {report.nodeid}: {reason[:120]}")
        else:
            _collected_skips.append(f"  SKIP  {report.nodeid}: {reason}")


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """测试结束时打印 skip 摘要"""
    global _collected_skips
    if _collected_skips:
        terminalreporter.write_sep("=", f"Skip Summary ({len(_collected_skips)} skipped)")
        for line in _collected_skips:
            terminalreporter.write_line(line)
        anti_det_skips = [entry for entry in _collected_skips if "anti_detection" in entry or "zhipin" in entry.lower()]
        if anti_det_skips:
            terminalreporter.write_sep("=", "WARNING: Anti-detection tests were skipped!")
            for line in anti_det_skips:
                terminalreporter.write_line(line)
            terminalreporter.write_line(
                "  These tests validate the core product claim. Install CloakBrowser to enable them."
            )
        _collected_skips.clear()
