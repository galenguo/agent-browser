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

import time
import asyncio
from enum import Enum
from typing import Optional, Any, List, Dict, TYPE_CHECKING
from dataclasses import dataclass, field
from pydantic import BaseModel

if TYPE_CHECKING:
    from playwright.async_api import Playwright, Browser


# ============ Enums ============

class BrowserType(str, Enum):
    """Browser engine type."""
    CHROMIUM = "chromium"   # CloakBrowser + patchright (default)


# ============ Exception classes ============

class ResourceExhaustedError(Exception):
    """Resource exhausted exception (max concurrency reached)."""
    pass


class SessionNotFoundError(Exception):
    """Session not found exception."""
    pass


# Re-export PipelineError from pipeline layer (for API layer consumption)
from agent_browser.pipeline.errors import PipelineError as PipelineError


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
    browser: Any = None     # playwright.async_api.Browser


@dataclass
class DockerBrowserInstance(BrowserInstance):
    """Docker browser instance (container)."""
    container: Any = None  # docker.models.containers.Container
    container_name: str = None
    novnc_host_port: Optional[int] = None   # Allocated host noVNC port (Mode B)
    # Public access info (requires BROWSER_PUBLIC_HOST env var)
    public_host: Optional[str] = None       # Public IP or domain name
    public_cdp_port: Optional[int] = None   # Public CDP port (Mode B has it, Mode D does not)
    public_novnc_port: Optional[int] = None # Public noVNC port
    novnc_url: Optional[str] = None         # Full noVNC monitoring URL

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
    delay: Optional[int] = None  # Click delay in ms


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
    selector: Optional[str] = None  # CSS selector
    timeout: int = 10000  # ms
    state: str = "visible"  # visible | hidden | attached | detached


# ============ Atomic operation response models ============

class ElementInfo(BaseModel):
    """Element information."""
    ref: str  # @e0, @e1...
    tag: str
    text: Optional[str] = None
    role: Optional[str] = None
    type: Optional[str] = None
    placeholder: Optional[str] = None
    href: Optional[str] = None
    is_visible: bool = True
    is_enabled: bool = True
    bounding_box: Optional[Dict] = None


class SnapshotResponse(BaseModel):
    """Snapshot response."""
    url: str
    title: str
    elements: List[ElementInfo]
    raw_html_size: Optional[int] = None
    snapshot_size: Optional[int] = None
