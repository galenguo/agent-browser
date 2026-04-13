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

**Server mode response** (when using `remote-aio` or `remote-distributed`):

In API mode the underlying `POST /sessions/create` returns a JSON object. Access it via `SkillBrowser`:

```python
sb = SkillBrowser()
info = await sb.create_session()
# info["session_id"]  -- session ID string
# info["vnc_url"]     -- VNC proxy URL for this session (distributed: per-session; aio: static)
# info["vnc_token"]   -- token for VNC WebSocket proxy endpoint
```

In `remote-distributed` mode, `vnc_url` is unique per session (each BR pod has its own VNC).
Open `vnc_url` in a browser to watch the live session. Use `sb.get_session_info(sid)` to retrieve
it again after creation.

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
) -> dict[str, Any]
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `session_id` | `str` | | Session ID. |
| `interactive_only` | `bool` | `False` | When `True`, only return interactive elements (inputs, buttons, links); skip static text. |

**Returns:** `dict` with:

| Key | Type | Description |
|-----|------|-------------|
| `url` | `str` | Current page URL. |
| `title` | `str` | Page title. |
| `elements` | `list[dict]` | Each element has `ref` (`"@e0"`), `text`, and `role` (`"button"`, `"input"`, `"link"`, etc.). |

```python
snap = await sb.snapshot(sid)
# {
#   "url": "https://example.com",
#   "title": "Example Domain",
#   "elements": [
#     {"ref": "@e0", "text": "More information...", "role": "link"},
#     {"ref": "@e1", "text": "", "role": "input"},
#   ]
# }

# Only interactive elements
snap = await sb.snapshot(sid, interactive_only=True)
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

### `hover`

Move the mouse over an element center. Useful for revealing dropdowns, tooltips, or hover menus.

```python
async def hover(self, session_id: str, ref: str) -> None
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `str` | Session ID. |
| `ref` | `str` | Element reference (`"@eN"`). |

**Returns:** `None`

```python
await sb.hover(sid, "@e4")
```

### `select_option`

Select an option in a `<select>` element by ref.

```python
async def select_option(self, session_id: str, ref: str, value: str) -> None
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `str` | Session ID. |
| `ref` | `str` | Element reference (`"@eN"`). |
| `value` | `str` | Option value to select. |

**Returns:** `None`

```python
await sb.select_option(sid, "@e6", "option_value")
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

## JavaScript Execution

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
