# API Reference -- SkillBrowser

All methods are async. Use `sb = SkillBrowser()` to create a client, then call methods on it.

```python
sb = SkillBrowser()                        # auto-load config
sid = await sb.create_session()
snap = await sb.snapshot(sid)
await sb.click(sid, "@e3")
result = await sb.run_task(sid, "search AI")
await sb.delete_session(sid)
```

Configuration can be passed explicitly:

```python
sb = SkillBrowser(
    api_url="http://api.agent-browser.local",
    api_key="key-alice-001",
    timeout=120,
)
```

---

## SkillBrowser

```python
class SkillBrowser:
    def __init__(
        self,
        api_url: str | None = None,
        api_key: str | None = None,
        timeout: int | None = None,
    )
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `api_url` | `str \| None` | `"http://localhost:8000"` | API server endpoint. Falls back to `skill/config.yaml` `service.url`, then auto-detect, then default. |
| `api_key` | `str \| None` | `""` | X-API-Key header for authentication. Falls back to `skill/config.yaml` `service.api_key`. |
| `timeout` | `int \| None` | `120` | HTTP request timeout in seconds. Falls back to `skill/config.yaml` `service.timeout`. |

**Configuration priority:** constructor params > `skill/config.yaml` > auto-detect (`localhost:8000/health`) > defaults.

Supports async context manager:

```python
async with SkillBrowser() as sb:
    sid = await sb.create_session()
    # ... use sb ...
    await sb.delete_session(sid)
```

---

## Diagnostics

### `diagnose`

Check environment and API service availability. Returns a structured report.

```python
async def diagnose(self) -> dict[str, Any]
```

**Returns:** `dict` with the following keys:

| Key | Type | Description |
|-----|------|-------------|
| `ready` | `bool` | `True` if all critical checks pass |
| `checks` | `list[dict]` | Each check has `name`, `status` (`"pass"`/`"warn"`/`"fail"`), and `message` |
| `api_url` | `str` | The configured API endpoint |
| `warnings` | `list[str]` | Non-blocking issues |
| `errors` | `list[str]` | Blocking issues |

**Checks performed:**
1. `api_service` -- API server reachable at `api_url`
2. `api_auth` -- API key configured
3. `llm_api_key` -- LLM API key available (for Agent mode)

```python
sb = SkillBrowser()
report = await sb.diagnose()
if report["ready"]:
    print("All systems go")
else:
    for err in report["errors"]:
        print(f"ERROR: {err}")
    for warn in report["warnings"]:
        print(f"WARNING: {warn}")
```

---

## Session Management

### `create_session`

Create a new browser session on the API server.

```python
async def create_session(self, user_id: str = "") -> str
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `user_id` | `str` | `""` | Optional user identifier for session isolation. |

**Returns:** `str` -- the session ID (UUID).

```python
sb = SkillBrowser()
sid = await sb.create_session()
# sid = "a1b2c3d4-..."

sid = await sb.create_session(user_id="alice")
# Session scoped to user "alice"
```

**VNC URL**: After creating a session, call `sb.get_session_info(sid)` to retrieve the `vnc_url` for live browser monitoring:

```python
sb = SkillBrowser()
sid = await sb.create_session()
info = await sb.get_session_info(sid)
# info["vnc_url"]   -- VNC proxy URL (per-session in distributed mode)
# info["vnc_token"] -- token for VNC WebSocket proxy endpoint
```

In distributed mode, `vnc_url` is unique per session. Open it in a browser to watch the live session.

### `delete_session`

Release browser resources for a session. Safe to call on already-deleted sessions (404 is silently handled).

```python
async def delete_session(self, session_id: str) -> None
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `str` | Session ID to delete. |

**Returns:** `None`

```python
await sb.delete_session(sid)
```

---

## Navigation

### `open_page`

Navigate the browser to a URL. Triggers stealth pre-delay automatically.

```python
async def open_page(self, session_id: str, url: str) -> None
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `str` | Session ID. |
| `url` | `str` | Target URL. |

**Returns:** `None`

```python
await sb.open_page(sid, "https://example.com")
```

### `go_back`

Navigate back in browser history.

```python
async def go_back(self, session_id: str) -> None
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `str` | Session ID. |

**Returns:** `None`

```python
await sb.go_back(sid)
```

---

## Observation

### `snapshot`

Get page state with `@eN` element references. Core of the ReAct loop.

```python
async def snapshot(
    self,
    session_id: str,
    interactive_only: bool = False,
    iframe_selector: str | None = None,
) -> dict[str, Any]
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `session_id` | `str` | | Session ID. |
| `interactive_only` | `bool` | `False` | When `True`, only return interactive elements (inputs, buttons, links); skip static text. |
| `iframe_selector` | `str \| None` | `None` | CSS selector for iframes to penetrate (e.g. `"iframe"`, `"#my-frame"`). Elements inside matching iframes are included with viewport-absolute `bounding_box` and an `iframe` field. Cross-origin iframes are silently skipped. |

**Returns:** `dict` with:

| Key | Type | Description |
|-----|------|-------------|
| `url` | `str` | Current page URL. |
| `title` | `str` | Page title. |
| `elements` | `list[dict]` | Each element has `ref` (`"@e0"`), `text`, `role`, `bounding_box`, and optionally `iframe` (frame name/id when element is inside an iframe). |

```python
snap = await sb.snapshot(sid)
# {
#   "url": "https://example.com",
#   "title": "Example Domain",
#   "elements": [
#     {"ref": "@e0", "text": "More information...", "role": "link", "bounding_box": {...}},
#   ]
# }

# Only interactive elements
snap = await sb.snapshot(sid, interactive_only=True)

# Penetrate iframes (same-origin only)
snap = await sb.snapshot(sid, iframe_selector="iframe")
# iframe elements include: {"ref": "@e5", ..., "bounding_box": {"x": 120, "y": 300, "width": 80, "height": 30}, "iframe": "login-frame"}
# Click by coordinates (works for both main-frame and iframe elements):
el = snap["elements"][5]
bb = el["bounding_box"]
await sb.click(sid, x=bb["x"] + bb["width"] / 2, y=bb["y"] + bb["height"] / 2)
```

---

## Interaction

### `click`

Click an element by `@eN` ref or viewport coordinates.

```python
async def click(
    self,
    session_id: str,
    ref: str | None = None,
    x: float | None = None,
    y: float | None = None,
) -> None
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `session_id` | `str` | | Session ID. |
| `ref` | `str \| None` | `None` | Element reference string (`"@eN"`). |
| `x` | `float \| None` | `None` | Viewport X coordinate (alternative to `ref`). |
| `y` | `float \| None` | `None` | Viewport Y coordinate (alternative to `ref`). |

You must provide either `ref` or both `x` and `y`. Raises `ValueError` if neither is provided.

**Returns:** `None`

```python
await sb.click(sid, "@e3")

# Click by coordinates
await sb.click(sid, x=150.0, y=300.0)
```

### `fill`

Fill an input element with text (types character-by-character with human-like timing).

```python
async def fill(self, session_id: str, ref: str, text: str) -> None
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `str` | Session ID. |
| `ref` | `str` | Element reference (`"@eN"`). |
| `text` | `str` | Text to type into the element. |

**Returns:** `None`

```python
await sb.fill(sid, "@e0", "hello world")
```

### `scroll`

Scroll the page.

```python
async def scroll(
    self,
    session_id: str,
    direction: str = "down",
    amount: int = 500,
) -> None
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `session_id` | `str` | | Session ID. |
| `direction` | `str` | `"down"` | `"down"` or `"up"`. |
| `amount` | `int` | `500` | Pixels to scroll. |

**Returns:** `None`

```python
await sb.scroll(sid, "down", 500)
await sb.scroll(sid, "up", 300)
```

### `press_key`

Press a keyboard key.

```python
async def press_key(self, session_id: str, key: str) -> None
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `str` | Session ID. |
| `key` | `str` | Key name: `"Enter"`, `"Tab"`, `"Escape"`, `"ArrowDown"`, etc. |

**Returns:** `None`

```python
await sb.press_key(sid, "Enter")
await sb.press_key(sid, "Tab")
```

### `wait_for_selector`

Wait for a CSS selector to appear in the DOM.

```python
async def wait_for_selector(
    self,
    session_id: str,
    selector: str,
    timeout: int = 10000,
) -> None
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `session_id` | `str` | | Session ID. |
| `selector` | `str` | | CSS selector string. |
| `timeout` | `int` | `10000` | Maximum wait time in milliseconds. |

**Returns:** `None`

```python
await sb.wait_for_selector(sid, ".search-results", timeout=10000)
```

---

## Search & Discovery

### `search_page`

Search page text content using regex or plain text. Returns matches with context and element path.

```python
async def search_page(
    self,
    session_id: str,
    pattern: str,
    case_sensitive: bool = False,
    is_regex: bool = False,
    max_results: int = 10,
    context_chars: int = 100,
    css_scope: str | None = None,
) -> dict
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `session_id` | `str` | | Session ID. |
| `pattern` | `str` | | Search pattern (regex or plain text). |
| `case_sensitive` | `bool` | `False` | Case-sensitive search. |
| `is_regex` | `bool` | `False` | Treat pattern as regex. |
| `max_results` | `int` | `10` | Max matches to return. |
| `context_chars` | `int` | `100` | Context characters around each match. |
| `css_scope` | `str \| None` | `None` | Limit search to this CSS subtree. |

**Returns:** `dict` with `matches` list and `total` count.

```python
results = await sb.search_page(sid, "Python")
# {"matches": [{match_text: "Python", context: "...Python...", element_path: "div > p", char_position: 42}], "total": 5}

# Regex search
results = await sb.search_page(sid, r"\\d{4}-\\d{2}-\\d{2}", is_regex=True)

# Scoped search
results = await sb.search_page(sid, "login", css_scope="#main-content")
```

### `find_elements`

Find elements matching a CSS selector with metadata (tag, text, bounding box, visibility).

```python
async def find_elements(
    self,
    session_id: str,
    selector: str,
    max_results: int = 50,
) -> dict
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `session_id` | `str` | | Session ID. |
| `selector` | `str` | | CSS selector string. |
| `max_results` | `int` | `50` | Max elements to return. |

**Returns:** `dict` with `elements` list and `total` count.

```python
result = await sb.find_elements(sid, "a[href]")
# {"elements": [{index: 0, tag: "a", text: "Click here", id: "", class_name: "btn",
#   bounding_box: {x: 10, y: 20, w: 100, h: 30}, visible: True}], "total": 42}
```

---

## Dropdown Handling

### `get_dropdown_options`

Get all options from a `<select>` element.

```python
async def get_dropdown_options(self, session_id: str, ref: str) -> list[dict]
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `str` | Session ID. |
| `ref` | `str` | Element reference (`"@eN"`). |

**Returns:** `list[dict]` with `{index, value, text, selected, disabled}` per option.

```python
options = await sb.get_dropdown_options(sid, "@e5")
# [{index: 0, value: "us", text: "United States", selected: True, disabled: False}, ...]
for opt in options:
    print(f"{opt['text']} (value={opt['value']})")
```

### `select_dropdown_option`

Select a dropdown option by visible text (not value).

```python
async def select_dropdown_option(self, session_id: str, ref: str, option_text: str) -> None
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `str` | Session ID. |
| `ref` | `str` | Element reference (`"@eN"`). |
| `option_text` | `str` | Visible text of the option to select. |

```python
await sb.select_dropdown_option(sid, "@e5", "Canada")
```

---

## File & Media

### `upload_file`

Upload files to an `<input type=file>` element.

```python
async def upload_file(self, session_id: str, ref: str, file_paths: list[str]) -> None
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `str` | Session ID. |
| `ref` | `str` | Element reference (`"@eN"`). |
| `file_paths` | `list[str]` | Absolute file paths to upload. |

```python
await sb.upload_file(sid, "@e10", ["/path/to/resume.pdf", "/path/to/photo.png"])
```

### `screenshot`

Take a screenshot of the page or specific element. Returns base64-encoded image data.

```python
async def screenshot(
    self,
    session_id: str,
    ref: str | None = None,
    full_page: bool = True,
    format: str = "png",
) -> dict
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `session_id` | `str` | | Session ID. |
| `ref` | `str \| None` | `None` | Element reference for element screenshot. `None` = full page. |
| `full_page` | `bool` | `True` | Capture full scrollable page. |
| `format` | `str` | `"png"` | `"png"` or `"jpeg"`. |

**Returns:** `dict` with `image` (base64), `format`, and `size`.

```python
result = await sb.screenshot(sid)
# {"image": "iVBORw0KGgoAAAANSUhEUg...", "format": "png", "size": 123456}

# Element screenshot
result = await sb.screenshot(sid, ref="@e3")

# JPEG with quality
result = await sb.screenshot(sid, format="jpeg", quality=85)
```

### `save_as_pdf`

Save current page as PDF. Returns file path.

```python
async def save_as_pdf(
    self,
    session_id: str,
    output_path: str | None = None,
    landscape: bool = False,
) -> dict
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `session_id` | `str` | | Session ID. |
| `output_path` | `str \| None` | `None` | Output file path (auto-generated if `None`). |
| `landscape` | `bool` | `False` | Landscape orientation. |

**Returns:** `dict` with `path` to saved PDF.

```python
pdf_path = await sb.save_as_pdf(sid)
pdf_path = await sb.save_as_pdf(sid, output_path="/tmp/report.pdf", landscape=True)
```

---

## Advanced Interaction

### `send_keys`

Send complex key sequences with modifier keys.

```python
async def send_keys(self, session_id: str, keys: str) -> None
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `str` | Session ID. |
| `keys` | `str` | Key sequence with modifiers (`"Meta+a"`, `"Shift+Home"`, `"Control+c"`). |

```python
await sb.send_keys(sid, "Meta+a")        # Select all
await sb.send_keys(sid, "Control+c")     # Copy
await sb.send_keys(sid, "Shift+End")      # Select to end of line
await sb.send_keys(sid, "Tab")            # Tab to next field
```

### `scroll_to_text`

Scroll the page until text becomes visible.

```python
async def scroll_to_text(self, session_id: str, text: str, max_scrolls: int = 10) -> bool
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `session_id` | `str` | | Session ID. |
| `text` | `str` | | Text to find. |
| `max_scrolls` | `int` | `10` | Max scroll attempts. |

**Returns:** `bool` -- `True` if text was found and made visible.

```python
found = await sb.scroll_to_text(sid, "Results found")
if not found:
    print("Text not found on page")
```

---

## Tab Management

### `get_tabs_info`

Get info about all open tabs in the session.

```python
async def get_tabs_info(self, session_id: str) -> list[dict]
```

**Returns:** `list[dict]` with `{index, url, title}` per tab.

```python
tabs = await sb.get_tabs_info(sid)
# [{index: 0, url: "https://example.com", title: "Example"}, ...]
```

### `open_tab`

Open a new tab. Optionally navigate to URL.

```python
async def open_tab(self, session_id: str, url: str | None = None) -> int
```

**Returns:** `int` -- index of the new tab.

```python
idx = await sb.open_tab(sid)                    # Blank tab
idx = await sb.open_tab(sid, url="https://example.com")  # Open + navigate
```

### `switch_tab`

Switch to a tab by index.

```python
async def switch_tab(self, session_id: str, index: int) -> None
```

```python
await sb.switch_tab(sid, index=1)  # Switch to second tab
```

### `close_tab`

Close a tab. Closes last tab if no index given.

```python
async def close_tab(self, session_id: str, index: int | None = None) -> None
```

```python
await sb.close_tab(sid)           # Close last tab
await sb.close_tab(sid, index=0)    # Close first tab
```

---

## Data Extraction

### `extract_content`

Extract content from the page or a specific element.

```python
async def extract_content(
    self,
    session_id: str,
    selector: str | None = None,
    extract_type: str = "text",
) -> str
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `session_id` | `str` | | Session ID. |
| `selector` | `str \| None` | `None` | CSS scope (None = entire page). |
| `extract_type` | `str` | `"text"` | `"text"`, `"html"`, `"links"`, `"images"`. |

**Returns:** `str` -- extracted content.

```python
# Full page text
text = await sb.extract_content(sid)

# HTML source
html = await sb.extract_content(sid, extract_type="html")

# All links as JSON
links_json = await sb.extract_content(sid, extract_type="links")

# All images as JSON
images_json = await sb.extract_content(sid, extract_type="images")

# Section-specific extraction
section = await sb.extract_content(sid, selector="#content", extract_type="text")
```

---

### `evaluate`

Execute JavaScript in the page context and return the result.

```python
async def evaluate(self, session_id: str, expression: str) -> Any
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `str` | Session ID. |
| `expression` | `str` | JavaScript expression to evaluate. |

**Returns:** `Any` -- the evaluation result, or `None` if the response has no result field.

```python
title = await sb.evaluate(sid, "document.title")

urls = await sb.evaluate(
    sid,
    "Array.from(document.querySelectorAll('a')).map(a => a.href).slice(0, 5)"
)
```

---

## Agent Mode

### `run_task`

Submit an Agent task and poll for completion. The task runs server-side using either the browser-use Agent framework or LLM-driven ReAct loop.

```python
async def run_task(
    self,
    session_id: str,
    task: str,
    intelligence: str | None = None,
    max_steps: int = 6,
    total_timeout: float = 300.0,
    poll_interval: float = 5.0,
) -> dict[str, Any]
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `session_id` | `str` | | Session ID. |
| `task` | `str` | | Natural language description of what to do. |
| `intelligence` | `str \| None` | `None` | `"agent"` or `"llm"`. When `None`, uses the `intelligence` field from `config.yaml`, falling back to `"llm"`. |
| `max_steps` | `int` | `6` | Maximum agent steps per chunk. |
| `total_timeout` | `float` | `300.0` | Max wall-clock seconds to wait for completion. |
| `poll_interval` | `float` | `5.0` | Seconds between status polls. |

**Returns:** `dict` with:

| Key | Type | Description |
|-----|------|-------------|
| `status` | `str` | `"completed"`, `"failed"`, `"stuck"`, `"timeout"`, or `"running"`. |
| `result` | `Any` | Task result on success. |
| `steps` | `list` | Steps taken by the agent. |
| `task_id` | `str` | Server-side task identifier. |
| `error` | `str` | Error message on failure (if present). |

**Intelligence modes:**
- `"agent"` -- Uses browser-use Agent framework. Best for complex multi-step tasks. Requires an LLM API key (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, or `GLM_API_KEY`).
- `"llm"` -- Returns tool descriptions for Claude to drive a ReAct loop manually. Use this for precise control over each step.

```python
# Agent mode (uses config.yaml intelligence setting)
result = await sb.run_task(
    sid,
    task="Search for Python jobs and return top 5 titles",
)
# result = {"status": "completed", "result": "...", "steps": [...]}

# Explicit agent mode
result = await sb.run_task(
    sid,
    task="Fill out the contact form",
    intelligence="agent",
    max_steps=12,
    total_timeout=300.0,
)

# LLM mode with custom polling
result = await sb.run_task(
    sid,
    task="Click the third search result",
    intelligence="llm",
    poll_interval=2.0,
)
```

---

## Properties

### `api_url`

The configured API endpoint URL.

```python
@property
def api_url(self) -> str
```

```python
sb = SkillBrowser()
print(sb.api_url)
# "http://localhost:8000"
```

---

## Error Handling

All methods raise `SkillBrowserError` on failure.

```python
class SkillBrowserError(Exception):
    message: str
    status_code: int    # HTTP status code (0 for connection errors)
    url: str            # Request URL that failed
```

```python
try:
    await sb.click(sid, "@e99")
except SkillBrowserError as e:
    print(f"Failed: {e}")
    print(f"Status: {e.status_code}")
    print(f"URL: {e.url}")
    print(e.to_dict())
    # {"error": "API error 404: ...", "status_code": 404, "url": "..."}
```

Common error scenarios:
- `status_code=0` -- Cannot connect to API server. Check that the service is running and `api_url` is correct.
- `status_code=401` -- API key required but not configured.
- `status_code=404` -- Session not found (may have expired or been deleted).
- `status_code=500` -- Server-side error during browser operation.

---

## Cleanup

### `close`

Close the underlying HTTP session. Called automatically when used as an async context manager.

```python
async def close(self) -> None
```

```python
sb = SkillBrowser()
try:
    sid = await sb.create_session()
    # ... work ...
finally:
    await sb.close()
```
