"""AgentBrowser -- clean OOP interface to the agent-browser package.

Provides an object-oriented wrapper around the functional API in main.py.
The key UX improvement: tracks the "current" session_id so callers can omit
it from every method after calling create_session().

Usage::

    ab = AgentBrowser()
    session_id = await ab.create_session()
    await ab.open_page("https://example.com")
    snap = await ab.snapshot()          # no session_id needed
    await ab.click("@e0")
    await ab.delete_session()

    # Context manager:
    async with AgentBrowser() as ab:
        await ab.create_session()
        await ab.open_page("https://example.com")
        # auto-cleanup on exit
"""

import contextlib
from typing import Any

from .config import SkillConfig
from .main import (
    click as _click,
)
from .main import (
    configure as _configure,
)
from .main import (
    create_session as _create_session,
)
from .main import (
    debug_pipeline as _debug_pipeline,
)
from .main import (
    delete_session as _delete_session,
)
from .main import (
    evaluate as _evaluate,
)
from .main import (
    fill as _fill,
)
from .main import (
    go_back as _go_back,
)
from .main import (
    hover as _hover,
)
from .main import (
    open_page as _open_page,
)
from .main import (
    press_key as _press_key,
)
from .main import (
    reset as _reset,
)
from .main import (
    run_task as _run_task,
)
from .main import (
    scroll as _scroll,
)
from .main import (
    select_option as _select_option,
)
from .main import (
    setup as _setup,
)
from .main import (
    snapshot as _snapshot,
)
from .main import (
    wait_for_selector as _wait_for_selector,
)


class AgentBrowser:
    """Object-oriented facade for the agent-browser automation library.

    Every method that accepts a ``session_id`` parameter makes it optional.
    When omitted, the instance uses the session returned by the most recent
    :meth:`create_session` call (or the one passed to the constructor).

    The class performs **lazy initialization** -- no browser connection is
    established until the first operation is invoked.
    """

    def __init__(self, config: SkillConfig | None = None, session_id: str | None = None):
        """Create an AgentBrowser instance.

        Args:
            config: Optional pre-built :class:`SkillConfig`.  When ``None``
                the library auto-detects mode on first use.
            session_id: Optional existing session to bind immediately,
                skipping the need to call :meth:`create_session`.
        """
        self._config = config
        self._session_id: str | None = session_id

    # ── properties ──────────────────────────────────────────────

    @property
    def session_id(self) -> str | None:
        """The current session ID (set by :meth:`create_session` or constructor)."""
        return self._session_id

    @session_id.setter
    def session_id(self, value: str | None) -> None:
        self._session_id = value

    # ── context manager ─────────────────────────────────────────

    async def __aenter__(self) -> "AgentBrowser":
        await _setup()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._session_id:
            with contextlib.suppress(Exception):
                await _delete_session(self._session_id)  # best-effort cleanup
            self._session_id = None
        _reset()

    # ── lifecycle ───────────────────────────────────────────────

    async def create_session(self, **kwargs) -> str:
        """Create a new browser session and set it as the current session.

        All keyword arguments are forwarded to the underlying
        ``create_session()`` function (e.g. ``cdp_url``, ``mode``,
        ``api_url``).

        Returns:
            The new session ID string.
        """
        sid = await _create_session(**kwargs)
        self._session_id = sid
        return sid

    async def delete_session(self, session_id: str | None = None) -> None:
        """Delete a browser session.

        Args:
            session_id: Session to delete.  Defaults to the current session.
                After deletion the current session ID is cleared.
        """
        sid = session_id or self._session_id
        if sid is None:
            raise RuntimeError("No session available. Call create_session() first.")
        await _delete_session(sid)
        if self._session_id == sid:
            self._session_id = None

    # ── navigation ──────────────────────────────────────────────

    async def open_page(self, url: str, session_id: str | None = None) -> None:
        """Navigate the browser to *url*.

        Args:
            url: Target URL.
            session_id: Session to use.  Defaults to the current session.
        """
        await _open_page(self._resolve(session_id), url)

    async def go_back(self, session_id: str | None = None) -> None:
        """Navigate back in history.

        Args:
            session_id: Session to use.  Defaults to the current session.
        """
        await _go_back(self._resolve(session_id))

    # ── inspection ──────────────────────────────────────────────

    async def snapshot(
        self, session_id: str | None = None, interactive_only: bool = False
    ) -> dict:
        """Return a snapshot of the current page DOM.

        Args:
            session_id: Session to use.  Defaults to the current session.
            interactive_only: If True, only include interactive elements.

        Returns:
            Dict containing element refs, text content, and structure.
        """
        return await _snapshot(self._resolve(session_id), interactive_only=interactive_only)

    # ── interaction ─────────────────────────────────────────────

    async def click(self, ref: str, session_id: str | None = None) -> None:
        """Click an element by its data-ab-ref (e.g. ``"@e0"``).

        Args:
            ref: Element reference string (``@e<digits>``).
            session_id: Session to use.  Defaults to the current session.
        """
        await _click(self._resolve(session_id), ref)

    async def fill(
        self, ref: str, text: str, session_id: str | None = None
    ) -> None:
        """Fill an input element with *text*.

        Args:
            ref: Element reference string (``@e<digits>``).
            text: Value to type into the element.
            session_id: Session to use.  Defaults to the current session.
        """
        await _fill(self._resolve(session_id), ref, text)

    async def scroll(
        self,
        amount: int = 300,
        direction: str = "down",
        session_id: str | None = None,
    ) -> None:
        """Scroll the page.

        Args:
            amount: Pixels to scroll (default 300).
            direction: ``"down"`` or ``"up"`` (default ``"down"``).
            session_id: Session to use.  Defaults to the current session.
        """
        await _scroll(self._resolve(session_id), direction=direction, amount=amount)

    async def evaluate(
        self,
        expression: str,
        session_id: str | None = None,
    ):
        """Execute JavaScript in the page and return the result.

        Args:
            expression: JavaScript expression to evaluate.
            session_id: Session to use.  Defaults to the current session.

        Returns:
            The result of the JavaScript evaluation.
        """
        return await _evaluate(self._resolve(session_id), expression)

    async def select_option(
        self, ref: str, value: str, session_id: str | None = None
    ) -> None:
        """Select an option in a ``<select>`` element.

        Args:
            ref: Element reference string (``@e<digits>``).
            value: Option value to select.
            session_id: Session to use.  Defaults to the current session.
        """
        await _select_option(self._resolve(session_id), ref, value)

    async def hover(self, ref: str, session_id: str | None = None) -> None:
        """Move the mouse over an element.

        Args:
            ref: Element reference string (``@e<digits>``).
            session_id: Session to use.  Defaults to the current session.
        """
        await _hover(self._resolve(session_id), ref)

    async def press_key(self, key: str, session_id: str | None = None) -> None:
        """Press a keyboard key.

        Args:
            key: Key name (e.g. ``"Enter"``, ``"Tab"``, ``"ArrowDown"``).
            session_id: Session to use.  Defaults to the current session.
        """
        await _press_key(self._resolve(session_id), key)

    async def wait_for_selector(
        self,
        selector: str,
        timeout: int = 10000,
        session_id: str | None = None,
    ) -> None:
        """Wait for a CSS selector to appear in the DOM.

        Args:
            selector: CSS selector string.
            timeout: Maximum wait time in milliseconds (default 10000).
            session_id: Session to use.  Defaults to the current session.
        """
        await _wait_for_selector(self._resolve(session_id), selector, timeout=timeout)

    # ── high-level / agent ──────────────────────────────────────

    async def run_task(
        self,
        task: str,
        intelligence: str = "agent",
        session_id: str | None = None,
        **kwargs,
    ) -> dict:
        """Execute a natural-language task using LLM/Agent intelligence.

        Args:
            task: Natural language description of what to do.
            intelligence: ``"llm"`` or ``"agent"`` (default ``"agent"``).
            session_id: Session to use.  Defaults to the current session.
            **kwargs: Extra arguments forwarded to the backend
                (e.g. ``llm_config``, ``max_steps``, ``total_timeout``).

        Returns:
            Result dict from the agent execution.
        """
        return await _run_task(
            self._resolve(session_id),
            task,
            intelligence=intelligence,
            **kwargs,
        )

    async def debug_pipeline(
        self,
        site: str,
        command: str,
        args: dict | None = None,
        breakpoints: list | None = None,
        session_id: str | None = None,
        **kwargs,
    ) -> Any:
        """Debug-mode pipeline execution with breakpoint support.

        Args:
            site: Site name (e.g. ``"boss"``).
            command: Command name (e.g. ``"search"``).
            args: Adapter parameters.
            breakpoints: Step indices at which to pause.
            session_id: Session to use.  Defaults to the current session.
            **kwargs: Forwarded to the underlying debugger.

        Returns:
            Breakpoint state dict or final result.
        """
        return await _debug_pipeline(
            self._resolve(session_id),
            site,
            command,
            args=args,
            breakpoints=breakpoints,
            **kwargs,
        )

    # ── configuration ───────────────────────────────────────────

    def configure(self, **kwargs) -> SkillConfig:
        """Update configuration and return the resulting :class:`SkillConfig`.

        Keyword arguments are forwarded to :func:`configure`.
        """
        return _configure(**kwargs)

    # ── internal helpers ────────────────────────────────────────

    def _resolve(self, session_id: str | None) -> str:
        """Return the explicit *session_id* or fall back to the tracked one."""
        if session_id is not None:
            return session_id
        if self._session_id is not None:
            return self._session_id
        raise RuntimeError(
            "No session available. Call create_session() first, "
            "or pass session_id explicitly."
        )
