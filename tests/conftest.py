"""
测试配置

提供共享 fixtures：
- event_loop: 异步事件循环
- mock_browser: Mock Playwright Browser
- mock_page: Mock Playwright Page
- mock_context: Mock BrowserContext
- skill_config: 默认 SkillConfig
- temp_state_path: 临时 daemon 状态文件路径
"""
import pytest
import asyncio
import sys
import tempfile
from pathlib import Path
from unittest import mock

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))
# 添加 skill 路径
sys.path.insert(0, str(Path(__file__).parent.parent / "skills"))


@pytest.fixture(scope="session")
def event_loop():
    """创建事件循环"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def skill_config():
    """默认 SkillConfig"""
    # 使用 skill 包的 config
    config_module = __import__(
        "config",
        fromlist=["SkillConfig"],
        level=0
    )
    # 动态导入
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "config",
        Path(__file__).parent.parent / "skills" / "agent-browser" / "config.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SkillConfig()


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
    import os
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


# pytest-asyncio 配置
pytest_plugins = ('pytest_asyncio',)
