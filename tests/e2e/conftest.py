"""
E2E 测试共享 fixtures

提供基于 conftest.py 中 cdp_url / browser_context / browser_page 的
E2E 专用便捷 fixture，减少 test_e2e_*.py 中的重复 boilerplate。
"""

import pytest


@pytest.fixture
async def e2e_page(browser_page):
    """
    E2E 页面 fixture — 已连接 CloakBrowser，可直接使用。

    用法：
        async def test_xxx(e2e_page):
            await e2e_page.goto("https://example.com")
            title = await e2e_page.title()
    """
    yield browser_page
