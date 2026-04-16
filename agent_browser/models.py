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
from typing import TYPE_CHECKING, Any, Literal

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
    container_ip: str | None = None  # Container IP address (for reverse proxy)
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


@dataclass
class K8sBrowserInstance(BrowserInstance):
    """K8s browser node instance (separate browser pod in distributed mode)."""

    pod_index: int = 0   # Kept for model compat; unused in dynamic routing
    pod_url: str = ""    # http://{pod_name}.{headless_svc}:8080
    pod_name: str = ""   # Full pod name (e.g. agent-browser-br-a1b2c3d4) for headless DNS routing
    pod_api_key: str | None = None  # Pod's unique API key for auth proxy
    novnc_url: str | None = None   # Internal noVNC URL (pod DNS :6080)


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
    vnc_token: str = ""  # Random UUID for VNC access authentication
    owner_key: str = ""  # API key that created this session (for ownership-based authorization)
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

    ref: str | None = None  # Element reference, e.g., @e0 (alternative to x/y)
    x: float | None = None  # Viewport X coordinate (alternative to ref)
    y: float | None = None  # Viewport Y coordinate (alternative to ref)
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


# ============ New Action Request Models (browser-use coverage) ============


class SearchPageRequest(BaseModel):
    """Search page text content using regex or plain text."""

    pattern: str
    case_sensitive: bool = False
    is_regex: bool = False
    max_results: int = 10
    context_chars: int = 100
    css_scope: str | None = None  # Limit search to this CSS selector's subtree


class FindElementsRequest(BaseModel):
    """Find elements matching a CSS selector."""

    selector: str
    max_results: int = 50
    return_attributes: list[str] | None = None  # Extra attributes to include


class GetDropdownOptionsRequest(BaseModel):
    """Get options from a <select> element."""

    ref: str  # Element reference (@eN)


class SelectDropdownOptionRequest(BaseModel):
    """Select a dropdown option by visible text (not value)."""

    ref: str  # Element reference (@eN)
    option_text: str  # Visible text of the option to select


class UploadFileRequest(BaseModel):
    """Upload files to an <input type=file> element."""

    ref: str  # Element reference (@eN)
    file_paths: list[str]  # Absolute file paths to upload


class ScreenshotRequest(BaseModel):
    """Take a screenshot of the page or element."""

    ref: str | None = None  # Element reference (None = full page)
    full_page: bool = True
    format: str = "png"  # png | jpeg
    quality: int | None = None  # JPEG quality (1-100), None for PNG
    type: str = "png"  # Deprecated alias for format


class SendKeysRequest(BaseModel):
    """Send a complex key sequence (modifiers + keys)."""

    keys: str  # e.g., "Meta+a", "Shift+Home", "Control+c", "Tab"


class ScrollToTextRequest(BaseModel):
    """Scroll the page until text becomes visible."""

    text: str
    max_scrolls: int = 10
    scroll_amount: int = 500  # pixels per scroll


class TabActionRequest(BaseModel):
    """Multi-tab management request."""

    index: int | None = None  # Tab index (for switch/close)
    url: str | None = None  # URL to navigate (for open_tab)


class ExtractContentRequest(BaseModel):
    """Extract content from the page or element."""

    selector: str | None = None  # CSS scope (None = entire page)
    extract_type: str = "text"  # text | html | markdown | attributes | links | images
    max_length: int | None = None  # Max characters to return


class StructuredOutputRequest(BaseModel):
    """Extract structured data using JSON schema validation."""

    schema: dict  # JSON Schema for the output
    prompt: str = ""  # Optional extraction instructions


class SaveAsPdfRequest(BaseModel):
    """Save the current page as PDF."""

    output_path: str | None = None  # File path (None = auto-generate)
    landscape: bool = False
    format: str = "A4"
    print_background: bool = True
    margin_top: str = "1cm"
    margin_bottom: str = "1cm"
    margin_left: str = "1cm"
    margin_right: str = "1cm"


# ============ BrowserProfile Configuration Models ============


class ProxySettingsModel(BaseModel):
    """Proxy configuration for browser session."""

    server: str  # e.g., "http://proxy.example.com:8080" or "socks5://host:1080"
    username: str | None = None
    password: str | None = None
    bypass: str | None = None  # Comma-separated hosts to bypass


class ViewportSettingsModel(BaseModel):
    """Viewport/window size configuration."""

    width: int = 1280
    height: int = 720


class WatchdogConfigModel(BaseModel):
    """Per-session watchdog configuration."""

    captcha_solver: bool = True
    crash_detection: bool = True
    download_tracking: bool = False
    har_recording: bool = False
    permission_handling: bool = True
    popup_handling: bool = True
    video_recording: bool = False
    screenshot_monitoring: bool = False
    security_monitoring: bool = False


class SessionProfileConfig(BaseModel):
    """Extended session creation parameters (BrowserProfile subset)."""

    viewport: ViewportSettingsModel | None = None
    proxy: ProxySettingsModel | None = None
    user_agent: str | None = None
    headless: bool | None = None
    record_video_dir: str | None = None
    record_har_path: str | None = None
    allowed_domains: list[str] | None = None
    prohibited_domains: list[str] | None = None
    enable_extensions: bool | None = None
    demo_mode: bool | None = None
    auto_download_pdfs: bool | None = None
    device_scale_factor: float | None = None
    window_size: ViewportSettingsModel | None = None
    watchdog: WatchdogConfigModel | None = None


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
    iframe: str | None = None  # Name/id of iframe if element is inside one (for iframe-aware snapshots)


class SnapshotResponse(BaseModel):
    """Snapshot response."""

    url: str
    title: str
    elements: list[ElementInfo]
    raw_html_size: int | None = None
    snapshot_size: int | None = None
    intervention: dict | None = None


class AgentConfig(BaseModel):
    """browser-use Agent configuration for Agent mode tasks.

    Controls how the autonomous browser-use Agent behaves during task execution.
    All fields have sensible defaults matching browser-use's built-in values.
    Pass as ``agent_config`` in ``run_task()`` or the ``/sessions/{id}/task`` endpoint.
    """

    # ── Planning ──────────────────────────────────────────────
    enable_planning: bool = True
    """Enable multi-step planning system. Agent creates/revises a todo list for complex tasks."""
    planning_replan_on_stall: int = 3
    """After N consecutive failures, nudge agent to revise its plan."""
    planning_exploration_limit: int = 5
    """If agent takes this many steps without a plan, nudge it to create one."""

    # ── Judge (post-completion validation) ────────────────────
    use_judge: bool = True
    """Run judge LLM evaluation after task completion to verify success."""

    # ── Thinking mode ─────────────────────────────────────────
    use_thinking: bool = True
    """Enable extended thinking (<<<<<<<) in model responses. Requires model support."""

    # ── Message compaction (token optimization) ─────────────
    message_compaction: bool | None = True
    """Compact message history to stay within context window.
    True = default compaction settings, False = disabled, None = no compaction logic."""

    # ── Reliability ──────────────────────────────────────────
    max_failures: int = 5
    """Max consecutive failures before giving up."""
    final_response_after_failure: bool = True
    """Try one final 'done' action after max_failures before stopping."""
    loop_detection_enabled: bool = True
    """Detect behavioral loops (repeating same actions) and inject recovery nudges."""
    loop_detection_window: int = 20
    """Number of recent steps to analyze for loop detection patterns."""

    # ── Timeouts ──────────────────────────────────────────────
    llm_timeout: int | None = None
    """LLM call timeout in seconds. None = auto-detect based on model (75-90s)."""
    step_timeout: int = 180
    """Max seconds per agent step (including browser operations)."""

    # ── Vision ────────────────────────────────────────────────
    use_vision: bool | Literal["auto"] = False
    """Send page screenshots to LLM. 'auto' excludes screenshot tool from registry.
    Default False avoids vision errors for non-vision models."""
    vision_detail_level: Literal["auto", "low", "high"] = "auto"
    """Screenshot detail level when use_vision is enabled."""

    # ── Flash mode ───────────────────────────────────────────
    flash_mode: bool = False
    """Optimized mode for browser-use's own ChatBrowserUse model (strips plan fields)."""

    # ── System prompt customization ──────────────────────────
    override_system_message: str | None = None
    """Replace the entire system prompt (advanced)."""
    extend_system_message: str | None = None
    """Append additional instructions to the default system prompt."""

    # ── Structured output ────────────────────────────────────
    extraction_schema: dict | None = None
    """JSON schema for structured data extraction. Passed to the LLM output format."""

    # ── Fallback LLM ─────────────────────────────────────────
    fallback_llm_model: str | None = None
    """Fallback model name on rate limit / provider errors (e.g. 'gpt-4o-mini').
    Uses same API key/base_url as the primary LLM."""

    # ── Recording & debugging ────────────────────────────────
    generate_gif: bool = False
    """Generate animated GIF of the agent session. True = 'agent_history.gif', or specify path."""
    save_conversation_path: str | None = None
    """Save LLM conversation logs to this directory (one file per step)."""

    # ── Cost tracking ────────────────────────────────────────
    calculate_cost: bool = False
    """Track and report token usage/cost in the result."""

    # ── Skills ecosystem ─────────────────────────────────────
    skill_ids: list[str] | None = None
    """browser-use skill IDs to register as additional agent actions (e.g. ['*'] for all)."""

    # ── Security ─────────────────────────────────────────────
    sensitive_data: dict[str, str] | None = None
    """Credentials to inject into agent context with domain-scoping warnings.
    Format: {'domain': 'credential'} or {'domain': {'user': '...', 'pass': '...'}}."""
