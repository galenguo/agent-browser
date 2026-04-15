# Error Recovery Patterns

## Overview

When SkillBrowser HTTP operations fail, the error is classified and a recovery
action is taken. This document catalogs every error visible to the
SkillBrowser HTTP client, their diagnoses, and recovery actions.

All errors surface as `SkillBrowserError` instances with `status_code` and
`url` attributes. Server-side concerns (CDP, CloakBrowser, Daemon, Extension,
StealthMiddleware circuit breaker) are handled entirely by the API server and
are never exposed to the client.

## Error Classification Hierarchy

```
SkillBrowserError
  status_code=0   API service not reachable
  status_code=401  Authentication failed
  status_code=404  Session not found
  status_code=409  Conflict (API key bound to another session)
  status_code=503  Pool exhausted (no browser instances available)
  status_code=*    Element @eN not found (message-based)
  status_code=*    Task timeout / stuck (result-based)
```

## Recovery Decision Tree

```
SkillBrowserError caught
  |
  +-- status_code == 0?
  |     +-- Yes -> E1: API unreachable -> diagnose() -> check config.yaml
  |
  +-- status_code == 401?
  |     +-- Yes -> E2: Auth failed -> check api_key in config.yaml
  |
  +-- status_code == 404 and "session" in message?
  |     +-- Yes -> E4: Session gone -> re-create session
  |
  +-- status_code == 409?
  |     +-- Yes -> E5: Conflict -> resolve API key / session binding
  |
  +-- "not found" in message and "@e" in message?
  |     +-- Yes -> E3: Element stale -> re-snapshot -> retry
  |
  +-- result["status"] == "timeout"?
  |     +-- Yes -> E6: Task timeout -> increase total_timeout or simplify
  |
  +-- result["status"] == "stuck"?
  |     +-- Yes -> E7: Agent stuck -> present to user for intervention
  |
  +-- otherwise -> unknown -> log + present to user with context

CLASSIFY -> ATTEMPT auto-fix -> fails 3x -> PRESENT TO USER
```

## Detailed Error Patterns

### E1: API Service Not Reachable

**Symptom**: `SkillBrowserError` with `status_code=0`, message contains
"Cannot connect" or "Request failed".

**Cause**: The API server at the configured `api_url` is not running, not
reachable from the network, or the URL is wrong.

**Recovery**:

```python
sb = SkillBrowser()
try:
    await sb.create_session()
except SkillBrowserError as e:
    if e.status_code == 0:
        report = await sb.diagnose()
        if not report["ready"]:
            # report["errors"] lists what is wrong
            for err in report["errors"]:
                print(err)
            # Common fix: edit agent_browser/skill/config.yaml
            #   service:
            #     url: http://correct-host:8000
```

**User action needed**: Ensure the API server is running and the URL in
`config.yaml` (or the `api_url` constructor param) points to it.

---

### E2: Authentication Failed (401)

**Symptom**: `SkillBrowserError` with `status_code=401`.

**Cause**: The API server requires an API key, and the key provided is
missing, incorrect, or expired.

**Recovery**:

```python
sb = SkillBrowser()
try:
    await sb.create_session()
except SkillBrowserError as e:
    if e.status_code == 401:
        # Check that api_key is configured
        report = await sb.diagnose()
        for check in report["checks"]:
            if check["name"] == "api_auth" and check["status"] == "warn":
                print(check["message"])
                # Fix: edit agent_browser/skill/config.yaml
                #   service:
                #     api_key: your-correct-key
```

**User action needed**: Set the correct `api_key` in `config.yaml` or pass it
to the `SkillBrowser(api_key=...)` constructor.

---

### E3: Element @eN Not Found

**Symptom**: `SkillBrowserError` from a click/fill/select call, message
contains "not found" and an `@eN` reference.

**Cause**: The page DOM changed after the last snapshot -- JS executed, async
content loaded, or an SPA routed to a different view. The element reference is
stale.

**Recovery** (automatic, up to 3 retries):

```python
sb = SkillBrowser()
sid = await sb.create_session()
# ... navigate and work ...

for attempt in range(3):
    try:
        await sb.click(sid, "@e3")
        break
    except SkillBrowserError as e:
        if "not found" not in str(e).lower() or "@e" not in str(e):
            raise
        # Re-snapshot to get fresh element references
        snap = await sb.snapshot(sid)
        # Find the element by text content instead of stale ref
        target_text = "Submit"
        for el in snap["elements"]:
            if target_text in el.get("text", ""):
                await sb.click(sid, el["ref"])
                break
        else:
            await asyncio.sleep(1)
            continue
        break
else:
    # Failed 3 times -- present to user
    snap = await sb.snapshot(sid)
    print(f"Could not find element. Current page: {snap['url']}")
    print(f"Available elements: {[e['ref'] for e in snap['elements']]}")
```

**User action needed**: None if auto-recovery succeeds. After 3 failures:
present current page URL and available elements to the user.

---

### E4: Session Not Found (404)

**Symptom**: `SkillBrowserError` with `status_code=404`, message references a
session ID.

**Cause**: The session expired on the server, the server restarted, or the
session ID is invalid.

**Recovery**:

```python
sb = SkillBrowser()
try:
    await sb.snapshot(sid)
except SkillBrowserError as e:
    if e.status_code == 404:
        # Session is gone -- create a new one
        sid = await sb.create_session()
        await sb.open_page(sid, url)
        # Re-do whatever was needed
```

**User action needed**: None. The session is re-created automatically. Any
page state from the old session is lost and must be re-established
(re-navigate, re-login if required).

---

### E5: Conflict (409)

**Symptom**: `SkillBrowserError` with `status_code=409`.

**Cause**: The API key is already bound to an active session on the server.
Each API key can only hold one session at a time.

**Recovery**:

```python
sb = SkillBrowser()
try:
    sid = await sb.create_session()
except SkillBrowserError as e:
    if e.status_code == 409:
        # The previous session still exists -- delete it first
        # Option A: If you know the old session ID, delete it
        await sb.delete_session(old_session_id)
        sid = await sb.create_session()

        # Option B: Use a different API key for concurrent sessions
        # sb2 = SkillBrowser(api_key="key-bob-002")
```

**User action needed**: Delete the existing session or use a separate API key
for concurrent sessions.

---

### E6: Task Timeout

**Symptom**: `run_task()` returns `{"status": "timeout", ...}` or raises a
`SkillBrowserError` indicating the task did not complete in time.

**Cause**: The task is too complex for the configured `total_timeout`, the page
is slow, or the agent is caught in a loop.

**Recovery**:

```python
sb = SkillBrowser()
result = await sb.run_task(
    sid,
    "Search for machine learning papers",
    total_timeout=300,   # default
)

if result.get("status") == "timeout":
    # Retry with a longer timeout or a simpler task
    result = await sb.run_task(
        sid,
        "Search for machine learning papers",
        total_timeout=600,       # double the timeout
        max_steps=4,             # fewer steps per chunk
    )
```

**User action needed**: Increase `total_timeout`, reduce `max_steps`, or
simplify the task description.

---

### E7: Agent Stuck

**Symptom**: `run_task()` returns `{"status": "stuck", ...}` or the agent
produces the same empty result repeatedly.

**Cause**: Anti-bot detection triggered, CAPTCHA wall, infinite redirect loop,
or the page structure does not match the agent's expectations.

**Recovery**:

```python
sb = SkillBrowser()
result = await sb.run_task(sid, "Apply to this job listing")

if result.get("status") == "stuck":
    # Gather context for the user
    snap = await sb.snapshot(sid)
    print(f"Agent stuck on: {snap['url']}")
    print(f"Page title: {snap['title']}")
    print(f"Visible elements: {[e['text'][:40] for e in snap['elements'][:10]]}")
    # Present options to the user:
    # A) Try a different approach (e.g., use a YAML adapter instead of agent)
    # B) Human solves CAPTCHA / logs in manually, then retry
    # C) Skip this task
```

**User action needed**: Yes. This almost always requires human intervention --
solving a CAPTCHA, completing a login, or choosing an alternative strategy.

---

### E8: Pool Exhausted (503)

**Symptom**: `SkillBrowserError` with `status_code=503` and message
containing "pool" or "Resource exhausted".

**Cause**: All browser instances are occupied. The server cannot allocate
a new browser for the requested session.

**Recovery**:

```python
sb = SkillBrowser()
try:
    sid = await sb.create_session()
except SkillBrowserError as e:
    if e.status_code == 503:
        # The client auto-deletes the user's own stale sessions first.
        # If still failing, the pool is genuinely full.
        import asyncio
        await asyncio.sleep(10)
        sid = await sb.create_session()  # retry
```

**User action needed**: Wait a moment and retry. If the error persists,
contact the server administrator to increase the pool size.

## General Recovery Flow

Every error follows the same three-stage process:

```
1. CLASSIFY
   Inspect SkillBrowserError.status_code and message text.
   Match to E1-E8 above.

2. ATTEMPT AUTO-FIX (up to 3 times)
   E1 -> sb.diagnose() + report errors
   E2 -> check api_key config
   E3 -> re-snapshot + find element by text
   E4 -> re-create session + re-navigate
   E5 -> delete old session or use new API key
   E6 -> increase total_timeout or simplify task
   E7 -> gather context (no auto-fix possible)
   E8 -> wait and retry

3. FAILS 3x -> PRESENT TO USER
   After 3 consecutive auto-recovery failures, stop and present:
   - The error message and status code
   - The current page URL and title
   - Available element references (if applicable)
   - Suggested next steps for the user
```

## Human Handoff Points

The following situations always require user intervention -- do not retry
indefinitely:

| Situation | Why | What to tell the user |
|-----------|-----|----------------------|
| API unreachable after `diagnose()` | Server may be down or URL wrong | "Browser service is not reachable. Start the API server or edit config.yaml." |
| 401 auth failed after key check | Key is invalid or revoked | "API key was rejected. Update api_key in config.yaml." |
| Agent stuck (E7) | CAPTCHA / login / anti-bot | "Agent is stuck and needs human help. Open the page manually to resolve the block, then retry." |
| Element not found after 3 retries | Page structure changed unexpectedly | "Cannot find the target element. The page may have changed. Review the current snapshot and choose a different element." |
| Session lost 3 times in a row | Server instability | "Sessions keep expiring. The API server may be restarting. Wait and try again." |

The key principle: **never silently fail**. Every error either triggers
automatic recovery or gets presented to the user with `status_code`, `url`,
and enough context to act on.
