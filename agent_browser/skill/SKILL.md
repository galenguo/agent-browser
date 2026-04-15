---
name: agent-browser
argument-hint: <task description>
description: >
  Anti-detection browser automation. Create sessions, navigate pages,
  click/fill elements, extract data, run Agent tasks.
  Trigger on: "帮我访问", "打开浏览器", "扫码登录", "自动化浏览", "网页采集",
    "浏览器操作", "帮我打开网站", "open website", "search for", "browse",
    "scrape", "fill form", "visit url", "help me browse", "automate browser".
  Proactively use when user mentions interacting with websites, collecting data, or
  automating browser tasks.
---

# Agent Browser

> **CRITICAL RULE — READ THIS FIRST:**
>
> **Never switch execution mode.** Read `sb._intelligence` from config.yaml and use ONLY that mode.
> If `sb._intelligence == "llm"`: you MUST drive every step manually (`snapshot → click/fill → snapshot`).
> Never call `run_task()`. Never pass `intelligence="agent"`.
> If `sb._intelligence == "agent"`: use `run_task()` exclusively, never drive steps manually.
>
> **Never call `screenshot()` in the ReAct loop.** Use `snapshot()` for all observation.
> `screenshot()` is **forbidden unless the user explicitly asks** to see the page ("截图", "截屏", "screenshot", "show me the page", "看看页面", etc).

```python
from agent_browser.skill.scripts.browser_cli import SkillBrowser
```

**Only use `SkillBrowser` methods. Never mix in Playwright, Puppeteer, or other CDP tools.**

---

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/browser_cli.py` | `SkillBrowser` — HTTP client facade for all browser operations |
| `scripts/doctor.py` | Environment diagnostic (`run_diagnosis()`) — checks connectivity, deps, LLM keys |

---

## Configuration

Edit `agent_browser/skill/config.yaml`:

```yaml
service:
  url: "http://your-api-server:8000"
  api_key: "your-api-key"
  timeout: 600
intelligence: "llm"   # "llm" (ReAct step-by-step) or "agent" (autonomous)
```

Config priority: constructor params > `config.yaml` > auto-detect `localhost:8000` > default.

---

## Execution Mode

`sb._intelligence` is auto-loaded from `config.yaml`. The current mode determines your workflow:

| `sb._intelligence` | Your workflow | Forbidden |
|---|---|---|
| `"llm"` | `snapshot → analyze → click/fill → snapshot → repeat` (you drive every step) | `run_task()`, `intelligence="agent"` |
| `"agent"` | `run_task(sid, task)` — submit once, server completes autonomously | Manual ReAct steps |

**Do NOT switch modes.** The config.yaml setting is the user's intentional choice.

**Slow pages**: If a page seems slow to load, use `await asyncio.sleep(N)` (up to 10 seconds) before
re-calling `snapshot()`. Do NOT switch to agent mode because a page is slow.

---

## Quick Start

```python
sb = SkillBrowser()

# Check service is reachable
report = await sb.diagnose()
if not report["ready"]:
    print(report["errors"])

# Session lifecycle
sid = await sb.create_session()
await sb.open_page(sid, "https://example.com")
snap = await sb.snapshot(sid)
# snap = {url, title, elements: [{ref: "@e0", text: "...", role: "link"}, ...]}
await sb.click(sid, "@e3")
await sb.fill(sid, "@e1", "search term")
await sb.press_key(sid, "Enter")
await sb.delete_session(sid)
```

---

## API Reference

### Session

```python
sid = await sb.create_session(user_id="")   # returns session_id str; reuses cached session if alive
await sb.delete_session(sid)
info = await sb.get_session_info(sid)        # includes vnc_url, vnc_token, browser_node
```

Session creation accepts extended profile parameters (passed to API server):

```python
sid = await sb.create_session(
    user_id="",
    # BrowserProfile subset:
    viewport={"width": 1920, "height": 1080},
    proxy={"server": "http://proxy:8080", "username": "user", "password": "pass"},
    user_agent="Mozilla/5.0 ...",
    headless=False,
    allowed_domains=["*.example.com"],
    prohibited_domains=["ads.example.com"],
    enable_extensions=True,
    demo_mode=False,
    device_scale_factor=2.0,
)
```

### Navigation

```python
await sb.open_page(sid, url)
await sb.go_back(sid)
```

### Observation

```python
snap = await sb.snapshot(sid, interactive_only=False)
# → {url, title, elements: [{ref, text, role, type, is_visible, bounding_box}]}

# Penetrate iframes (same-origin only):
snap = await sb.snapshot(sid, iframe_selector="iframe")
# iframe elements have: {ref, ..., bounding_box: {x,y,w,h}, iframe: "frame-name"}
# Note: Use coordinate-based click for iframe elements (see "Working with iframes")
```

### Working with iframes

iframe elements require coordinate-based interaction since ref-based methods (`fill`, `click` by ref) only work in the main frame.

**Pattern:**

```python
# 1. Snapshot with iframe penetration (same-origin only)
snap = await sb.snapshot(sid, iframe_selector="iframe")
# or target specific iframes: iframe_selector="iframe.login-frame"

# 2. Find element inside iframe (has "iframe" field)
for el in snap["elements"]:
    if el.get("iframe") and "Login" in el.get("text", ""):
        bb = el["bounding_box"]
        # 3. Click by viewport-absolute coordinates
        await sb.click(sid, x=bb["x"] + bb["width"]/2, y=bb["y"] + bb["height"]/2)
        break
```

**Limitations:**
- Cross-origin iframes are silently skipped (browser security)
- `fill(sid, ref)` won't work for iframe elements (use coordinate click + `press_key`)
- `evaluate()` runs in main frame only (no `evaluate_in_frame` exists)

**See:** `references/api-reference.md` for complete iframe documentation.

### Interaction

```python
await sb.click(sid, ref="@e3")              # click by element ref (main frame only)
await sb.click(sid, x=150.0, y=300.0)       # click by coordinates (works for iframes too)
await sb.fill(sid, "@e1", "text")           # fill input
await sb.scroll(sid, direction="down", amount=500)
await sb.press_key(sid, "Enter")            # Enter, Tab, Escape, ArrowDown, etc.
await sb.wait_for_selector(sid, ".result", timeout=10000)
```

### Search & Discovery

```python
# Search page text content (regex or plain text)
results = await sb.search_page(sid, pattern="Python", is_regex=False, max_results=10)
# → {matches: [{match_text, context, element_path, char_position}], total: 5, has_more: false}

# Find elements by CSS selector with metadata
elements = await sb.find_elements(sid, selector="a[href]", max_results=20)
# → {elements: [{index, tag, text, id, class_name, bounding_box: {x,y,w,h}, visible}], total: 42}
```

### Dropdown Handling

```python
# Get all options from a <select> element
options = await sb.get_dropdown_options(sid, "@e5")
# → [{index: 0, value: "us", text: "United States", selected: True, disabled: False}, ...]

# Select option by visible text (not value)
await sb.select_dropdown_option(sid, "@e5", "Canada")
```

### File & Media

**Screenshot usage rule**: `screenshot()` transfers base64 image data and is slow.
**Only use it when the user explicitly asks** to see the page ("截图", "截屏", "screenshot",
"show me the page", "看看页面"). For all ReAct loop observation, use `snapshot()`
(DOM-based, lightweight). Do NOT call `screenshot()` in any automated loop.

```python
# Upload files to <input type=file>
await sb.upload_file(sid, "@e10", ["/path/to/file1.pdf", "/path/to/file2.png"])

# Take screenshot (returns base64 image data)
result = await sb.screenshot(sid)                          # full page screenshot
result = await sb.screenshot(sid, ref="@e3")              # element screenshot
result = await sb.screenshot(sid, format="jpeg", quality=85)  # JPEG with quality

# Save page as PDF
pdf_path = await sb.save_as_pdf(sid)                   # auto-generated path
pdf_path = await sb.save_as_pdf(sid, output_path="/tmp/report.pdf", landscape=True)
```

### Advanced Interaction

```python
# Complex key sequences (modifiers + keys)
await sb.send_keys(sid, "Meta+a")           # Select all
await sb.send_keys(sid, "Control+c")        # Copy
await sb.send_keys(sid, "Shift+Home")       # Go to line start
await sb.send_keys(sid, "Tab")             # Tab to next field

# Scroll until text becomes visible
found = await sb.scroll_to_text(sid, "Results")

# Multi-tab management
tabs = await sb.get_tabs_info(sid)          # List all tabs: [{index, url, title}, ...]
idx = await sb.open_tab(sid)               # Open blank tab, returns index
idx = await sb.open_tab(sid, url="https://example.com")  # Open + navigate
await sb.switch_tab(sid, index=1)         # Switch to tab 1
await sb.close_tab(sid)                  # Close last tab
await sb.close_tab(sid, index=0)          # Close specific tab
```

### Data Extraction

```python
# Extract content from page or element
text = await sb.extract_content(sid)                                    # Full page text
html = await sb.extract_content(sid, extract_type="html")               # HTML source
links = await sb.extract_content(sid, extract_type="links")             # All links as JSON
images = await sb.extract_content(sid, extract_type="images")          # All images as JSON
section_text = await sb.extract_content(sid, selector="#content", extract_type="text")
```

### JavaScript

```python
result = await sb.evaluate(sid, "document.title")
result = await sb.evaluate_with_retry(sid, "...", retries=3)
```

### Agent Mode

> **Only relevant when `sb._intelligence == "agent"`.** If your config says `"llm"`, skip this
> section entirely — you must NOT use `run_task()` or any agent features.

When in agent mode, submit tasks and the server-side browser-use Agent handles them autonomously:

```python
result = await sb.run_task(
    sid,
    task="Search for Python jobs and return top 5 titles",
    max_steps=10,
    total_timeout=300.0,
)
# result = {status: "completed"|"failed"|"timeout", result: "...", steps: [...]}
```

For `agent_config` options and detailed usage, see `references/api-reference.md` → **Agent Mode** and **AgentConfig** sections.

### Diagnostics

```python
report = await sb.diagnose()
# report = {ready: bool, checks: [...], errors: [...], warnings: [...]}
```

---

## ReAct Loop (LLM mode)

**Observation rule**: Always use `sb.snapshot()` for observation. It returns structured
DOM data (element refs, text, roles) without image transfer overhead. `screenshot()` is
**forbidden unless the user explicitly asks** to see the page ("截图", "截屏", "screenshot",
"show me the page"). Never call `screenshot()` in automated loops.

**Patience rule**: Pages may load slowly. If `snapshot()` returns few or empty elements,
the page may still be loading. Wait with `await asyncio.sleep(N)` (N up to 10 seconds),
then re-snapshot. Do NOT switch to agent mode because a page is slow — stay in llm mode
and wait.

```
snapshot → analyze elements → act (click/fill/scroll) → snapshot → verify → repeat
```

Common patterns:
- **Navigate + extract**: `open_page → snapshot → evaluate(JS) → delete_session`
- **Search**: `open_page → snapshot → fill(query) → click(submit) → snapshot → extract`
- **Search + extract**: `open_page → search_page("keyword") → find_elements(".result") → extract_content(selector=".result-item")`
- **Upload form**: `open_page → snapshot → upload_file(ref, ["/path/to/file"]) → click(submit)`
- **Multi-tab workflow**: `open_tab(url) → switch_tab(1) → snapshot(tab=1) → close_tab(1)`
- **Data export**: `open_page → extract_content(type="links")` (only use `screenshot()` or `save_as_pdf()` if user explicitly requests visual output)
- **Login (QR)**: `open_page → click(QR tab) → get_session_info → tell user to open vnc_url → wait for confirmation`

---

## Error Handling

```python
from agent_browser.skill.scripts.browser_cli import SkillBrowserError

try:
    await sb.click(sid, "@e99")
except SkillBrowserError as e:
    # e.status_code: 0=connection, 401=auth, 404=session/element, 409=conflict, 503=pool full, 500=server
    print(e.status_code, e.url)
```

Auto-recovery rules:
- Element `@eN` not found → re-`snapshot`, find by text (up to 3×)
- Session 404 → `create_session` again
- 409 on create → reuse existing session (handled automatically by `create_session`)
- 503 pool full → cleans current user's sessions, retries (handled automatically)
- Login / captcha → stop, get `vnc_url` via `get_session_info`, ask user to handle manually

---

## Detailed References

- **API reference**: `references/api-reference.md`
- **ReAct workflow**: `references/react-workflow.md`
- **Error recovery**: `references/error-recovery.md`
- **Adapter guide**: `references/adapter-guide.md`
