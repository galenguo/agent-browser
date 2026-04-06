"""Data model definitions.

Contains:
- BrowserType (browser type enum)
- BrowserInstance (browser instance base class)
- LocalBrowserInstance (local Chromium browser instance)
- DockerBrowserInstance (Docker browser instance)
- UserSession (user session)
- Atomic operation request models
- Exception classes
"""

import asyncio
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

if TYPE_CHECKING:
    pass


# ============ Enums ============


class BrowserType(StrEnum):
    """Browser engine type."""

    CHROMIUM = "chromium"  # CloakBrowser + patchright (default)


# ============ Exception classes ============


class ResourceExhaustedError(Exception):
    """Resource exhausted exception (max concurrency reached)."""


class SessionNotFoundError(Exception):
    """Session not found exception."""


from agent_browser.pipeline.errors import (  # noqa: E402
    PipelineError as PipelineError,
)

# ============ Browser instances ============


@dataclass
class BrowserInstance:
    """Browser instance base class."""

    instance_id: str
    cdp_url: str
    cdp_port: int
    session_id: str
    created_at: float = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = time.time()


@dataclass
class LocalBrowserInstance(BrowserInstance):
    """Local browser instance (process)."""

    playwright: Any = None  # playwright.async_api.Playwright
    browser: Any = None  # playwright.async_api.Browser


@dataclass
class DockerBrowserInstance(BrowserInstance):
    """Docker browser instance (container)."""

    container: Any = None  # docker.models.containers.Container
    container_name: str = None
    novnc_host_port: int | None = None  # Allocated host noVNC port (Mode B)
    # Public access info (requires BROWSER_PUBLIC_HOST env var)
    public_host: str | None = None  # Public IP or domain name
    public_cdp_port: int | None = None  # Public CDP port (Mode B has it, Mode D does not)
    public_novnc_port: int | None = None  # Public noVNC port
    novnc_url: str | None = None  # Full noVNC monitoring URL

    def __post_init__(self):
        super().__post_init__()
        if self.container_name is None:
            self.container_name = f"browser_{self.session_id}"


# ============ User sessions ============


@dataclass
class UserSession:
    """User session."""

    session_id: str
    user_id: str
    browser_instance: BrowserInstance
    profile_dir: str
    created_at: float
    last_activity: float
    tasks: dict = None  # task_id -> task_info
    task_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def __post_init__(self):
        if self.tasks is None:
            self.tasks = {}

    def is_idle(self, timeout: int) -> bool:
        """Check if session has been idle beyond timeout."""
        return time.time() - self.last_activity > timeout

    def mark_activity(self):
        """Mark activity timestamp."""
        self.last_activity = time.time()


# ============ Atomic operation request models (Pydantic) ============


class NavigateRequest(BaseModel):
    """Page navigation request."""

    url: str
    wait_until: str = "domcontentloaded"  # load | domcontentloaded | networkidle
    timeout: int = 30000  # ms


class ClickRequest(BaseModel):
    """Click element request."""

    ref: str  # Element reference, e.g., @e0, @e1
    button: str = "left"  # left | right | middle
    click_count: int = 1
    delay: int | None = None  # Click delay in ms


class FillRequest(BaseModel):
    """Fill input field request."""

    ref: str  # Element reference
    text: str
    clear_first: bool = True  # Whether to clear first
    human_like: bool = False  # Whether to simulate human input


class EvaluateRequest(BaseModel):
    """Execute JavaScript request."""

    expression: str
    return_by_value: bool = True


class ScrollRequest(BaseModel):
    """Scroll request."""

    direction: str = "down"  # up | down
    amount: int = 300  # pixels
    smooth: bool = True


class WaitRequest(BaseModel):
    """Wait request."""

    selector: str | None = None  # CSS selector
    timeout: int = 10000  # ms
    state: str = "visible"  # visible | hidden | attached | detached


# ============ Atomic operation response models ============


class ElementInfo(BaseModel):
    """Element information."""

    ref: str  # @e0, @e1...
    tag: str
    text: str | None = None
    role: str | None = None
    type: str | None = None
    placeholder: str | None = None
    href: str | None = None
    is_visible: bool = True
    is_enabled: bool = True
    bounding_box: dict | None = None


class SnapshotResponse(BaseModel):
    """Snapshot response."""

    url: str
    title: str
    elements: list[ElementInfo]
    raw_html_size: int | None = None
    snapshot_size: int | None = None
