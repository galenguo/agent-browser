"""
StealthMiddleware — 集中式隐匿层

包装所有浏览器操作，自动应用：
  - 操作前延迟（人类思考时间）
  - 操作后停顿（阅读/反应时间）
  - 贝塞尔鼠标移动（点击前）
  - 人类打字模拟（输入操作）

当 stealth 禁用时，作为透传层（零开销）。

熔断器状态机（per-session，非全局）：
  CLOSED: 隐匿激活，failure_count < threshold
  OPEN:   隐匿禁用（当前 session），failure_count >= threshold
  RESET:  新 session 重置 failure_count = 0

设计文档：galen-autoresearch-apr2-design-20260404-233255.md Phase 1
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

from core.stealth_enhancer import StealthEnhancer
from skills.agent_browser.backends import BrowserBackend, BrowserPageHandle

logger = logging.getLogger(__name__)


# ── 熔断器状态 ──────────────────────────────────────────────


class CircuitState(Enum):
    CLOSED = "closed"   # 正常：隐匿激活
    OPEN = "open"       # 降级：隐匿禁用


@dataclass
class _PerSessionCircuit:
    """Per-session circuit breaker state（非全局单例）"""

    failure_count: int = 0
    state: CircuitState = CircuitState.CLOSED
    threshold: int = 5

    def record_failure(self) -> bool:
        """记录失败，返回是否应触发熔断"""
        self.failure_count += 1
        if self.failure_count >= self.threshold:
            self.state = CircuitState.OPEN
            logger.warning(
                f"Circuit OPEN after {self.failure_count} stealth failures; "
                f"disabling stealth for this session"
            )
            return True
        return False

    @property
    def is_active(self) -> bool:
        return self.state == CircuitState.CLOSED


# ── 操作分类 ────────────────────────────────────────────────

# 需要隐匿包装的交互式操作（映射到 StealthEnhancer 延迟类型）
_STEALTH_OPS: Dict[str, str] = {
    "goto": "navigate",
    "go_back": "navigate",
    "mouse_wheel": "scroll",
    "mouse_move": "general",  # 鼠标移动本身是隐匿行为
    "keyboard_press": "input",
}

# 透传操作（只读或非交互，不需要延迟）
_PASSTHROUGH_OPS = frozenset({
    "evaluate", "wait_for_selector", "title", "url",
    "on", "remove_listener", "close",
})


# ── StealthPageHandle ────────────────────────────────────────


class StealthPageHandle(BrowserPageHandle):
    """
    包装 BrowserPageHandle，为每个操作自动注入隐匿行为。

    实现与 BrowserPageHandle 相同的接口。
    对 RemotePageHandle 安全（不依赖 raw_page 属性）。
    """

    def __init__(
        self,
        wrapped: BrowserPageHandle,
        stealth: StealthEnhancer,
        circuit: _PerSessionCircuit,
    ):
        self._wrapped = wrapped
        self._stealth = stealth
        self._circuit = circuit
        # 缓存 raw_page 引用（RemotePageHandle 没有）
        self._raw_page = getattr(wrapped, "raw_page", None)

    # ── 导航（隐匿包装）──

    async def goto(self, url: str, wait_until: str = "domcontentloaded", timeout: int = 8000) -> None:
        await self._pre("goto")
        try:
            await self._wrapped.goto(url, wait_until=wait_until, timeout=timeout)
        finally:
            await self._post("goto")

    async def go_back(self, wait_until: str = "domcontentloaded", timeout: int = 10000) -> None:
        await self._pre("go_back")
        try:
            await self._wrapped.go_back(wait_until=wait_until, timeout=timeout)
        finally:
            await self._post("go_back")

    # ── JavaScript 执行（透传）──

    async def evaluate(self, expression: str) -> Any:
        return await self._wrapped.evaluate(expression)

    # ── 元素等待（透传）──

    async def wait_for_selector(self, selector: str, timeout: int = 10000) -> None:
        return await self._wrapped.wait_for_selector(selector, timeout=timeout)

    # ── 鼠标操作（隐匿包装）──

    async def mouse_wheel(self, delta_x: int, delta_y: int) -> None:
        await self._pre("mouse_wheel")
        try:
            await self._wrapped.mouse_wheel(delta_x, delta_y)
        finally:
            await self._post("mouse_wheel")

    async def mouse_move(self, x: float, y: float) -> None:
        """鼠标移动本身是隐匿行为——使用贝塞尔曲线"""
        if not self._circuit.is_active or self._raw_page is None:
            await self._wrapped.mouse_move(x, y)
            return
        try:
            await self._stealth.random_mouse_move(self._raw_page)
        except Exception as e:
            self._circuit.record_failure()
            logger.debug(f"Stealth mouse_move failed: {e}")
        await self._wrapped.mouse_move(x, y)

    # ── 键盘操作（隐匿包装）──

    async def keyboard_press(self, key: str) -> None:
        await self._pre("keyboard_press")
        try:
            await self._wrapped.keyboard_press(key)
        finally:
            await self._post("keyboard_press")

    # ── 页面信息（透传）──

    async def title(self) -> str:
        return await self._wrapped.title()

    async def url(self) -> str:
        return await self._wrapped.url()

    # ── 事件监听（透传）──

    async def on(self, event: str, handler) -> None:
        await self._wrapped.on(event, handler)

    def remove_listener(self, event: str, handler) -> None:
        self._wrapped.remove_listener(event, handler)

    # ── 生命周期（透传）──

    async def close(self) -> None:
        await self._wrapped.close()

    # ── 内部方法 ──

    async def _pre(self, operation: str) -> None:
        """操作前隐匿延迟"""
        if not self._circuit.is_active:
            return
        action_type = _STEALTH_OPS.get(operation, "general")
        try:
            await self._stealth.pre_action(action_type)
        except Exception as e:
            self._circuit.record_failure()
            logger.warning(f"Stealth pre_action({action_type}) failed: {e}")

    async def _post(self, operation: str) -> None:
        """操作后隐匿停顿"""
        if not self._circuit.is_active:
            return
        action_type = _STEALTH_OPS.get(operation, "general")
        try:
            await self._stealth.post_action(action_type)
        except Exception as e:
            self._circuit.record_failure()
            logger.warning(f"Stealth post_action({action_type}) failed: {e}")

    @property
    def raw_page(self):
        """暴露原始 page（兼容需要 raw_page 的代码路径）"""
        return self._raw_page

    @property
    def wrapped(self) -> BrowserPageHandle:
        """访问被包装的 handle（用于高级用法）"""
        return self._wrapped


# ── StealthMiddleware ─────────────────────────────────────────


class StealthMiddleware:
    """
    集中式隐匿中间件。

    包装 BrowserBackend，在所有操作中自动注入隐匿行为。

    用法：
        backend = LocalCDPBackend(config)
        middleware = StealthMiddleware(backend, config)
        page_handle = await middleware.create_session("user_1")
        # page_handle 是 StealthPageHandle，所有操作自动隐匿
    """

    def __init__(self, backend: BrowserBackend, config):
        """
        Args:
            backend: 底层 BrowserBackend（LocalCDPBackend 或 RemoteAPIBackend）
            config: SkillConfig（读取 stealth_enabled 等）
        """
        self._backend = backend
        self._config = config
        self._stealth: Optional[StealthEnhancer] = None
        self._circuits: Dict[str, _PerSessionCircuit] = {}

        # 仅在启用时初始化 StealthEnhancer
        stealth_enabled = getattr(config, "stealth_enabled", True)
        if stealth_enabled:
            self._stealth = StealthEnhancer()
            logger.info("StealthMiddleware initialized (stealth ON)")
        else:
            logger.info("StealthMiddleware initialized (stealth OFF — pass-through)")

    # ── Backend 委托方法 ──

    async def connect(self) -> None:
        """连接到底层后端"""
        await self._backend.connect()

    async def disconnect(self) -> None:
        """断开底层后端"""
        await self._backend.disconnect()

    async def is_connected(self) -> bool:
        return await self._backend.is_connected()

    # ── Session 管理（核心：创建时包装 handle）──

    async def create_session(self, session_id: str) -> BrowserPageHandle:
        """
        创建会话并通过隐匿包装 PageHandle。

        当 stealth 启用时：
          1. 注入定时器噪声（JS 指纹防御）
          2. 返回 StealthPageHandle（所有操作自动隐匿）

        当 stealth 禁用或熔断时：
          返回原始 PageHandle（零开销透传）
        """
        page_handle = await self._backend.create_session(session_id)

        if self._stealth is None:
            return page_handle

        # Per-session circuit breaker
        circuit = _PerSessionCircuit(threshold=5)
        self._circuits[session_id] = circuit

        try:
            # 注入 JS 定时器噪声（Layer 6: timing fingerprint defense）
            raw_page = getattr(page_handle, "raw_page", None)
            if raw_page is not None:
                await StealthEnhancer.inject_timing_noise(raw_page)

            # 包装为 StealthPageHandle
            return StealthPageHandle(page_handle, self._stealth, circuit)

        except Exception as e:
            logger.warning(f"Stealth injection failed for session {session_id}: {e}")
            circuit.record_failure()
            return page_handle  # 降级：返回未包装的 handle

    async def delete_session(self, session_id: str) -> None:
        """删除会话，清理 per-session 熔断状态"""
        self._circuits.pop(session_id, None)
        await self._backend.delete_session(session_id)

    async def get_page(self, session_id: str) -> BrowserPageHandle:
        """获取页面句柄（可能是 StealthPageHandle 或原始 handle）"""
        return await self._backend.get_page(session_id)

    # ── 快照/refs（委托给后端）──

    async def snapshot(self, session_id: str, interactive_only: bool = False) -> Dict:
        if hasattr(self._backend, "snapshot"):
            return await self._backend.snapshot(session_id, interactive_only)
        raise NotImplementedError("snapshot() not supported by current backend")

    async def cache_snapshot_after_open(self, session_id: str) -> None:
        if hasattr(self._backend, "cache_snapshot_after_open"):
            await self._backend.cache_snapshot_after_open(session_id)

    def get_dom_indices(self, session_id: str) -> list:
        if hasattr(self._backend, "get_dom_indices"):
            return self._backend.get_dom_indices(session_id)
        return []

    # ── 隐匿快捷方法（向后兼容）──

    async def stealth_delay(self, action_type: str = "general") -> None:
        """手动触发隐匿延迟（向后兼容旧代码）"""
        if self._stealth and self._stealth:
            await self._stealth.pre_action(action_type)

    async def stealth_mouse_move(self, session_id: str) -> None:
        """手动触发鼠标游走（向后兼容旧代码）"""
        if self._stealth is None:
            return
        page = await self.get_page(session_id)
        raw_page = getattr(page, "raw_page", None)
        if raw_page is not None:
            try:
                await self._stealth.random_mouse_move(raw_page)
            except Exception as e:
                logger.debug(f"Manual stealth_mouse_move failed: {e}")

    # ── Agent 任务执行（委托给后端）──

    async def run_task(
        self,
        session_id: str,
        task: str,
        intelligence: str = "agent",
        llm_config: Optional[Dict] = None,
        max_steps: int = 6,
        total_timeout: float = 300.0,
        **kwargs,
    ) -> Dict:
        """
        执行 Agent 任务（委托给后端 run_task）。

        total_timeout: 整体超时（秒），防止无限阻塞。
                     默认 300s（5 分钟）。
        """
        if not hasattr(self._backend, "run_task"):
            return {"status": "failed", "error": "run_task() not supported by current backend"}

        # 包装超时控制
        if total_timeout > 0:
            try:
                return await asyncio.wait_for(
                    self._backend.run_task(
                        session_id, task,
                        intelligence=intelligence,
                        llm_config=llm_config,
                        max_steps=max_steps,
                        **kwargs,
                    ),
                    timeout=total_timeout,
                )
            except asyncio.TimeoutError:
                return {
                    "status": "timeout",
                    "error": f"Task exceeded {total_timeout}s limit",
                    "steps": max_steps,
                }

        return await self._backend.run_task(
            session_id, task,
            intelligence=intelligence,
            llm_config=llm_config,
            max_steps=max_steps,
            **kwargs,
        )

    # ── 属性访问 ──

    @property
    def backend(self) -> BrowserBackend:
        """访问底层后端（用于需要直接访问的场景）"""
        return self._backend

    @property
    def stealth(self) -> Optional[StealthEnhancer]:
        """访问 StealthEnhancer 实例"""
        return self._stealth

    @property
    def circuits(self) -> Dict[str, _PerSessionCircuit]:
        """访问 per-session 熔断状态（用于监控/调试）"""
        return dict(self._circuits)  # 返回副本
