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
> **Do not use screenshot in loops.** Use `snapshot` for observation.
> Only use screenshot when the user explicitly asks for visual output.

## Quick Start

```bash
agent-browser session create --name default
agent-browser open https://example.com --session default
agent-browser snapshot --session default -i
agent-browser click @e3 --session default
agent-browser fill @e1 "search term" --session default
agent-browser press Enter --session default
agent-browser snapshot --session default -i
```

## Core Workflow (LLM mode)

Use the ReAct loop with lightweight snapshots:

```bash
snapshot → analyze → click/fill/scroll → snapshot → verify → repeat
```

Example:

```bash
agent-browser open https://example.com --session default
agent-browser snapshot --session default -i
# pick ref @e2 from snapshot output
agent-browser click @e2 --session default
agent-browser snapshot --session default -i
```

## Key Commands

### Session Management

```bash
agent-browser session create --name <name>
agent-browser session list
agent-browser session destroy <name>
```

### Navigation

```bash
agent-browser open <url> --session <name>
agent-browser back --session <name>
```

### Observation

```bash
agent-browser snapshot --session <name> -i
# -i returns interactive elements only
```

### Interaction

```bash
agent-browser click <ref> --session <name>
agent-browser fill <ref> <text> --session <name>
agent-browser scroll down --amount 500 --session <name>
agent-browser press Enter --session <name>
```

### Content Extraction

```bash
agent-browser extract --type text --session <name>
agent-browser extract --type html --session <name>
agent-browser extract --type links --session <name>
agent-browser extract --selector "#content" --type text --session <name>
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
- Login/captcha: stop automation and ask user to complete manual verification
- API unreachable: check `agent_browser/skill/config.yaml` service.url and network access

## Performance Rules

1. Always use `snapshot` for observation loops
2. Avoid screenshots unless explicitly requested
3. Reuse named sessions instead of creating new sessions repeatedly
4. Prefer small atomic actions and re-snapshot after page changes

## Installation Notes

`agent-browser install-skill` installs:
- `~/.claude/skills/agent-browser/` skill files
- `~/.local/bin/agent-browser` shim command

If `agent-browser` command is not found, add `~/.local/bin` to PATH:

```bash
export PATH="$HOME/.local/bin:$PATH"
```
