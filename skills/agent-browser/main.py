"""Agent Browser Skill 主入口 — 模式感知 facade"""
import json
import re
import uuid
import logging
from typing import Optional, Dict

from .config import SkillConfig, detect_mode, load_config
from .backends import BrowserBackend, BrowserPageHandle
from .backends.local import LocalCDPBackend

logger = logging.getLogger(__name__)

# ref 格式: @e 后跟数字（如 @e0, @e12），防止 CSS 选择器注入
_REF_PATTERN = re.compile(r'^@e\d+$')

# ── 全局状态 ──

_config: Optional[SkillConfig] = None
_backend: Optional[BrowserBackend] = None


async def _ensure_backend(config: SkillConfig = None) -> BrowserBackend:
    """确保后端已初始化（懒初始化 + 缓存）"""
    global _config, _backend
    if _backend is not None:
        return _backend

    # 优先级：传入的 config > 已有的 _config > 自动探测
    if config:
        _config = config
    elif _config is not None:
        # 已经通过 configure() 设置过，直接使用
        pass
    else:
        _config = await detect_mode()

    if _config.calling_mode == "cli":
        _backend = LocalCDPBackend(_config)
    elif _config.calling_mode == "api":
        try:
            from .backends.remote import RemoteAPIBackend
            _backend = RemoteAPIBackend(_config)
        except ImportError:
            logger.warning("RemoteAPIBackend not available, falling back to LocalCDPBackend")
            _backend = LocalCDPBackend(_config)
    else:
        _backend = LocalCDPBackend(_config)

    logger.info(f"Backend initialized: {_config.calling_mode} + {_config.browser_mode}")
    return _backend


def configure(**kwargs) -> SkillConfig:
    """同步配置（不触发自动探测）"""
    global _config
    _config = load_config(**kwargs)
    return _config


def reset():
    """重置全局状态（用于测试）"""
    global _config, _backend
    _config = None
    _backend = None
    logger.debug("Global state reset")


async def create_session(
    cdp_url: str = None,
    mode: str = None,
    api_url: str = None,
    **kwargs,
) -> str:
    """
    创建浏览器会话。

    向后兼容：无参数时默认 CLI + local + http://127.0.0.1:19222。
    新参数：
      mode: "cli" | "api" — 调用模式
      api_url: FastAPI 地址（API 模式需要）
      cdp_url: CDP 地址（CLI 模式，覆盖默认）
    """
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
        backend = await _ensure_backend(config)
    else:
        backend = await _ensure_backend()

    session_id = uuid.uuid4().hex
    await backend.create_session(session_id)
    return session_id


async def delete_session(session_id: str):
    """删除会话"""
    backend = await _ensure_backend()
    await backend.delete_session(session_id)


async def open_page(session_id: str, url: str):
    """打开页面"""
    backend = await _ensure_backend()
    page = await backend.get_page(session_id)

    # 隐匿延迟
    if isinstance(backend, LocalCDPBackend):
        await backend.stealth_delay("navigate")

    await page.goto(url)

    # 预计算快照缓存
    if isinstance(backend, LocalCDPBackend):
        await backend.cache_snapshot_after_open(session_id)


async def snapshot(session_id: str, interactive_only: bool = False):
    """获取快照"""
    backend = await _ensure_backend()
    if isinstance(backend, LocalCDPBackend):
        return await backend.snapshot(session_id, interactive_only)

    # RemoteAPIBackend: 通过 HTTP 获取完整快照
    return await backend.snapshot(session_id, interactive_only)


async def click(session_id: str, ref: str):
    """点击元素"""
    backend = await _ensure_backend()
    if isinstance(backend, LocalCDPBackend):
        await backend.stealth_delay("click")
        # 验证 ref 格式（防止 CSS 选择器注入）
        if not _REF_PATTERN.match(ref):
            raise ValueError(f"Invalid ref format: {ref}")

        page = await backend.get_page(session_id)
        # 通过 data-ab-ref 属性查找元素（稳定，不受 DOM 位置变化影响）
        result = await page.evaluate(
            f"""(() => {{
                const el = document.querySelector('[data-ab-ref="{ref}"]');
                if (!el) return {{error: 'Element not found'}};
                el.click();
                return {{status: 'ok'}};
            }})()"""
        )
        if result.get("error"):
            raise ValueError(f"Element {ref} not found. DOM may have changed since snapshot.")
    else:
        # Remote: 通过 evaluate
        page = await backend.get_page(session_id)
        await page.evaluate(f"document.querySelector('[data-ab-ref=\"{ref}\"]')?.click()")


async def fill(session_id: str, ref: str, text: str):
    """填充输入"""
    backend = await _ensure_backend()
    if isinstance(backend, LocalCDPBackend):
        await backend.stealth_delay("input")
        # 验证 ref 格式（防止 CSS 选择器注入）
        if not _REF_PATTERN.match(ref):
            raise ValueError(f"Invalid ref format: {ref}")

        escaped = json.dumps(text)
        page = await backend.get_page(session_id)
        # 通过 data-ab-ref 属性查找元素（稳定，不受 DOM 位置变化影响）
        result = await page.evaluate(
            f"""(() => {{
                const el = document.querySelector('[data-ab-ref="{ref}"]');
                if (!el) return {{error: 'Element not found'}};
                el.focus();
                el.value = '{escaped}';
                el.dispatchEvent(new Event('input', {{bubbles: true}}));
                return {{status: 'ok'}};
            }})()"""
        )
        if result.get("error"):
            raise ValueError(f"Element {ref} not found. DOM may have changed since snapshot.")
    else:
        page = await backend.get_page(session_id)
        escaped = text.replace("\\", "\\\\").replace("'", "\\'")
        await page.evaluate(
            f"document.querySelector('[data-ab-ref=\"{ref}\"]') && (() => {{ const el = document.querySelector('[data-ab-ref=\"{ref}\"]'); el.focus(); el.value = '{escaped}'; el.dispatchEvent(new Event('input', {{bubbles: true}})); }})()"
        )


async def scroll(session_id: str, direction: str = "down", amount: int = 500):
    """滚动页面"""
    backend = await _ensure_backend()
    if isinstance(backend, LocalCDPBackend):
        await backend.stealth_delay("scroll")
    page = await backend.get_page(session_id)
    delta = amount if direction == "down" else -amount
    await page.mouse_wheel(0, delta)


async def select_option(session_id: str, ref: str, value: str):
    """选择下拉选项"""
    backend = await _ensure_backend()
    if isinstance(backend, LocalCDPBackend):
        # 验证 ref 格式（防止 CSS 选择器注入）
        if not _REF_PATTERN.match(ref):
            raise ValueError(f"Invalid ref format: {ref}")

        escaped = json.dumps(value)
        page = await backend.get_page(session_id)
        # 通过 data-ab-ref 属性查找元素（稳定，不受 DOM 位置变化影响）
        result = await page.evaluate(
            f"""(() => {{
                const el = document.querySelector('[data-ab-ref="{ref}"]');
                if (!el) return {{error: 'Element not found'}};
                el.value = '{escaped}';
                el.dispatchEvent(new Event('change', {{bubbles: true}}));
                return {{status: 'ok'}};
            }})()"""
        )
        if result.get("error"):
            raise ValueError(f"Element {ref} not found. DOM may have changed since snapshot.")


async def hover(session_id: str, ref: str):
    """悬停元素"""
    backend = await _ensure_backend()
    if isinstance(backend, LocalCDPBackend):
        # 验证 ref 格式（防止 CSS 选择器注入）
        if not _REF_PATTERN.match(ref):
            raise ValueError(f"Invalid ref format: {ref}")

        page = await backend.get_page(session_id)
        # 通过 data-ab-ref 属性查找元素并获取中心坐标
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
    """按键"""
    backend = await _ensure_backend()
    page = await backend.get_page(session_id)
    await page.keyboard_press(key)


async def wait_for_selector(session_id: str, selector: str, timeout: int = 10000):
    """等待选择器出现"""
    backend = await _ensure_backend()
    page = await backend.get_page(session_id)
    await page.wait_for_selector(selector, timeout=timeout)


async def go_back(session_id: str):
    """后退到上一页"""
    backend = await _ensure_backend()
    page = await backend.get_page(session_id)
    await page.go_back()


async def run_task(
    session_id: str,
    task: str,
    intelligence: str = "agent",
    llm_config: dict = None,
    max_steps: int = 6,
) -> dict:
    """
    智能模式任务执行。

    intelligence="agent": 内置 browser-use Agent 自主执行
    intelligence="llm": 返回可用工具描述，由外部 LLM 驱动 ReAct

    LocalCDPBackend: 本地 browser-use Agent（直连 CDP）
    RemoteAPIBackend: HTTP 轮询远程 FastAPI run_task 端点
    """
    backend = await _ensure_backend()
    return await backend.run_task(
        session_id, task, intelligence=intelligence, llm_config=llm_config, max_steps=max_steps
    )
