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

Read `sb._intelligence` (auto-loaded from `config.yaml`) before starting:

- **`llm`** — You drive each step: `snapshot → analyze → click/fill → snapshot → repeat`
- **`agent`** — Submit task once, server Agent completes it autonomously: `run_task(sid, "...")`

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
info = await sb.get_session_info(sid)        # includes browser_node.novnc_url
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
# Elements inside iframes include: {ref, ..., bounding_box: {x,y,w,h}, iframe: "frame-name"}
```

### Interaction

```python
await sb.click(sid, ref="@e3")              # click by element ref
await sb.click(sid, x=150.0, y=300.0)       # click by coordinates
await sb.fill(sid, "@e1", "text")           # fill input
await sb.scroll(sid, direction="down", amount=500)
await sb.press_key(sid, "Enter")            # Enter, Tab, Escape, ArrowDown, etc.
await sb.wait_for_selector(sid, ".result", timeout=10000)
```

### JavaScript

```python
result = await sb.evaluate(sid, "document.title")
result = await sb.evaluate_with_retry(sid, "...", retries=3)
```

### Agent Mode

```python
result = await sb.run_task(
    sid,
    task="Search for Python jobs and return top 5 titles",
    intelligence="agent",   # or "llm"; defaults to config.yaml setting
    max_steps=10,
    total_timeout=300.0,
)
# result = {status: "completed"|"failed"|"timeout", result: "...", steps: [...]}
```

### Diagnostics

```python
report = await sb.diagnose()
# report = {ready: bool, checks: [...], errors: [...], warnings: [...]}
```

---

## ReAct Loop (LLM mode)

```
snapshot → analyze elements → act (click/fill/scroll) → snapshot → verify → repeat
```

Common patterns:
- **Navigate + extract**: `open_page → snapshot → evaluate(JS) → delete_session`
- **Search**: `open_page → snapshot → fill(query) → click(submit) → snapshot → extract`
- **Login (QR)**: `open_page → click(QR tab) → get_session_info → tell user to open novnc_url → wait for confirmation`

---

## Error Handling

```python
from agent_browser.skill.scripts.browser_cli import SkillBrowserError

try:
    await sb.click(sid, "@e99")
except SkillBrowserError as e:
    # e.status_code: 0=connection, 401=auth, 404=session/element, 500=server
    print(e.status_code, e.url)
```

Auto-recovery rules:
- Element `@eN` not found → re-`snapshot`, find by text (up to 3×)
- Session 404 → `create_session` again
- 409 on create → reuse existing session (handled automatically by `create_session`)
- 503 pool full → cleans current user's sessions, retries (handled automatically)
- Login / captcha → stop, get `novnc_url` via `get_session_info`, ask user to handle manually

---

## Detailed References

- **API reference**: `references/api-reference.md`
- **ReAct workflow**: `references/react-workflow.md`
- **Error recovery**: `references/error-recovery.md`
- **Adapter guide**: `references/adapter-guide.md`
