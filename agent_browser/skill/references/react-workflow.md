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

**Action**: Call `snapshot(session_id)`.

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
# Navigation
await open_page(session_id, "https://example.com")
await go_back(session_id)

# Interaction
await click(session_id, "@e3")        # Click button/link
await fill(session_id, "@e0", "query")   # Fill input
await select_option(session_id, "@e6", "option_value")  # Dropdown
await hover(session_id, "@e4")       # Hover (reveal submenu etc.)
await press_key(session_id, "Enter")   # Keyboard

# Movement
await scroll(session_id, "down", 500)     # Scroll
await wait_for_selector(session_id, ".results", timeout=10000)

# Extraction
data = await evaluate(session_id, "document.title")
snap = await snapshot(session_id)           # Fresh observe
```

**Rules**:
- One action per Act phase (then Check)
- Always use latest snapshot refs (not stale ones)
- Validate ref exists before using (catch ValueError → re-snapshot)

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

## Human-Like Timing (Applied Automatically by StealthMiddleware)

Operations are automatically wrapped with human-like delays. You don't need to add these manually, but knowing them helps you understand behavior:

| Operation | Pre-delay | Post-delay | Why |
|-----------|-----------|------------|-----|
| navigate | 0.5-1.5s | 0.05-0.2s | Page load time |
| click | 0.1-0.3s | 0.05-0.2s | Button response |
| fill/input | 0.3-0.8s | 0.05-0.2s | Typing simulation |
| scroll | 0.3-1.0s | 0.05-0.2s | Content settling |
| general | 0.1-0.5s | 0.05-0.2s | Default |

Additional behaviors (handled by StealthEnhancer):
- Typing: 50-250ms per character, 5% typo rate, 10% long pauses
- Mouse movement: Triple Bezier curves, sinusoidal speed variation
- Timing noise injection via Date.now/performance.now offset

## Complete Example: Search Task

```python
# === OBserve ===
sid = await create_session()
await open_page(sid, "https://www.google.com")
snap = await snapshot(sid)
# Found: @e0 = search box, @e1 = "Google Search" button

# === REASON ===
# Plan: fill search box with query → click search → wait → extract results

# === ACT ===
await fill(sid, "@e0", "Python jobs Beijing")
# === CHECK ===
snap2 = await snapshot(sid)
# Still on Google homepage, search box filled. Need to click search or press Enter.
# === ACT ===
await press_key(sid, "Enter")
# === CHECK ===
snap3 = await snapshot(sid)
# URL changed to search results. Elements show results list.
# === OBERVE (continue) ===
# Extract first 10 result titles and links...
results = []
for el in snap3["elements"][:10]:
    results.append(el["text"])

await delete_session(sid)
return results
```

## Element Reference Lifecycle

1. `snapshot()` assigns refs: `@e0`, `@e1`, `@e2`... to interactive elements
2. Refs are valid **until the next DOM mutation** (click, fill, navigation, JS execution)
3. After mutation: **always re-snapshot** before using refs
4. On `ValueError("Element @eN not found")`: the ref is stale, re-snapshot to get fresh refs
5. Refs are **session-scoped** -- each session has its own ref numbering
