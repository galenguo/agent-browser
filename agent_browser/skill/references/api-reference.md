# API Reference -- Complete

## Session Management

### `create_session`

Create a new browser session. Auto-selects optimal mode (Extension > Local > Remote).

```python
session_id = await create_session(
    cdp_url="http://127.0.0.1:19222",  # Optional: override CDP endpoint
    mode="cli",                       # Optional: "cli" | "api"
    api_url="http://localhost:8000",     # Optional: for API mode
)
# Returns: str (UUID session ID)
```

**Modes**: Auto-detected by default. Force with `mode` param or `AGENT_BROWSER_CALLING_MODE` env var.

### `delete_session`

Release browser resources for a session.

```python
await delete_session(session_id)  # str → None
```

## Page Operations

### `open_page`

Navigate to a URL. Triggers stealth pre-delay automatically.

```python
await open_page(session_id, "https://example.com")
# Validates URL, navigates, caches snapshot for subsequent snapshot()
```

### `snapshot`

Get page state with element refs. Core of ReAct loop.

```python
snap = await snapshot(session_id)
# Returns: {
#   "url": "https://...",
#   "title": "Page Title",
#   "elements": [
#     {"ref": "@e0", "text": "button text", "role": "button"},
#     {"ref": "@e1", "text": "input value", "role": "input"},
#   ]
# }
```

**Params**: `interactive_only=False` -- when True, only returns interactive elements (inputs, buttons, links), skips static text.

### `click`

Click an element by ref.

```python
await click(session_id, "@e3")
# Raises: ValueError if @e3 not found (DOM changed since last snapshot)
```

### `fill`

Fill an input element by ref.

```python
await fill(session_id, "@e0", "hello world")
# Sets value + dispatches input event + change event
```

### `scroll`

Scroll the page.

```python
await scroll(session_id, "down", 500)  # direction: "up" | "down", amount in px
```

### `hover`

Move mouse to element center (for revealing dropdowns, tooltips).

```python
await hover(session_id, "@e4")
```

### `select_option`

Select a dropdown option by ref.

```python
await select_option(session_id, "@e6", "option_value")
```

### `press_key`

Press a keyboard key.

```python
await press_key(session_id, "Enter")  # "Tab", "Escape", "ArrowDown", etc.
```

### `go_back`

Browser back navigation.

```python
await go_back(session_id)
```

### `evaluate`

Execute JavaScript in the page context. Return value.

```python
title = await evaluate(session_id, "document.title")
urls = await evaluate(session_id, "Array.from(document.querySelectorAll('a')).map(a => a.href).slice(0, 5)")
```

### `wait_for_selector`

Wait for a CSS selector to appear in the DOM.

```python
await wait_for_selector(session_id, ".search-results", timeout=10000)
# Raises: TimeoutError if not found within timeout
```

## Agent Mode

### `run_task`

Let the built-in Agent execute a complete task autonomously.

```python
result = await run_task(
    session_id,
    task="Search for Python jobs and return top 5 titles",
    intelligence="agent",    # "agent" | "llm"
    max_steps=12,           # Max steps before reporting
    total_timeout=300.0,    # Overall timeout in seconds
)
# Returns: {status, result, steps, chunks, error?}
```

**Intelligence modes**:
- `"agent"` -- Uses browser-use Agent framework. Best for complex multi-step tasks. Requires LLM API key.
- `"llm"` -- Returns tool descriptions so Claude can drive ReAct loop manually. Use this for precise control.

**LLM config** (optional):
```python
result = await run_task(sid, "task", llm_config={
    "provider": "openai",
    "model": "gpt-4o",
    "api_key": "sk-...",
    "base_url": "https://api.openai.com/v1",
})
```

## Setup & Diagnostics

### `configure`

Set configuration before first session.

```python
from agent_browser import configure
configure(mode="api", api_url="http://localhost:8000")
```

### `setup`

Full environment detection + validation. Returns structured report.

```python
result = await setup()
# Returns: {config, issues, report, ready, config_path, environment}
# result["ready"] == True → all good
# result["report"].fixable → auto-fix these
# result["report"].needs_human → user must provide
```

### `detect_missing_deps`

Check environment without modifying anything.

```python
from agent_browser import detect_missing_deps
report = await detect_missing_deps()
# report.ready → bool
# report.missing_deps → list of DepStatus
# report.fixable → subset that can be auto-fixed
# report.needs_human → items requiring user input
```

## Reset

### `reset`

Clean up all sessions and middleware state. Call between independent tasks or to recover from errors.

```python
from agent_browser import reset
reset()  # Disconnects daemon, clears middleware
```
