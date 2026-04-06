"""BrowserController -- wraps BrowserSession to provide a unified operation interface.

Bridges browser-use's BrowserSession with CLI/API atomic operations.
"""
from dataclasses import dataclass
from typing import Any


@dataclass
class ActionResult:
    """Result of an atomic operation."""
    status: str = "ok"
    error: str | None = None
    data: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"status": self.status}
        if self.error:
            d["error"] = self.error
        if self.data:
            d["data"] = self.data
        return d


class BrowserController:
    """Browser operation controller.

    Wraps browser-use BrowserSession to provide a typed operation interface.
    Used by CLI commands and SessionManager's session context.
    """

    def __init__(self, browser_session, session_id: str):
        self._session = browser_session
        self.session_id = session_id

    @property
    def session(self):
        return self._session
