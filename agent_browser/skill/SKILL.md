---
name: agent-browser
argument-hint: <task description>
description: >
  Anti-detection browser automation for Claude Code. Create sessions, navigate pages,
  click/fill elements, extract data with 7-layer stealth protection. Supports local
  browser (CloakBrowser), Chrome Extension (natural fingerprints), and remote API mode.
  Trigger on: "帮我访问", "打开浏览器", "扫码登录", "自动化浏览", "网页采集",
    "浏览器操作", "帮我打开网站", "open website", "search for", "browse",
    "scrape", "fill form", "visit url", "help me browse", "automate browser".
  Proactively use when user mentions interacting with websites, collecting data, or
  automating browser tasks.
---

# Agent Browser

> **Execution Environment**: Use `.venv/bin/python3` (never bare `python3`) from the project root.

## Quick Start

Run diagnostics first:

```
python -m agent_browser.skill.scripts.doctor
```

If `skill.yaml` is missing, configure it:

```
python -m agent_browser.skill.scripts.setup --mode local
python -m agent_browser.skill.scripts.setup --mode remote-aio --api-url http://host:8000 --vnc-url http://host:6080
python -m agent_browser.skill.scripts.setup --mode remote-distributed --api-url http://host:8000
```

---

## Atomic Operations

All operations route through `agent_browser.skill.scripts.session`. If `skill.yaml` is absent, each call returns a structured guidance dict -- use `AskUserQuestion` to present mode choices to the user, then run `setup` with their answer.

| Operation | Script call | Returns |
|-----------|-------------|---------|
| Check config | `session.check_config()` | `{"configured": True}` or guidance dict |
| Create session | `await session.create()` | `session_id` string |
| Open page | `await session.open_page(sid, url)` | `None` |
| Snapshot | `await session.snapshot(sid)` | `{url, title, elements: [{ref, text, role}]}` |
| Click element | `await session.click(sid, ref)` | `None` |
| Fill input | `await session.fill(sid, ref, text)` | `None` |
| Scroll page | `await session.scroll(sid, direction, amount)` | `None` |
| Run agent task | `await session.run_task(sid, task, max_steps)` | `{status, result, steps}` |
| Delete session | `await session.delete(sid)` | `None` |

**Element refs**: `@e0`, `@e1`, `@e2` ... from snapshot `elements[].ref`.

---

## ReAct Loop

```
┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
│ Observe  │→  │ Reason   │→  │ Act      │→  │ Check    │
│          │   │          │   │          │   │          │
│ snapshot │   │ Analyze  │   │ Execute  │   │ Verify   │
│ elements │   │ elements │   │ action   │   │ result   │
│ URL/title│   │ Plan next│   │ (click/  │   │ Loop or  │
│          │   │ step     │   │ fill/    │   │ done     │
└──────────┘   └──────────┘   └──────────┘   └──────────┘
     ↑                                              │
     └──────────── retry on failure ←───────────────┘
                    (max 3 retries per action)
```

All scripts handle mode routing transparently -- local, remote-aio, and remote-distributed all use the same call interface.

---

## Human Handoff Points

Stop and ask the user when:
- **Login required** -- "I see a login page. Please log in, then tell me when ready."
- **Captcha detected** -- "There's a captcha. Please solve it, then tell me."
- **Unexpected modal** -- "Something popped up. What should I do?"
- **3 consecutive failures** -- "I'm stuck on [element]. Options: try different approach / skip / show what I see."

---

## Error Recovery

| Error | Cause | Recovery |
|-------|-------|----------|
| `Element @eN not found` | DOM changed, ref expired | Re-snapshot (up to 3x), find by text |
| `CDP not initialized` | Browser not ready | Wait 5-10s, retry |
| `Backend not initialized` | No session created | Call `session.create()` first |
| `ConnectionError: CDP not reachable` | Browser not started | Run `doctor`, start CloakBrowser |
| `check_config()` returns `configured: False` | `skill.yaml` missing | Run `setup` with user-chosen mode |
| `ImportError: cloakbrowser` | `[cloak]` extra not installed | Auto-degrades to layers 6-7 (plain Playwright) |

---

## Reference Docs

- **ReAct workflow details**: `references/react-workflow.md`
- **Error recovery patterns**: `references/error-recovery.md`
- **Complete API reference**: `references/api-reference.md`
- **Adapter/exploration guide**: `references/adapter-guide.md`
