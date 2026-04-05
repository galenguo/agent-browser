"""Agent Browser Skill 主入口 — 轻量级 facade（通过 StealthMiddleware 路由所有操作）"""
import asyncio
import json
import re
import uuid
import logging
from typing import Any, Optional

from .config import SkillConfig, detect_mode, load_config

logger = logging.getLogger(__name__)
_REF_PATTERN = re.compile(r'^@e\d+$')

_config: Optional[SkillConfig] = None
_middleware = None
_middleware_lock = asyncio.Lock()


async def _ensure_middleware(config: SkillConfig = None):
    global _config, _middleware
    if _middleware is not None:
        return _middleware
    async with _middleware_lock:
        if _middleware is not None:
            return _middleware
        if config:
            _config = config
        elif _config is not None:
            pass
        else:
            _config = await detect_mode()

    # ── 后端选择：Extension > Local (CloakBrowser) > Remote ──
    raw_backend = await _select_backend(_config)

    from src.stealth.middleware import StealthMiddleware
    _middleware = StealthMiddleware(raw_backend, _config)
    await _middleware.connect()
    logger.info(f"Middleware ready: {_config.calling_mode}/{_config.browser_mode}")
    return _middleware


async def _select_backend(config: SkillConfig):
    """
    后端选择逻辑（优先级）：

    1. Extension 模式：Chrome Extension 已连接 → 使用用户真实 Chrome
    2. Local 模式：CloakBrowser CDP 可达 → 使用本地反检测浏览器
    3. API 模式：FastAPI 服务可用 → 远程调用
    4. Fallback: Local 模式（默认）
    """
    # Priority 1: Try Extension mode (user's real Chrome)
    if await _try_extension_connection(config):
        try:
            from .backends.extension import ExtensionBackend
            logger.info("Using Extension backend (real Chrome via Chrome Extension)")
            return ExtensionBackend(config)
        except Exception as e:
            logger.warning(f"Extension backend failed, falling back to local: {e}")

    # Priority 2-4: Existing logic (Local / API / fallback)
    if config.calling_mode == "cli":
        from .backends.local import LocalCDPBackend
        return LocalCDPBackend(config)
    elif config.calling_mode == "api":
        try:
            from .backends.remote import RemoteAPIBackend
            return RemoteAPIBackend(config)
        except ImportError:
            from .backends.local import LocalCDPBackend
            return LocalCDPBackend(config)
    else:
        from .backends.local import LocalCDPBackend
        return LocalCDPBackend(config)


async def _try_extension_connection(config: SkillConfig) -> bool:
    """
    检测 Chrome Extension 是否已连接。

    方法：通过 Daemon 的 ExtensionBridge 检查 WebSocket 连接状态。
    不需要实际创建后端，只做轻量级探测。
    """
    # 快速检查：如果配置明确禁用 Extension，跳过
    if getattr(config, 'extension_enabled', True) is False:
        return False

    try:
        from ..daemon import BrowserDaemon, ExtensionBridge

        daemon = BrowserDaemon.get(config)
        await daemon.ensure_connected()

        bridge = daemon.extension_bridge
        if bridge and bridge.is_connected:
            logger.info("Chrome Extension detected and connected")
            return True
    except ImportError:
        # websockets 未安装，跳过 Extension 模式
        pass
    except Exception as e:
        logger.debug(f"Extension detection failed (non-fatal): {e}")

    return False


def configure(**kwargs) -> SkillConfig:
    global _config
    _config = load_config(**kwargs)
    return _config


def reset():
    global _config, _middleware
    if _middleware:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(_middleware.disconnect())
            else:
                loop.run_until_complete(_middleware.disconnect())
        except Exception as e:
            logger.warning(f"reset(): disconnect failed (non-fatal): {e}")
    _config = None
    _middleware = None


# ── 内部工具 ──

def _validate_ref(ref: str):
    if not _REF_PATTERN.match(ref):
        raise ValueError(f"Invalid ref: {ref}. Expected @e<digits>")


async def _get_page(session_id: str):
    mw = await _ensure_middleware()
    return await mw.get_page(session_id)


async def _ref_op(session_id: str, ref: str, js_body: str):
    """通过 data-ab-ref 执行 JS（统一验证 + 查询 + 错误处理）"""
    _validate_ref(ref)
    page = await _get_page(session_id)
    safe_ref = json.dumps(ref)
    result = await page.evaluate(
        f"""(() => {{
            const el = document.querySelector('[data-ab-ref=' + {safe_ref} + ']');
            if (!el) return {{error: 'not found'}};
            {js_body}
            return {{status: 'ok'}};
        }})()"""
    )
    if result and result.get("error"):
        raise ValueError(f"Element {ref} not found. DOM may have changed.")


# ── Facade API ──

async def create_session(cdp_url=None, mode=None, api_url=None, **kwargs) -> str:
    cfg = {}
    if mode: cfg["calling_mode"] = mode
    if api_url: cfg["api_url"] = api_url
    if cdp_url: cfg["cdp_url"] = cdp_url
    cfg.update(kwargs)
    mw = await _ensure_middleware(load_config(**cfg) if cfg else None)
    sid = uuid.uuid4().hex
    await mw.create_session(sid)
    return sid


async def delete_session(session_id: str):
    mw = await _ensure_middleware()
    await mw.delete_session(session_id)


async def open_page(session_id: str, url: str):
    from .pipeline.steps import _validate_url
    url = _validate_url(url)
    page = await _get_page(session_id)
    await page.goto(url)
    mw = await _ensure_middleware()
    await mw.cache_snapshot_after_open(session_id)


async def snapshot(session_id: str, interactive_only: bool = False):
    mw = await _ensure_middleware()
    return await mw.snapshot(session_id, interactive_only)


async def click(session_id: str, ref: str):
    await _ref_op(session_id, ref, "el.click();")


async def fill(session_id: str, ref: str, text: str):
    v = json.dumps(text)
    await _ref_op(session_id, ref,
        f"el.focus(); el.value = {v}; el.dispatchEvent(new Event('input', {{bubbles: true}}));")


async def scroll(session_id: str, direction: str = "down", amount: int = 500):
    page = await _get_page(session_id)
    await page.mouse_wheel(0, amount if direction == "down" else -amount)


async def select_option(session_id: str, ref: str, value: str):
    v = json.dumps(value)
    await _ref_op(session_id, ref,
        f"el.value = {v}; el.dispatchEvent(new Event('change', {{bubbles: true}}));")


async def hover(session_id: str, ref: str):
    _validate_ref(ref)
    page = await _get_page(session_id)
    safe_ref = json.dumps(ref)
    box = await page.evaluate(
        f"""(() => {{
            const el = document.querySelector('[data-ab-ref=' + {safe_ref} + ']');
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return {{x: r.x + r.width/2, y: r.y + r.height/2}};
        }})()"""
    )
    if not box:
        raise ValueError(f"Element {ref} not found. DOM may have changed.")
    await page.mouse_move(box["x"], box["y"])


async def press_key(session_id: str, key: str):
    page = await _get_page(session_id)
    await page.keyboard_press(key)


async def wait_for_selector(session_id: str, selector: str, timeout: int = 10000):
    page = await _get_page(session_id)
    await page.wait_for_selector(selector, timeout=timeout)


async def go_back(session_id: str):
    page = await _get_page(session_id)
    await page.go_back()


async def run_task(
    session_id: str, task: str,
    intelligence: str = "agent",
    llm_config: dict = None,
    max_steps: int = 6,
    total_timeout: float = 300.0,
) -> dict:
    mw = await _ensure_middleware()
    return await mw.run_task(
        session_id, task,
        intelligence=intelligence, llm_config=llm_config,
        max_steps=max_steps, total_timeout=total_timeout,
    )


async def debug_pipeline(
	session_id: str,
	site: str,
	command: str,
	args: dict = None,
	breakpoints: list = None,
	cdp_url: str = "http://127.0.0.1:19222",
	**kwargs,
) -> Any:
	"""调试模式：单步执行 adapter pipeline，支持断点。

	Args:
		session_id: 浏览器会话 ID
		site: 站点名（如 "boss"）
		command: 命令名（如 "search"）
		args: 适配器参数
		breakpoints: 断点步骤索引列表（如 [2, 5] 表示在第 2、5 步后暂停）
		cdp_url: CDP 连接地址

	Returns:
		断点状态字典或最终数据（与 execute_pipeline 兼容）

	Example::

		result = await debug_pipeline(session_id, "boss", "search",
		                                {"query": "Python"}, breakpoints=[2])
		# 在 navigate 后暂停，返回当前页面数据
	"""
	from .adapters.loader import get_adapter
	from .pipeline.debugger import debug_pipeline as _debug

	adapter = get_adapter(site, command)
	if not adapter:
		raise ValueError(f"Adapter not found: {site}/{command}")

	merged_args = {**(args or {}), "_adapter_name": f"{site}/{command}"}
	pipeline = adapter.get("pipeline", [])
	stealth = adapter.get("stealth", {})

	return await _debug(
		steps=pipeline,
		session_id=session_id,
		args=merged_args,
		breakpoints=breakpoints,
		stealth_config=stealth,
	)
