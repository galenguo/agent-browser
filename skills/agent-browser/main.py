"""Agent Browser Skill 主入口 — 模式感知 facade（通过 StealthMiddleware 路由所有操作）"""
import json
import re
import uuid
import logging
from typing import Optional, Dict

from .config import SkillConfig, detect_mode, load_config

logger = logging.getLogger(__name__)

# ref 格式: @e 后跟数字（如 @e0, @e12），防止 CSS 选择器注入
_REF_PATTERN = re.compile(r'^@e\d+$')

# ── 全局状态 ──

_config: Optional[SkillConfig] = None
_middleware = None  # StealthMiddleware（包装底层 Backend）


async def _ensure_middleware(config: SkillConfig = None):
    """确保 Middleware 已初始化（懒初始化 + 缓存）

    返回 StealthMiddleware 实例，所有操作通过它自动获得隐匿包装。
    """
    global _config, _middleware
    if _middleware is not None:
        return _middleware

    # 优先级：传入的 config > 已有的 _config > 自动探测
    if config:
        _config = config
    elif _config is not None:
        pass
    else:
        _config = await detect_mode()

    # 创建底层 backend
    if _config.calling_mode == "cli":
        from .backends.local import LocalCDPBackend
        raw_backend = LocalCDPBackend(_config)
    elif _config.calling_mode == "api":
        try:
            from .backends.remote import RemoteAPIBackend
            raw_backend = RemoteAPIBackend(_config)
        except ImportError:
            logger.warning("RemoteAPIBackend not available, falling back to LocalCDPBackend")
            from .backends.local import LocalCDPBackend
            raw_backend = LocalCDPBackend(_config)
    else:
        from .backends.local import LocalCDPBackend
        raw_backend = LocalCDPBackend(_config)

    # 包装为 StealthMiddleware（自动注入隐匿行为）
    from src.stealth.middleware import StealthMiddleware
    _middleware = StealthMiddleware(raw_backend, _config)

    # 连接后端
    await _middleware.connect()
    logger.info(
        f"Middleware initialized: {_config.calling_mode} + {_config.browser_mode} "
        f"(stealth={'ON' if _config.stealth_enabled else 'OFF'}, mode={_config.stealth_mode})"
    )
    return _middleware


def configure(**kwargs) -> SkillConfig:
    """同步配置（不触发自动探测）"""
    global _config
    _config = load_config(**kwargs)
    return _config


def reset():
    """重置全局状态（用于测试）"""
    global _config, _middleware
    if _middleware:
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(_middleware.disconnect())
            else:
                loop.run_until_complete(_middleware.disconnect())
        except Exception:
            pass
    _config = None
    _middleware = None
    logger.debug("Global state reset")


# ═══════════════════════════════════════════════════════════════
#  Facade API — 所有操作通过 StealthMiddleware 自动隐匿
# ═══════════════════════════════════════════════════════════════


async def create_session(
    cdp_url: str = None,
    mode: str = None,
    api_url: str = None,
    **kwargs,
) -> str:
    """创建浏览器会话（返回 session_id）"""
    config_kwargs = {}
    if mode:
        config_kwargs["calling_mode"] = mode
    if api_url:
        config_kwargs["api_url"] = api_url
    if cdp_url:
        config_kwargs["cdp_url"] = cdp_url
    config_kwargs.update(kwargs)

    if config_kwargs:
        config = load_config(**config_kwargs)
        mw = await _ensure_middleware(config)
    else:
        mw = await _ensure_middleware()

    session_id = uuid.uuid4().hex
    await mw.create_session(session_id)
    return session_id


async def delete_session(session_id: str):
    """删除会话"""
    mw = await _ensure_middleware()
    await mw.delete_session(session_id)


async def open_page(session_id: str, url: str):
    """打开页面（通过 StealthPageHandle.goto → 自动隐匿导航延迟）"""
    mw = await _ensure_middleware()
    page = await mw.get_page(session_id)
    await page.goto(url)

    # 预计算快照缓存
    await mw.cache_snapshot_after_open(session_id)


async def snapshot(session_id: str, interactive_only: bool = False):
    """获取页面快照"""
    mw = await _ensure_middleware()
    return await mw.snapshot(session_id, interactive_only)


async def click(session_id: str, ref: str):
    """点击元素（通过 data-ab-ref 属性定位）"""
    _validate_ref(ref)
    mw = await _ensure_middleware()
    page = await mw.get_page(session_id)

    result = await page.evaluate(
        f"""(() => {{
            const el = document.querySelector('[data-ab-ref="{ref}"]');
            if (!el) return {{error: 'Element not found'}};
            el.click();
            return {{status: 'ok'}};
        }})()"""
    )
    if result and result.get("error"):
        raise ValueError(f"Element {ref} not found. DOM may have changed since snapshot.")


async def fill(session_id: str, ref: str, text: str):
    """填充输入框（通过 data-ab-ref 定位 + json.dumps 安全转义）"""
    _validate_ref(ref)
    mw = await _ensure_middleware()
    page = await mw.get_page(session_id)

    escaped = json.dumps(text)
    result = await page.evaluate(
        f"""(() => {{
            const el = document.querySelector('[data-ab-ref="{ref}"]');
            if (!el) return {{error: 'Element not found'}};
            el.focus();
            el.value = {escaped};
            el.dispatchEvent(new Event('input', {{bubbles: true}}));
            return {{status: 'ok'}};
        }})()"""
    )
    if result and result.get("error"):
        raise ValueError(f"Element {ref} not found. DOM may have changed since snapshot.")


async def scroll(session_id: str, direction: str = "down", amount: int = 500):
    """滚动页面（通过 StealthPageHandle.mouse_wheel → 自动隐匿滚动延迟）"""
    mw = await _ensure_middleware()
    page = await mw.get_page(session_id)
    delta = amount if direction == "down" else -amount
    await page.mouse_wheel(0, delta)


async def select_option(session_id: str, ref: str, value: str):
    """选择下拉选项"""
    _validate_ref(ref)
    mw = await _ensure_middleware()
    page = await mw.get_page(session_id)

    escaped = json.dumps(value)
    result = await page.evaluate(
        f"""(() => {{
            const el = document.querySelector('[data-ab-ref="{ref}"]');
            if (!el) return {{error: 'Element not found'}};
            el.value = {escaped};
            el.dispatchEvent(new Event('change', {{bubbles: true}}));
            return {{status: 'ok'}};
        }})()"""
    )
    if result and result.get("error"):
        raise ValueError(f"Element {ref} not found. DOM may have changed since snapshot.")


async def hover(session_id: str, ref: str):
    """悬停元素（获取中心坐标后 mouse_move）"""
    _validate_ref(ref)
    mw = await _ensure_middleware()
    page = await mw.get_page(session_id)

    box = await page.evaluate(
        f"""(() => {{
            const el = document.querySelector('[data-ab-ref="{ref}"]');
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return {{x: r.x + r.width/2, y: r.y + r.height/2}};
        }})()"""
    )
    if not box:
        raise ValueError(f"Element {ref} not found. DOM may have changed since snapshot.")
    await page.mouse_move(box["x"], box["y"])


async def press_key(session_id: str, key: str):
    """按键（通过 StealthPageHandle.keyboard_press → 自动隐匿输入延迟）"""
    mw = await _ensure_middleware()
    page = await mw.get_page(session_id)
    await page.keyboard_press(key)


async def wait_for_selector(session_id: str, selector: str, timeout: int = 10000):
    """等待选择器出现"""
    mw = await _ensure_middleware()
    page = await mw.get_page(session_id)
    await page.wait_for_selector(selector, timeout=timeout)


async def go_back(session_id: str):
    """后退到上一页（通过 StealthPageHandle.go_back → 自动隐匿导航延迟）"""
    mw = await _ensure_middleware()
    page = await mw.get_page(session_id)
    await page.go_back()


async def run_task(
    session_id: str,
    task: str,
    intelligence: str = "agent",
    llm_config: dict = None,
    max_steps: int = 6,
    total_timeout: float = 300.0,
) -> dict:
    """
    智能模式任务执行。

    通过 StealthMiddleware.run_task() 委托给后端，
    自动获得 total_timeout 超时保护。
    """
    mw = await _ensure_middleware()
    return await mw.run_task(
        session_id, task,
        intelligence=intelligence,
        llm_config=llm_config,
        max_steps=max_steps,
        total_timeout=total_timeout,
    )


# ═══════════════════════════════════════════════════════════════
#  内部工具
# ═══════════════════════════════════════════════════════════════


def _validate_ref(ref: str):
    """验证 ref 格式（防止 CSS 选择器 / JS 注入）"""
    if not _REF_PATTERN.match(ref):
        raise ValueError(f"Invalid ref format: {ref}. Expected pattern: @e<digits>")
