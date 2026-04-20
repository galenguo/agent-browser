---
name: stealth-browser
argument-hint: <task description>
description: >
  Anti-detection browser automation via bash CLI commands.
  Use for website navigation, data extraction, form filling, and agent tasks.
  Trigger on: "帮我访问", "打开浏览器", "扫码登录", "自动化浏览", "网页采集",
    "open website", "browse", "scrape", "fill form", "visit url".
---

# Stealth Browser

> **CRITICAL RULE — NEVER write Python scripts.**
>
> All browser operations MUST be executed via bash commands only.
> Never import `SkillBrowser`. Never write `import` statements.
> Use ONLY the `stealth-browser` CLI commands below.
>
> **NEVER call `screenshot` automatically.** Screenshot is STRICTLY FORBIDDEN in automation
> workflows, observation loops, or verification steps. It is ONLY permitted when the user
> explicitly requests visual output (e.g., "show me a screenshot", "take a picture").
> For ALL observation and element discovery, use `snapshot` instead — always.

## Quick Start

```bash
stealth-browser session create --name default

# Navigate and ALWAYS wait for page load before any action
stealth-browser open https://example.com --session default
stealth-browser wait "body" --timeout 3000 --session default
stealth-browser snapshot --session default -i

# Interact, then pause briefly before next action
stealth-browser click @e3 --session default
sleep 1
stealth-browser fill @e1 "search term" --session default
stealth-browser press Enter --session default
sleep 2

# Confirm result
stealth-browser wait "body" --timeout 3000 --session default
stealth-browser snapshot --session default -i
```

## Core Workflow (LLM mode)

Use the ReAct loop with lightweight snapshots. **Always wait after navigation.**

```bash
open → wait → snapshot → analyze → click/fill → sleep → wait → snapshot → verify → repeat
```

**IMPORTANT**: Never use `screenshot` in this workflow. Use `snapshot` for all observation steps.
Screenshot is only for user-requested visual output, not for automation.

Example:

```bash
stealth-browser open https://example.com --session default
stealth-browser wait "body" --timeout 3000 --session default
stealth-browser snapshot --session default -i
# pick ref @e2 from snapshot output
stealth-browser click @e2 --session default
sleep 1
stealth-browser wait "body" --timeout 3000 --session default
stealth-browser snapshot --session default -i
```

## Key Commands

### Session Management

```bash
stealth-browser session create --name <name>
# Returns: {"success": true, "data": {"name": "...", "session_id": "...", "vnc_url": "..."}}
# vnc_url is cached locally — retrieve anytime with: stealth-browser vnc --session <name>
stealth-browser session list
stealth-browser session destroy <name>
```

When login or CAPTCHA is required, the `open` and `snapshot` commands automatically detect it and return an `intervention` field. Follow the HUMAN INTERVENTION protocol below when it appears. You can also manually retrieve the VNC URL at any time:
```bash
stealth-browser vnc --session <name>
```

### Navigation

```bash
stealth-browser open <url> --session <name>
stealth-browser back --session <name>
stealth-browser url --session <name>
stealth-browser title --session <name>
```

**CRITICAL: Always confirm page load after `open` or `back`:**

```bash
# ✅ Correct
stealth-browser open <url> --session <name>
stealth-browser wait "body" --timeout 3000 --session <name>
stealth-browser snapshot --session <name> -i

# ❌ Wrong — page may not be loaded, eval/extract returns empty data
stealth-browser open <url> --session <name>
stealth-browser eval "..." --session <name>
```

**After navigation, verify you reached the intended page:**

```bash
stealth-browser title --session <name>   # Check for "安全限制", "Access Denied", login page titles
stealth-browser url --session <name>     # Check for unexpected redirects to /login, /captcha, /verify
```

The `open` command automatically detects login, CAPTCHA, and anti-bot pages and returns an `intervention` field when detected. When `intervention` appears in the output, you MUST follow the HUMAN INTERVENTION protocol below.

To manually check the current page state at any time:

```bash
stealth-browser check --session <name>
# Returns: {"url": "...", "title": "...", "intervention": {...}|null, "vnc_url": "..."}
```

To get the VNC URL at any time:

```bash
stealth-browser vnc --session <name>
# Returns: {"vnc_url": "https://..."}
```

### Observation

```bash
stealth-browser snapshot --session <name> -i
# -i returns interactive elements only
stealth-browser snapshot --session <name> -i --iframe "#frame-selector"
# --iframe penetrates into a specific iframe
```

### Interaction

```bash
stealth-browser click <ref> --session <name>
stealth-browser fill <ref> <text> --session <name>
stealth-browser scroll down --amount 500 --session <name>
stealth-browser press Enter --session <name>
stealth-browser mouse 100,200 --session <name>
stealth-browser keys "Control+c" --session <name>
```

### Waiting & Element Discovery

```bash
stealth-browser wait "#selector" --timeout 5000 --session <name>
stealth-browser find "#selector" --max 20 --session <name>
```

### Dropdown & File Upload

```bash
stealth-browser dropdown options @e3 --session <name>
stealth-browser dropdown select @e3 "Option 1" --session <name>
stealth-browser upload @e5 /path/to/file.pdf --session <name>
```

### Tab Management

```bash
stealth-browser tab list --session <name>
stealth-browser tab open https://example.com --session <name>
stealth-browser tab switch 1 --session <name>
stealth-browser tab close 1 --session <name>
```

### JavaScript Evaluation

Use `eval` ONLY for custom JavaScript logic — not for data extraction.
`eval` is a pass-through operation with no stealth delays; overusing it increases detection risk.

```bash
stealth-browser eval "document.title" --session <name>
stealth-browser eval "window.location.href" --session <name>
```

For data extraction, always prefer `extract` over `eval` (see Content Extraction below).

### Content Extraction

**Prefer `extract` over `eval` for data extraction** — it's more stable and handles page load timing internally.

```bash
stealth-browser extract --type text --session <name>
stealth-browser extract --type html --session <name>
stealth-browser extract --type links --session <name>
stealth-browser extract --selector "#content" --type text --session <name>
```

```bash
# ✅ Correct: Use extract for data
stealth-browser extract --selector ".post-title" --type text --session <name>

# ❌ Wrong: eval bypasses stealth delays and is less stable
stealth-browser eval "document.querySelector('.post-title').textContent" --session <name>
```

### Screenshot & PDF

> **CRITICAL: Screenshot is FORBIDDEN in automation workflows.**
>
> - Screenshot is ONLY for user-requested visual output (e.g., "show me a screenshot", "take a picture")
> - NEVER use screenshot for observation, element discovery, or verification
> - For all automation tasks, use `snapshot` instead — it's faster and designed for LLM consumption

```bash
stealth-browser screenshot --session <name>
stealth-browser screenshot --full-page --session <name>
stealth-browser pdf --output /tmp/page.pdf --session <name>
stealth-browser pdf --landscape --session <name>
```

### Agent Mode

Use only when configured for autonomous execution:

```bash
stealth-browser run "search Python jobs and return top 5 titles" --session <name> --max-steps 10
```

### Daemon Management

```bash
stealth-browser daemon status
stealth-browser daemon stop
```

## Output Format

All commands return JSON:

```json
{"success": true, "data": {...}}
{"success": false, "error": "..."}
```

## HUMAN INTERVENTION (MANDATORY)

> **This protocol is MANDATORY. You MUST NOT skip or ignore it.**

When `open`, `snapshot`, or `check` returns an `intervention` field in the output, you MUST:

1. **STOP** all automation immediately — do NOT attempt any further actions
2. **Print** the VNC URL from the output to the user
3. **Tell the user**: "Human intervention required: `{intervention.reason}`. Please complete at: `{vnc_url}`"
4. **WAIT** for user confirmation before continuing automation
5. **NEVER retry** the same action without user guidance

Example output that triggers this protocol:
```json
{"success": true, "data": {
  "url": "https://example.com/login",
  "title": "请登录",
  "intervention": {"type": "login", "reason": "Login page detected -- user authentication required"},
  "vnc_url": "https://stealth-browser-vnc.example.com/vnc/abc123/vnc.html?autoconnect=1"
}}
```

If no VNC URL is in the output, retrieve it:
```bash
stealth-browser vnc --session <name>
```

You do NOT need to manually check title/url patterns — the `intervention` field is generated automatically by the server. However, if you suspect the automatic detection missed something, you can manually check:
```bash
stealth-browser check --session <name>
```

## Error Recovery

- Session not found: run `stealth-browser session create --name <name>`
- Element ref not found: call `snapshot` again and re-locate the element by text
- **Login/captcha required**: Follow the HUMAN INTERVENTION protocol above — stop, surface VNC URL, wait for confirmation
- **Anti-bot / security page detected**: Follow the HUMAN INTERVENTION protocol — do NOT retry the same URL without user guidance
- **Empty data from `eval`**: page not fully loaded — use `wait "body"` before extracting, or switch to `extract`
- API unreachable: check `stealth_browser/skill/config.yaml` service.url and network access

## Anti-Detection Rules

1. **Always `wait` after `open`** — never operate on a page before confirming it loaded
2. **Throttle batch operations** — add `sleep 2` between consecutive page navigations
3. **Prefer `extract` over `eval`** for data extraction — `eval` bypasses stealth delays
4. **Verify page state after navigation** — `open` auto-detects intervention; follow HUMAN INTERVENTION protocol when `intervention` field appears
5. **Pause after interactions** — `sleep 1` after `click`/`fill`/`press` before next action
6. **Reuse named sessions** — avoid creating new sessions repeatedly
7. **Avoid screenshots** unless explicitly requested by user

**Recommended delays:**
- After `open`: `wait "body" --timeout 3000` (mandatory)
- Between batch page visits: `sleep 2` minimum
- After form submit / `press Enter`: `sleep 2`
- After login: `sleep 5`
- After `click`: `sleep 1`

## Installation Notes

Run once to install the skill and create the CLI shim:

```bash
stealth-browser install-skill
```

### macOS / Linux

Shim is created at `~/.local/bin/stealth-browser`.

If `stealth-browser` command is not found, add to PATH:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Add that line to `~/.bashrc`, `~/.zshrc`, or equivalent to persist across sessions.

### Windows

Shim is created at `%APPDATA%\Python\Scripts\stealth-browser.bat`.

If `stealth-browser` command is not found, add to PATH via PowerShell (run once as admin):

```powershell
$scripts = "$env:APPDATA\Python\Scripts"
[Environment]::SetEnvironmentVariable("PATH", "$env:PATH;$scripts", "User")
```

Or add `%APPDATA%\Python\Scripts` manually via System Properties → Environment Variables.

### Daemon Auto-Start

The daemon starts automatically on first command and stops after 30 minutes of inactivity.
No manual daemon management is needed during normal use.
