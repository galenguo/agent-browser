# ReAct Workflow -- Detailed Guide

## Overview

The ReAct (Reasoning + Acting) loop is how Claude Code controls browser automation step by step. Each iteration cycles through four phases: Observe, Reason, Act, Check.

This document specifies exact interaction formats for each phase.

## Loop Structure

```
START → Observe → Reason → Act → Check → (pass?) → Observe → ...
                                      ↓ (fail?)
                                 Retry or Report
```

## Phase 1: Observe

**Goal**: Get current page state.

**Action**: Call `sb.snapshot(session_id)`.

**Output format**:
```json
{
  "url": "https://www.example.com/search?q=test",
  "title": "Search Results - Example",
  "elements": [
    {"ref": "@e0", "text": "Search...", "role": "input"},
    {"ref": "@e1", "text": "Search", "role": "button"},
    {"ref": "@e2", "text": "Images", "role": "link"},
    {"ref": "@e3", "text": "Videos", "role": "link"}
  ]
}
```

**What to look for**:
- Target element (search box, button, link) -- note its `@eN` ref
- Page state (loaded? loading? error? login required?)
- Navigation status (did URL change as expected?)

**When to re-snapshot**:
- After every action that mutates DOM (click, fill, navigate)
- When an element ref is not found (refs invalidated)
- When check phase shows unexpected state
- At start of each logical "step" in the task

## Phase 2: Reason

**Goal**: Decide next action based on observation.

**Output**: Internal decision (not shown to user). Options:

1. **Continue task** -- execute action on observed element
2. **Adapt** -- page looks different than expected, adjust plan
3. **Hand off to user** -- login, captcha, ambiguous choice needed
4. **Retry** -- previous action may not have completed, try again
5. **Done** -- task complete, extract/present results

**Decision heuristics**:
- If multiple elements match text, pick the most specific (e.g., `role="button"` over `role="div"`)
- If target not visible, scroll toward it first
- If page navigated unexpectedly, assess new page for opportunity
- If same element fails 3x, switch strategy (different selector, different approach)

## Phase 3: Act

**Goal**: Execute one atomic browser operation.

**Available actions** (one per iteration):

```python
from agent_browser.skill.scripts.browser_cli import SkillBrowser

sb = SkillBrowser()
sid = await sb.create_session()

# Navigation
await sb.open_page(sid, "https://example.com")
await sb.go_back(sid)

# Interaction
await sb.click(sid, "@e3")                              # Click button/link
await sb.fill(sid, "@e0", "query")                      # Fill input
await sb.select_option(sid, "@e6", "option_value")      # Dropdown
await sb.hover(sid, "@e4")                              # Hover (reveal submenu etc.)
await sb.press_key(sid, "Enter")                        # Keyboard

# Movement
await sb.scroll(sid, "down", 500)                        # Scroll
await sb.wait_for_selector(sid, ".results", timeout=10000)

# Extraction
data = await sb.evaluate(sid, "document.title")
snap = await sb.snapshot(sid)                            # Fresh observe
```

**Rules**:
- One action per Act phase (then Check)
- Always use latest snapshot refs (not stale ones)
- Validate ref exists before using (catch `SkillBrowserError` → re-snapshot)

## Phase 4: Check

**Goal**: Verify action had intended effect.

**Process**:
1. Re-snapshot (get fresh state)
2. Compare against expected outcome:
   - URL changed? (for navigation)
   - Element gone/changed? (for click/fill)
   - New content appeared? (for search/submit)
   - Error message? (diagnose)
3. Decide: pass → next Observe, or fail → retry/handoff

**Check outcomes**:

| Outcome | Next Action |
|--------|------------|
| As expected | Continue to next Observe (next sub-step of task) |
| Partially worked | Adapt -- use new info to refine next action |
| Unexpected state | Diagnose -- may need different approach |
| Action failed | Retry (same action, up to 3x) then switch strategy |
| User intervention needed | Hand off -- ask user what to do |

## Human-Like Timing

反检测延迟由服务端自动处理（人类行为模拟 + 鼠标轨迹 + 打字节奏），客户端无需关心。

## Complete Example: Search Task

```python
from agent_browser.skill.scripts.browser_cli import SkillBrowser

sb = SkillBrowser()
sid = await sb.create_session()

# === OBSERVE ===
await sb.open_page(sid, "https://www.google.com")
snap = await sb.snapshot(sid)
# Found: @e0 = search box, @e1 = "Google Search" button

# === REASON ===
# Plan: fill search box with query → click search → wait → extract results

# === ACT ===
await sb.fill(sid, "@e0", "Python jobs Beijing")
# === CHECK ===
snap2 = await sb.snapshot(sid)
# Still on Google homepage, search box filled. Need to click search or press Enter.
# === ACT ===
await sb.press_key(sid, "Enter")
# === CHECK ===
snap3 = await sb.snapshot(sid)
# URL changed to search results. Elements show results list.
# === OBSERVE (continue) ===
# Extract first 10 result titles and links...
results = []
for el in snap3["elements"][:10]:
    results.append(el["text"])

await sb.delete_session(sid)
return results
```

## Element Reference Lifecycle

1. `sb.snapshot()` assigns refs: `@e0`, `@e1`, `@e2`... to interactive elements
2. Refs are valid **until the next DOM mutation** (click, fill, navigation, JS execution)
3. After mutation: **always re-snapshot** before using refs
4. On `SkillBrowserError` indicating stale ref: re-snapshot to get fresh refs
5. Refs are **session-scoped** -- each session has its own ref numbering

## Standard Flow Templates

**Simple navigation/extraction**:
```python
sb = SkillBrowser()
sid = await sb.create_session()
# create_session -> open_page -> snapshot -> [分析] -> delete_session
await sb.open_page(sid, "https://example.com")
snap = await sb.snapshot(sid)
# ... extract data ...
await sb.delete_session(sid)
```

**Search task**:
```python
sb = SkillBrowser()
sid = await sb.create_session()
# create_session -> open_page(搜索页) -> snapshot -> fill(搜索词) -> click(搜索按钮) -> snapshot -> 提取结果 -> delete_session
await sb.open_page(sid, "https://example.com/search")
snap = await sb.snapshot(sid)
await sb.fill(sid, "@e0", "关键词")
await sb.click(sid, "@e1")
snap2 = await sb.snapshot(sid)
# ... extract results ...
await sb.delete_session(sid)
```

**QR code login**:
```python
sb = SkillBrowser()
sid = await sb.create_session()
# create_session -> open_page(登录页) -> click(扫码登录) -> 告知用户扫码 -> 用户确认后继续
await sb.open_page(sid, "https://example.com/login")
snap = await sb.snapshot(sid)
# 找到扫码登录按钮并点击
await sb.click(sid, "@e2")
# 告知用户："请扫码登录，完成后告诉我"
# ... 用户确认后继续 ...
await sb.delete_session(sid)
```

## Error Handling in ReAct Loop

When a `SkillBrowserError` is raised during any phase:

1. **Element not found** (`@eN` stale) → re-snapshot to get fresh refs, retry (up to 3x)
2. **Session not found** → re-create session via `sb.create_session()`, re-navigate
3. **Timeout / slow page** → wait longer, re-snapshot
4. **3 consecutive failures** → switch strategy or hand off to user
5. **Auth / login required** → stop and ask user (human-only block)

```python
from agent_browser.skill.scripts.browser_cli import SkillBrowser, SkillBrowserError

sb = SkillBrowser()
sid = await sb.create_session()

for attempt in range(3):
    try:
        await sb.click(sid, "@e3")
        snap = await sb.snapshot(sid)
        break  # success
    except SkillBrowserError as e:
        if attempt == 2:
            # 报告用户，切换策略
            break
        snap = await sb.snapshot(sid)  # re-snapshot for fresh refs
```
