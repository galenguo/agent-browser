"""
StealthMiddleware -- Centralized stealth layer.

Wraps all browser operations to automatically apply:
  - Pre-action delays (human thinking time)
  - Post-action pauses (reading/reaction time)
  - Bezier mouse movement (before clicks)
  - Human typing simulation (for input operations)

When stealth is disabled, acts as a pass-through layer (zero overhead).

Circuit breaker state machine (per-session, not global):
  CLOSED: stealth active, failure_count < threshold
  OPEN:   stealth disabled for this session, failure_count >= threshold
  RESET:  new session resets failure_count = 0
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

try:
    from agent_browser.stealth.enhancer import StealthEnhancer
except ImportError:
    # CloakBrowser C extensions not installed (CI environments, dev without cloakbrowser)
    StealthEnhancer = None  # type: ignore[assignment]

from agent_browser.browser import BrowserBackend, BrowserPageHandle

logger = logging.getLogger(__name__)


# ── Circuit breaker state ──────────────────────────────────────


class CircuitState(Enum):
    CLOSED = "closed"  # Normal: stealth active
    OPEN = "open"  # Degraded: stealth disabled


@dataclass
class _PerSessionCircuit:
    """Per-session circuit breaker state (not a global singleton)."""

    failure_count: int = 0
    state: CircuitState = CircuitState.CLOSED
    threshold: int = 5

    def record_failure(self) -> bool:
        """Record a failure; return whether the circuit should trip open."""
        self.failure_count += 1
        if self.failure_count >= self.threshold:
            self.state = CircuitState.OPEN
            logger.warning(
                f"Circuit OPEN after {self.failure_count} stealth failures; disabling stealth for this session"
            )
            return True
        return False

    @property
    def is_active(self) -> bool:
        return self.state == CircuitState.CLOSED


# ── Operation classification ──────────────────────────────────

# Interactive operations that need stealth wrapping (mapped to StealthEnhancer delay types)
_STEALTH_OPS: dict[str, str] = {
    "goto": "navigate",
    "go_back": "navigate",
    "mouse_wheel": "scroll",
    "mouse_move": "general",  # mouse movement itself is a stealth behavior
    "keyboard_press": "input",
}

# Pass-through operations (read-only or non-interactive, no delay needed)
_PASSTHROUGH_OPS = frozenset(
    {
        "evaluate",
        "wait_for_selector",
        "title",
        "url",
        "on",
        "remove_listener",
        "close",
    }
)


# ── StealthPageHandle ─────────────────────────────────────────


class StealthPageHandle(BrowserPageHandle):
    """
    Wraps BrowserPageHandle to automatically inject stealth behavior on every operation.

    Implements the same interface as BrowserPageHandle.
    Safe for RemotePageHandle (does not depend on raw_page attribute).
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
        # Cache raw_page reference (RemotePageHandle does not have one)
        self._raw_page = getattr(wrapped, "raw_page", None)

    # ── Navigation (stealth-wrapped) ──

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

    # ── JavaScript execution (pass-through) ──

    async def evaluate(self, expression: str) -> Any:
        return await self._wrapped.evaluate(expression)

    # ── Element wait (pass-through) ──

    async def wait_for_selector(self, selector: str, timeout: int = 10000) -> None:
        return await self._wrapped.wait_for_selector(selector, timeout=timeout)

    # ── Mouse operations (stealth-wrapped) ──

    async def mouse_wheel(self, delta_x: int, delta_y: int) -> None:
        await self._pre("mouse_wheel")
        try:
            await self._wrapped.mouse_wheel(delta_x, delta_y)
        finally:
            await self._post("mouse_wheel")

    async def mouse_move(self, x: float, y: float) -> None:
        """Mouse movement is itself a stealth behavior -- uses Bezier curves."""
        if not self._circuit.is_active or self._raw_page is None:
            await self._wrapped.mouse_move(x, y)
            return
        try:
            await self._stealth.random_mouse_move(self._raw_page)
        except Exception as e:
            self._circuit.record_failure()
            logger.debug(f"Stealth mouse_move failed: {e}")
        await self._wrapped.mouse_move(x, y)

    # ── Keyboard operations (stealth-wrapped) ──

    async def keyboard_press(self, key: str) -> None:
        await self._pre("keyboard_press")
        try:
            await self._wrapped.keyboard_press(key)
        finally:
            await self._post("keyboard_press")

    # ── Page info (pass-through) ──

    async def title(self) -> str:
        return await self._wrapped.title()

    async def url(self) -> str:
        return await self._wrapped.url()

    # ── Event listeners (pass-through) ──

    async def on(self, event: str, handler) -> None:
        await self._wrapped.on(event, handler)

    def remove_listener(self, event: str, handler) -> None:
        self._wrapped.remove_listener(event, handler)

    # ── Lifecycle (pass-through) ──

    async def close(self) -> None:
        await self._wrapped.close()

    # ── Internal methods ──

    async def _pre(self, operation: str) -> None:
        """Pre-action stealth delay."""
        if not self._circuit.is_active:
            return
        action_type = _STEALTH_OPS.get(operation, "general")
        try:
            await self._stealth.pre_action(action_type)
        except Exception as e:
            self._circuit.record_failure()
            logger.warning(f"Stealth pre_action({action_type}) failed: {e}")

    async def _post(self, operation: str) -> None:
        """Post-action stealth pause."""
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
        """Expose raw page (for code paths that need raw_page access)."""
        return self._raw_page

    @property
    def wrapped(self) -> BrowserPageHandle:
        """Access the wrapped handle (for advanced usage)."""
        return self._wrapped


# ── StealthMiddleware ──────────────────────────────────────────


class StealthMiddleware:
    """
    Centralized stealth middleware.

    Wraps BrowserBackend to automatically inject stealth behavior into all operations.

    Usage::

        backend = LocalCDPBackend(config)
        middleware = StealthMiddleware(backend, config)
        page_handle = await middleware.create_session("user_1")
        # page_handle is a StealthPageHandle; all operations are auto-stealthed
    """

    def __init__(self, backend: BrowserBackend, config):
        """
        Args:
            backend: underlying BrowserBackend (LocalCDPBackend or RemoteAPIBackend)
            config: SkillConfig (reads stealth_enabled etc.)
        """
        self._backend = backend
        self._config = config
        self._stealth: StealthEnhancer | None = None
        self._circuits: dict[str, _PerSessionCircuit] = {}

        # Only initialize StealthEnhancer when enabled
        stealth_enabled = getattr(config, "stealth_enabled", True)
        if stealth_enabled:
            if StealthEnhancer is not None:
                # Resolve stealth profile from config or env
                from agent_browser.stealth.profiles import resolve_stealth_profile, profile_from_env

                profile_name = getattr(config, "stealth_profile", None)
                try:
                    profile = resolve_stealth_profile(profile_name) if profile_name else profile_from_env()
                except ValueError:
                    logger.warning("Invalid stealth_profile '%s', using env/default", profile_name)
                    profile = profile_from_env()

                self._stealth = StealthEnhancer(profile=profile)
                logger.info(
                    "StealthMiddleware initialized (stealth ON, profile=%s)",
                    profile.name,
                )
            else:
                logger.warning(
                    "StealthEnhancer not available (CloakBrowser not installed); running in pass-through mode"
                )
        else:
            logger.info("StealthMiddleware initialized (stealth OFF -- pass-through)")

    # ── Backend delegation methods ──

    async def connect(self) -> None:
        """Connect to the underlying backend."""
        await self._backend.connect()

    async def disconnect(self) -> None:
        """Disconnect from the underlying backend."""
        await self._backend.disconnect()

    async def is_connected(self) -> bool:
        return await self._backend.is_connected()

    # ── Session management (core: wrap handle on creation) ──

    async def create_session(self, session_id: str) -> BrowserPageHandle:
        """
        Create a session and wrap the PageHandle with stealth.

        When stealth is enabled:
          1. Inject timing noise (JS fingerprint defense)
          2. Return StealthPageHandle (all operations auto-stealthed)

        When stealth is disabled or circuit is open:
          Return raw PageHandle (zero-overhead pass-through)
        """
        page_handle = await self._backend.create_session(session_id)

        if self._stealth is None:
            return page_handle

        # Per-session circuit breaker
        circuit = _PerSessionCircuit(threshold=5)
        self._circuits[session_id] = circuit

        try:
            # Inject JS timing noise (Layer 6: timing fingerprint defense)
            raw_page = getattr(page_handle, "raw_page", None)
            if raw_page is not None:
                await StealthEnhancer.inject_timing_noise(raw_page)

            # Wrap into StealthPageHandle
            return StealthPageHandle(page_handle, self._stealth, circuit)

        except Exception as e:
            logger.warning(f"Stealth injection failed for session {session_id}: {e}")
            circuit.record_failure()
            return page_handle  # Degraded: return unwrapped handle

    async def delete_session(self, session_id: str) -> None:
        """Delete session and clean up per-session circuit state."""
        self._circuits.pop(session_id, None)
        await self._backend.delete_session(session_id)

    async def get_page(self, session_id: str) -> BrowserPageHandle:
        """Get page handle (may be StealthPageHandle or raw handle)."""
        return await self._backend.get_page(session_id)

    # ── Snapshot/refs (delegate to backend) ──

    async def snapshot(self, session_id: str, interactive_only: bool = False) -> dict:
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

    # ── Stealth convenience methods (backward compat) ──

    async def stealth_delay(self, action_type: str = "general") -> None:
        """Manually trigger stealth delay (backward compatibility with old code)."""
        if self._stealth and self._stealth:
            await self._stealth.pre_action(action_type)

    async def stealth_mouse_move(self, session_id: str) -> None:
        """Manually trigger mouse wandering (backward compatibility with old code)."""
        if self._stealth is None:
            return
        page = await self.get_page(session_id)
        raw_page = getattr(page, "raw_page", None)
        if raw_page is not None:
            try:
                await self._stealth.random_mouse_move(raw_page)
            except Exception as e:
                logger.debug(f"Manual stealth_mouse_move failed: {e}")

    # ── Agent task execution (delegate to backend) ──

    async def run_task(
        self,
        session_id: str,
        task: str,
        intelligence: str = "agent",
        llm_config: dict | None = None,
        max_steps: int = 6,
        total_timeout: float = 300.0,
        **kwargs,
    ) -> dict:
        """
        Execute an Agent task (delegates to backend run_task).

        total_timeout: overall timeout in seconds, prevents infinite blocking.
                     Default 300s (5 minutes).
        """
        if not hasattr(self._backend, "run_task"):
            return {"status": "failed", "error": "run_task() not supported by current backend"}

        # Wrap with timeout control
        if total_timeout > 0:
            try:
                return await asyncio.wait_for(
                    self._backend.run_task(
                        session_id,
                        task,
                        intelligence=intelligence,
                        llm_config=llm_config,
                        max_steps=max_steps,
                        **kwargs,
                    ),
                    timeout=total_timeout,
                )
            except TimeoutError:
                return {
                    "status": "timeout",
                    "error": f"Task exceeded {total_timeout}s limit",
                    "steps": max_steps,
                }

        return await self._backend.run_task(
            session_id,
            task,
            intelligence=intelligence,
            llm_config=llm_config,
            max_steps=max_steps,
            **kwargs,
        )

    # ── New Actions (delegate to backend) ──────────────────────

    async def search_page(
        self, session_id: str, pattern: str, **kwargs,
    ) -> dict:
        if hasattr(self._backend, "search_page"):
            return await self._backend.search_page(session_id, pattern, **kwargs)
        raise NotImplementedError("search_page() not supported by current backend")

    async def find_elements(self, session_id: str, selector: str, **kwargs) -> list[dict]:
        if hasattr(self._backend, "find_elements"):
            return await self._backend.find_elements(session_id, selector, **kwargs)
        raise NotImplementedError("find_elements() not supported by current backend")

    async def get_dropdown_options(self, session_id: str, ref: str) -> list[dict]:
        if hasattr(self._backend, "get_dropdown_options"):
            return await self._backend.get_dropdown_options(session_id, ref)
        raise NotImplementedError("get_dropdown_options() not supported by current backend")

    async def select_dropdown_option(self, session_id: str, ref: str, option_text: str) -> None:
        if hasattr(self._backend, "select_dropdown_option"):
            return await self._backend.select_dropdown_option(session_id, ref, option_text)
        raise NotImplementedError("select_dropdown_option() not supported by current backend")

    async def upload_file(self, session_id: str, ref: str, file_paths: list[str]) -> None:
        if hasattr(self._backend, "upload_file"):
            return await self._backend.upload_file(session_id, ref, file_paths)
        raise NotImplementedError("upload_file() not supported by current backend")

    async def screenshot(self, session_id: str, **kwargs) -> bytes:
        if hasattr(self._backend, "screenshot"):
            return await self._backend.screenshot(session_id, **kwargs)
        raise NotImplementedError("screenshot() not supported by current backend")

    async def save_as_pdf(self, session_id: str, **kwargs) -> str:
        if hasattr(self._backend, "save_as_pdf"):
            return await self._backend.save_as_pdf(session_id, **kwargs)
        raise NotImplementedError("save_as_pdf() not supported by current backend")

    async def scroll_to_text(self, session_id: str, text: str, **kwargs) -> bool:
        if hasattr(self._backend, "scroll_to_text"):
            return await self._backend.scroll_to_text(session_id, text, **kwargs)
        raise NotImplementedError("scroll_to_text() not supported by current backend")

    async def switch_tab(self, session_id: str, index: int) -> None:
        if hasattr(self._backend, "switch_tab"):
            return await self._backend.switch_tab(session_id, index)
        raise NotImplementedError("switch_tab() not supported by current backend")

    async def open_tab(self, session_id: str, url: str | None = None) -> int:
        if hasattr(self._backend, "open_tab"):
            return await self._backend.open_tab(session_id, url=url)
        raise NotImplementedError("open_tab() not supported by current backend")

    async def close_tab(self, session_id: str, index: int | None = None) -> None:
        if hasattr(self._backend, "close_tab"):
            return await self._backend.close_tab(session_id, index=index)
        raise NotImplementedError("close_tab() not supported by current backend")

    async def extract_content(self, session_id: str, **kwargs) -> str:
        if hasattr(self._backend, "extract_content"):
            return await self._backend.extract_content(session_id, **kwargs)
        raise NotImplementedError("extract_content() not supported by current backend")

    async def get_tabs_info(self, session_id: str) -> list[dict]:
        if hasattr(self._backend, "get_tabs_info"):
            return await self._backend.get_tabs_info(session_id)
        raise NotImplementedError("get_tabs_info() not supported by current backend")

    # ── Property access ──

    @property
    def backend(self) -> BrowserBackend:
        """Access the underlying backend (for scenarios needing direct access)."""
        return self._backend

    @property
    def stealth(self) -> StealthEnhancer | None:
        """Access the StealthEnhancer instance."""
        return self._stealth

    @property
    def circuits(self) -> dict[str, _PerSessionCircuit]:
        """Access per-session circuit states (for monitoring/debugging)."""
        return dict(self._circuits)  # Return a copy
