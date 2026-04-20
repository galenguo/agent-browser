"""Browser backend abstraction layer.

Defines BrowserBackend and BrowserPageHandle ABCs that all backend
implementations must follow.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any


class BrowserPageHandle(ABC):
    """Unified page operation interface.

    Two implementations:
    - PlaywrightPageHandle: delegates to Playwright Page (local CDP)
    - RemotePageHandle: translates to HTTP REST calls (remote API)
    """

    # -- Navigation --

    @abstractmethod
    async def goto(self, url: str, wait_until: str = "domcontentloaded", timeout: int = 8000) -> None:
        """Navigate to URL."""

    @abstractmethod
    async def go_back(self, wait_until: str = "domcontentloaded", timeout: int = 10000) -> None:
        """Navigate back."""

    # -- JavaScript execution --

    @abstractmethod
    async def evaluate(self, expression: str) -> Any:
        """Execute JavaScript and return result."""

    # -- Element operations --

    @abstractmethod
    async def wait_for_selector(self, selector: str, timeout: int = 10000) -> None:
        """Wait for selector to appear."""

    # -- Mouse / keyboard --

    @abstractmethod
    async def mouse_wheel(self, delta_x: int, delta_y: int) -> None:
        """Mouse wheel scroll."""

    @abstractmethod
    async def mouse_move(self, x: float, y: float) -> None:
        """Move mouse to coordinates."""

    @abstractmethod
    async def keyboard_press(self, key: str) -> None:
        """Press a key."""

    # -- Page info --

    @abstractmethod
    async def title(self) -> str:
        """Get page title."""

    @abstractmethod
    async def url(self) -> str:
        """Get current URL."""

    # -- Event listeners --

    @abstractmethod
    async def on(self, event: str, handler: Callable) -> None:
        """Register event listener (needed by explore network interception)."""

    @abstractmethod
    def remove_listener(self, event: str, handler: Callable) -> None:
        """Remove event listener."""

    # -- Lifecycle --

    @abstractmethod
    async def close(self) -> None:
        """Close page."""


class BrowserBackend(ABC):
    """Browser backend abstraction.

    Two implementations:
    - LocalCDPBackend: Playwright CDP direct connection (local browser)
    - RemoteAPIBackend: HTTP REST to FastAPI (remote / local service)
    - ExtensionBackend: Chrome Extension via chrome.debugger
    """

    @abstractmethod
    async def connect(self) -> None:
        """Establish browser connection."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect browser."""

    @abstractmethod
    async def is_connected(self) -> bool:
        """Check if connection is alive."""

    @abstractmethod
    async def create_session(self, session_id: str) -> BrowserPageHandle:
        """Create browser session (context + page), return page handle."""

    @abstractmethod
    async def delete_session(self, session_id: str) -> None:
        """Delete browser session."""

    @abstractmethod
    async def get_page(self, session_id: str) -> BrowserPageHandle:
        """Get page handle for a session."""

    @abstractmethod
    async def run_task(
        self,
        session_id: str,
        task: str,
        intelligence: str = "agent",
        llm_config: dict | None = None,
        max_steps: int = 6,
        **kwargs,
    ) -> dict:
        """Execute intelligent task (agent mode: browser-use; llm mode: tool descriptions)."""
