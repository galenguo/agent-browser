---
name: agent-browser
argument-hint: <task description>
description: >
  Anti-detection browser automation via bash CLI commands.
  Use for website navigation, data extraction, form filling, and agent tasks.
  Trigger on: "帮我访问", "打开浏览器", "扫码登录", "自动化浏览", "网页采集",
    "open website", "browse", "scrape", "fill form", "visit url".
---

# Agent Browser

> **CRITICAL RULE — NEVER write Python scripts.**
>
> All browser operations MUST be executed via bash commands only.
> Never import `SkillBrowser`. Never write `import` statements.
> Use ONLY the `agent-browser` CLI commands below.
>
> **NEVER call `screenshot` automatically.** Screenshot is STRICTLY FORBIDDEN in automation
> workflows, observation loops, or verification steps. It is ONLY permitted when the user
> explicitly requests visual output (e.g., "show me a screenshot", "take a picture").
> For ALL observation and element discovery, use `snapshot` instead — always.

## Quick Start

```bash
agent-browser session create --name default

# Navigate and ALWAYS wait for page load before any action
agent-browser open https://example.com --session default
agent-browser wait "body" --timeout 3000 --session default
agent-browser snapshot --session default -i

# Interact, then pause briefly before next action
agent-browser click @e3 --session default
sleep 1
agent-browser fill @e1 "search term" --session default
agent-browser press Enter --session default
sleep 2

# Confirm result
agent-browser wait "body" --timeout 3000 --session default
agent-browser snapshot --session default -i
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
agent-browser open https://example.com --session default
agent-browser wait "body" --timeout 3000 --session default
agent-browser snapshot --session default -i
# pick ref @e2 from snapshot output
agent-browser click @e2 --session default
sleep 1
agent-browser wait "body" --timeout 3000 --session default
agent-browser snapshot --session default -i
```

## Key Commands

### Session Management

```bash
agent-browser session create --name <name>
# Returns: {"success": true, "data": {"name": "...", "session_id": "...", "vnc_url": "..."}}
# vnc_url is present when available for manual login/verification
agent-browser session list
agent-browser session destroy <name>
```

When login or CAPTCHA is required:
1. Read `vnc_url` from session creation output
2. Provide it to user: "Please complete login at: <vnc_url>"
3. Wait for user confirmation before continuing automation

### Navigation

```bash
agent-browser open <url> --session <name>
agent-browser back --session <name>
agent-browser url --session <name>
agent-browser title --session <name>
```

**CRITICAL: Always confirm page load after `open` or `back`:**

```bash
# ✅ Correct
agent-browser open <url> --session <name>
agent-browser wait "body" --timeout 3000 --session <name>
agent-browser snapshot --session <name> -i

# ❌ Wrong — page may not be loaded, eval/extract returns empty data
agent-browser open <url> --session <name>
agent-browser eval "..." --session <name>
```

**After navigation, verify you reached the intended page:**

```bash
agent-browser title --session <name>   # Check for "安全限制", "Access Denied", login page titles
agent-browser url --session <name>     # Check for unexpected redirects to /login, /captcha, /verify
```

If an anti-bot or login page is detected: stop immediately, report to user with VNC URL, wait for confirmation.

### Observation

```bash
agent-browser snapshot --session <name> -i
# -i returns interactive elements only
agent-browser snapshot --session <name> -i --iframe "#frame-selector"
# --iframe penetrates into a specific iframe
```

### Interaction

```bash
agent-browser click <ref> --session <name>
agent-browser fill <ref> <text> --session <name>
agent-browser scroll down --amount 500 --session <name>
agent-browser press Enter --session <name>
agent-browser mouse 100,200 --session <name>
agent-browser keys "Control+c" --session <name>
```

### Waiting & Element Discovery

```bash
agent-browser wait "#selector" --timeout 5000 --session <name>
agent-browser find "#selector" --max 20 --session <name>
```

### Dropdown & File Upload

```bash
agent-browser dropdown options @e3 --session <name>
agent-browser dropdown select @e3 "Option 1" --session <name>
agent-browser upload @e5 /path/to/file.pdf --session <name>
```

### Tab Management

```bash
agent-browser tab list --session <name>
agent-browser tab open https://example.com --session <name>
agent-browser tab switch 1 --session <name>
agent-browser tab close 1 --session <name>
```

### JavaScript Evaluation

Use `eval` ONLY for custom JavaScript logic — not for data extraction.
`eval` is a pass-through operation with no stealth delays; overusing it increases detection risk.

```bash
agent-browser eval "document.title" --session <name>
agent-browser eval "window.location.href" --session <name>
```

For data extraction, always prefer `extract` over `eval` (see Content Extraction below).

### Content Extraction

**Prefer `extract` over `eval` for data extraction** — it's more stable and handles page load timing internally.

```bash
agent-browser extract --type text --session <name>
agent-browser extract --type html --session <name>
agent-browser extract --type links --session <name>
agent-browser extract --selector "#content" --type text --session <name>
```

```bash
# ✅ Correct: Use extract for data
agent-browser extract --selector ".post-title" --type text --session <name>

# ❌ Wrong: eval bypasses stealth delays and is less stable
agent-browser eval "document.querySelector('.post-title').textContent" --session <name>
```

### Screenshot & PDF

> **CRITICAL: Screenshot is FORBIDDEN in automation workflows.**
>
> - Screenshot is ONLY for user-requested visual output (e.g., "show me a screenshot", "take a picture")
> - NEVER use screenshot for observation, element discovery, or verification
> - For all automation tasks, use `snapshot` instead — it's faster and designed for LLM consumption

```bash
agent-browser screenshot --session <name>
agent-browser screenshot --full-page --session <name>
agent-browser pdf --output /tmp/page.pdf --session <name>
agent-browser pdf --landscape --session <name>
```

### Agent Mode

Use only when configured for autonomous execution:

```bash
agent-browser run "search Python jobs and return top 5 titles" --session <name> --max-steps 10
```

### Daemon Management

```bash
agent-browser daemon status
agent-browser daemon stop
```

## Output Format

All commands return JSON:

```json
{"success": true, "data": {...}}
{"success": false, "error": "..."}
```

## Error Recovery

- Session not found: run `agent-browser session create --name <name>`
- Element ref not found: call `snapshot` again and re-locate the element by text
- **Login/captcha required**: 
  - Stop automation immediately
  - Check the session creation output for `vnc_url` field
  - Provide the VNC URL to the user: "Please complete login manually at: <vnc_url>"
  - Wait for user confirmation before continuing
  - If no VNC URL available, ask user to check browser window directly
- **Anti-bot / security page detected** (title contains "安全限制", "Access Denied", "Verify"; URL redirected to `/login`, `/captcha`, `/verify`):
  - Stop automation immediately
  - Report to user with current URL and VNC URL
  - Do NOT retry the same URL — wait for user guidance
- **Empty data from `eval`**: page not fully loaded — use `wait "body"` before extracting, or switch to `extract`
- API unreachable: check `agent_browser/skill/config.yaml` service.url and network access

## Anti-Detection Rules

1. **Always `wait` after `open`** — never operate on a page before confirming it loaded
2. **Throttle batch operations** — add `sleep 2` between consecutive page navigations
3. **Prefer `extract` over `eval`** for data extraction — `eval` bypasses stealth delays
4. **Verify page state after navigation** — check title/url for anti-bot or login redirects
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
agent-browser install-skill
```

### macOS / Linux

Shim is created at `~/.local/bin/agent-browser`.

If `agent-browser` command is not found, add to PATH:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Add that line to `~/.bashrc`, `~/.zshrc`, or equivalent to persist across sessions.

### Windows

Shim is created at `%APPDATA%\Python\Scripts\agent-browser.bat`.

If `agent-browser` command is not found, add to PATH via PowerShell (run once as admin):

```powershell
$scripts = "$env:APPDATA\Python\Scripts"
[Environment]::SetEnvironmentVariable("PATH", "$env:PATH;$scripts", "User")
```

Or add `%APPDATA%\Python\Scripts` manually via System Properties → Environment Variables.

### Daemon Auto-Start

The daemon starts automatically on first command and stops after 30 minutes of inactivity.
No manual daemon management is needed during normal use.
