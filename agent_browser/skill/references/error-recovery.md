# Error Recovery Patterns

## Overview

When browser operations fail, the error is classified and a recovery action is taken. This document catalogs all error patterns, their diagnoses, and recovery actions.

## Error Classification Hierarchy

```
FirstSessionError (setup-time errors)
  ├── MissingDependency (pip package not installed)
  ├── CDPUnreachable (browser not running)
  └── MissingAPIKey (LLM mode needs key)

PipelineError (runtime errors)
  ├── ElementNotFound (@eN ref stale / selector mismatch)
  ├── StepTimeout (operation exceeded time limit)
  ├── NavigationError (URL invalid / blocked)
  └── AuthFailure (login session expired / blocked)

ConnectionError (infrastructure errors)
  ├── ExtensionDisconnected (Chrome Extension not connected)
  ├── DaemonCrashed (BrowserDaemon process died)
  └── APIError (Remote server error)
```

## Recovery Decision Tree

```
Error occurs
  │
  ├─ Is it FirstSessionError?
  │   ├─ Yes → Run doctor.py → auto-fix what's possible → report unfixable to user
  │   └─ No → continue
  │
  ├─ Is it ElementNotFound?
  │   ├─ Yes → re-snapshot (1) → find by text/selector (2) → retry original action (3)
  │   │         └─ If still fails after 3 attempts → report to user with context
  │   └─ No → continue
  │
  ├─ Is it TimeoutError?
  │   ├─ Yes → wait 2s → retry once → if still timeout → increase timeout or report
  │   └─ No → continue
  │
  ├─ Is it ConnectionError (Extension)?
  │   ├─ Yes → "Extension not connected. Install Chrome Extension from extension/ directory."
  │   │        One-time setup. Falling back to LocalCDPBackend.
  │   └─ No → continue
  │
  └─ Is it unknown/unclassified?
      → Log error + present to user with suggestion
```

## Detailed Error Patterns

### E1: CDP Not Reachable

**Symptom**: `ConnectionError: Failed to connect to CDP at http://127.0.0.1:19222`

**Cause**: CloakBrowser not launched or not running.

**Recovery**:
```python
# Auto-fix attempt:
# 1. Check if cloakbrowser package installed
try:
    import cloakbrowser
except ImportError:
    # Degrade to vanilla Playwright -- no anti-detection but works
    pass

# 2. Try launching browser via existing mechanism
# The daemon's ensure_connected() handles this
```

**User action needed**: None (automatic). If CloakBrowser not installed, degrades gracefully to vanilla Playwright mode.

---

### E2: Element @eN Not Found

**Symptom**: `ValueError: Element @e3 not found. DOM may have changed.`

**Cause**: Page mutated after snapshot (JS executed, async load, SPA route change).

**Recovery** (automatic, up to 3 retries):
```python
for attempt in range(3):
    snap = await snapshot(session_id)  # Fresh refs
    # Find element by text content instead of ref
    for el in snap["elements"]:
        if target_text in el.get("text", ""):
            # Use this element's ref for the action
            await click(session_id, el["ref"])
            return
    await asyncio.sleep(1)  # Brief wait before retry
```

**User action needed**: None if auto-recovery succeeds. After 3 failures: present screenshot/context to user.

---

### E3: Timeout / Slow Page

**Symptom**: `TimeoutError` or operation hangs >30s.

**Cause**: Page slow to load, heavy JS, network latency, anti-bot challenge.

**Recovery**:
```python
# Increase timeout for this specific operation
await click(session_id, "@e3")  # Uses default timeout
# If timing out:
await fill(session_id, "@e5", "text", timeout=30)  # Explicit longer timeout

# For wait_for_selector:
await wait_for_selector(session_id, ".results", timeout=20000)  # 20s instead of default 10s
```

**User action needed**: None if retry succeeds. If persistent slowdown: suggest checking network or using a different page.

---

### E4: FirstSessionError (Setup Needed)

**Symptom**: `FirstSessionError: Setup needed: [diagnosis]`

**Cause**: One or more dependencies missing or misconfigured.

**Recovery**:
```python
from agent_browser import setup
result = await setup()

if not result["ready"]:
    print("Issues found:")
    for issue in result["issues"]:
        print(f"  - {issue}")
    print("\nFixable automatically:")
    for fix in result["report"].fixable:
        print(f"  - {fix['name']}: {fix['command']}")
    
    # Auto-run fixes
    for fix in result["report"].fixable:
        os.system(fix["command"])
```

**User action needed**: Maybe. If LLM API key missing, user must provide it. Everything else is auto-fixed.

---

### E5: Extension Not Connected

**Symptom**: `ConnectionError: Chrome Extension not connected. Please install the Agent Browser Bridge extension.`

**Cause**: Chrome Extension not loaded, not enabled, or Chrome not running.

**Recovery**:
```
1. Automatic fallback to LocalCDPBackend (happens in _select_backend())
2. Inform user: "Extension mode unavailable. Using LocalCDPBackend (CloakBrowser) instead."
3. Next session: will try Extension again (intermittent if user enables it)
```

**User action needed**: One-time setup.
1. Open `chrome://extensions/`
2. Enable "Developer mode"
3. Click "Load unpacked"
4. Select `extension/` directory from agent-browser project
5. Ensure badge shows connected state

---

### E6: Agent Stuck (Repeated Empty Results)

**Symptom**: Agent returns `status: "stuck"` or same empty result 3+ times.

**Cause**: Anti-bot detection triggered, captcha wall, infinite redirect loop, or page structure doesn't match expectations.

**Recovery**:
```python
# Take screenshot for context
await evaluate(session_id, "document.title")
# Suggest manual intervention
# Present options:
# A) Try different approach (e.g., use adapter instead of ReAct)
# B) Open VNC/manual browser to solve captcha
# C) Skip this task / try different site
```

**User action needed**: Yes. This usually requires human intervention (captcha, manual login).

---

### E7: CloakBrowser Not Installed

**Symptom**: `ImportError: No module named 'cloakbrowser'`

**Cause**: Basic install (`pip install agent-browser`) without `[cloak]` extra.

**Recovery**:
```
Automatic: Continue in vanilla mode (Playwright only, layers 6-7 of stealth).
Optional: User can run `pip install agent-browser[cloak]` for full protection.
No blocking -- skill continues working with reduced anti-detection.
```

**User action needed**: None (auto-degrade). Inform user about reduced capability.

## Writing Recovery Code in SKILL.md Context

When writing SKILL.md instructions or when Claude encounters errors during execution:

```python
# Pattern for error handling in ReAct loop:
try:
    await click(session_id, "@e3")
except ValueError as e:
    if "not found" in str(e).lower():
        # E2 recovery: re-snapshot + retry
        snap = await snapshot(session_id)
        # ... find element again ...
    elif "connection" in str(e).lower():
        # E5 or E1 recovery: diagnose + fallback
        ...
except Exception as e:
    # Unknown error: log + present to user
```

The key principle: **never silently fail**. Every error either triggers automatic recovery or gets presented to the user with enough context to act on.
