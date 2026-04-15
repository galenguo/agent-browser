"""CLI session manager -- file-based persistence for cross-process session sharing.

Provides:
  CLISession       -- session record dataclass
  CLISessionManager -- JSON file-based session store (~/.agent-browser/sessions.json)
  SessionContext   -- in-process session context (browser_instance + controller)
  UnifiedSessionManager -- in-memory session lifecycle manager (CLI mode)
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_STORAGE = Path.home() / ".agent-browser" / "sessions.json"


# ── Data models ────────────────────────────────────────────────────────────────


@dataclass
class CLISession:
    """Persisted session record (stored in sessions.json)."""

    session_id: str
    browser_instance_id: str
    cdp_url: str
    mode: str  # "local" | "remote"
    profile_path: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_used: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    task_count: int = 0


@dataclass
class SessionContext:
    """In-process session context (not persisted)."""

    session_id: str
    browser_instance: Any
    browser_session: Any
    controller: Any
    mode: str
    browser_mode: str


# ── CLISessionManager ──────────────────────────────────────────────────────────


class CLISessionManager:
    """File-based session persistence for cross-process sharing.

    Stores session records as JSON at ``storage_path`` (default
    ``~/.agent-browser/sessions.json``).  All mutations are atomic: read →
    modify → write so concurrent CLI invocations don't corrupt the file.
    """

    def __init__(self, storage_path: Path | None = None) -> None:
        self._path = Path(storage_path) if storage_path else DEFAULT_STORAGE
        self._path.parent.mkdir(parents=True, exist_ok=True)

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _read(self) -> dict[str, dict]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _write(self, data: dict[str, dict]) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    # ── Public API ─────────────────────────────────────────────────────────────

    def create(
        self,
        session_id: str,
        cdp_url: str,
        mode: str = "local",
        profile_path: str | None = None,
    ) -> CLISession:
        """Create and persist a new session record."""
        sess = CLISession(
            session_id=session_id,
            browser_instance_id=session_id,
            cdp_url=cdp_url,
            mode=mode,
            profile_path=profile_path,
        )
        data = self._read()
        data[session_id] = asdict(sess)
        self._write(data)
        return sess

    def get(self, session_id: str) -> CLISession | None:
        """Return session record or None if not found."""
        data = self._read()
        raw = data.get(session_id)
        if raw is None:
            return None
        return CLISession(**raw)

    def list_all(self) -> dict[str, CLISession]:
        """Return all session records keyed by session_id."""
        return {sid: CLISession(**raw) for sid, raw in self._read().items()}

    def delete(self, session_id: str) -> None:
        """Remove session record (no-op if not found)."""
        data = self._read()
        data.pop(session_id, None)
        self._write(data)

    def update_last_used(self, session_id: str) -> None:
        """Bump last_used timestamp and increment task_count."""
        data = self._read()
        if session_id in data:
            data[session_id]["last_used"] = datetime.now(timezone.utc).isoformat()
            data[session_id]["task_count"] = data[session_id].get("task_count", 0) + 1
            self._write(data)


# ── UnifiedSessionManager ──────────────────────────────────────────────────────


class UnifiedSessionManager:
    """In-memory browser instance manager for CLI mode.

    Manages the lifecycle of ``SessionContext`` objects.  Sessions are kept
    in memory only; use ``CLISessionManager`` for cross-process persistence.
    """

    def __init__(self, mode: str = "cli", max_concurrent: int = 5) -> None:
        self.mode = mode
        self.max_concurrent = max_concurrent
        self.sessions: dict[str, SessionContext] = {}

    async def create_session(
        self,
        session_id: str | None = None,
        browser_mode: str = "local",
        cdp_url: str | None = None,
    ) -> SessionContext:
        """Create a new browser session context.

        For ``browser_mode="local"``, launches a local CDP browser via
        ``BrowserDaemon``.  For ``browser_mode="remote"``, connects to the
        provided ``cdp_url``.
        """
        import uuid

        from browser_use.browser import BrowserProfile, BrowserSession

        from agent_browser.models import BrowserInstance
        from agent_browser.stealth.browser_controller import BrowserController

        if len(self.sessions) >= self.max_concurrent:
            raise RuntimeError(
                f"Max concurrent sessions reached ({self.max_concurrent}). "
                "Destroy an existing session first."
            )

        sid = session_id or f"cli_{uuid.uuid4().hex[:8]}"

        if browser_mode == "remote" and cdp_url:
            target_cdp = cdp_url
        else:
            # Local mode: use BrowserDaemon to get a persistent CDP connection
            from agent_browser.browser.daemon import BrowserDaemon

            daemon = BrowserDaemon()
            await daemon.ensure_connected()
            context = await daemon.create_context(sid)
            target_cdp = daemon.cdp_url

        browser_session = BrowserSession(
            browser_profile=BrowserProfile(cdp_url=target_cdp, is_local=True)
        )
        await browser_session.start()

        instance = BrowserInstance(
            instance_id=sid,
            cdp_url=target_cdp,
            cdp_port=0,
            session_id=sid,
        )
        controller = BrowserController(browser_session, sid)

        ctx = SessionContext(
            session_id=sid,
            browser_instance=instance,
            browser_session=browser_session,
            controller=controller,
            mode=self.mode,
            browser_mode=browser_mode,
        )
        self.sessions[sid] = ctx
        return ctx

    async def get_session(self, session_id: str) -> SessionContext:
        """Return session context or raise if not found."""
        ctx = self.sessions.get(session_id)
        if ctx is None:
            raise KeyError(f"Session not found in memory: {session_id}")
        return ctx

    async def destroy_session(self, session_id: str) -> None:
        """Close browser session and remove from memory."""
        ctx = self.sessions.pop(session_id, None)
        if ctx is None:
            return
        try:
            await ctx.browser_session.close()
        except Exception:
            pass
