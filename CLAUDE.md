# Agent Browser - Development Guide

## Overview

Agent Browser is an AI-driven anti-detection browser automation platform designed for high-protection websites. It combines browser automation with AI agents to enable intelligent web interaction while evading detection systems.

**Core capabilities:**
- Industrial-grade anti-detection (7-layer protection stack + StealthMiddleware circuit breaker)
- Pipeline engine v2.3 (YAML adapters + error classification + auto-recovery + debugger + telemetry)
- Site exploration module (automatic DOM analysis + adapter generation)
- Multi-mode support (CLI/API x LLM/Agent x Local/Extension/Remote)
- Multi-account isolation (independent fingerprints, cookies, proxies)
- Flexible deployment (local/Docker/distributed)

**Typical use cases:**
- Data collection from high-protection websites (Boss Zhipin, Taobao, Zhihu, Bilibili, etc.)
- AI Agent-driven browser automation
- Chrome Extension automation (inherits user login state)
- Anti-scraping system testing and evaluation

## Architecture

### 7-Layer Anti-Detection Stack

| Layer | Component | Function |
|------|-----------|----------|
| 1 | CloakBrowser | C++ compile-level fingerprint spoofing (33 patches) |
| 2 | patchright | Driver-level CDP patches (removes `__playwright__binding__`) |
| 3 | rebrowser-patches | Runtime.Enable leak fix (addBinding mode) |
| 4 | Non-standard port 19222 | Bound to 127.0.0.1 for connection obfuscation |
| 5 | Persistent CDP sessions | BrowserDaemon prevents frequent attach/detach |
| 6 | StealthEnhancer | Human delays + Bezier mouse + character-by-character typing |
| 7 | **StealthMiddleware** | **Centralized stealth layer: auto pre/post delay + circuit breaker** |

**Note on optional dependencies:** Layers 1-5 require the `[cloak]` extra (`pip install agent-browser[cloak]`). A basic install (`pip install agent-browser`) works with plain Playwright and provides layers 6-7 only.

### Package Architecture

```
agent-browser/                          # Project root
├── agent_browser/                      # Single pip-installable package
│   ├── main.py                        # Facade API (create_session, snapshot, click, etc.)
│   ├── config.py                      # SkillConfig dataclass + load_config / detect_mode
│   ├── deploy_config.py               # DeployConfig for Docker/K8s deployments
│   ├── models.py                      # Data models (BrowserInstance, UserSession, etc.)
│   │
│   ├── browser/                       # Browser engine layer
│   │   ├── __init__.py                # BrowserBackend + BrowserPageHandle ABCs
│   │   ├── local.py                   # LocalCDPBackend (CloakBrowser + Playwright)
│   │   ├── remote.py                  # RemoteAPIBackend (HTTP transport)
│   │   ├── extension.py               # ExtensionBackend (Chrome DevTools)
│   │   ├── daemon.py                  # BrowserDaemon (persistent CDP singleton)
│   │   ├── stealth_launcher.py        # CloakBrowser launch with conditional imports
│   │   ├── human_behavior.py          # Human behavior parameters
│   │   ├── instance_pool.py           # Browser instance pool
│   │   └── auth_proxy.py              # Reverse proxy for browser pod CDP + noVNC
│   │
│   ├── stealth/                       # Anti-detection layer (Layers 6-7)
│   │   ├── __init__.py                # Exports all stealth components
│   │   ├── middleware.py              # StealthMiddleware + circuit breaker (Layer 7)
│   │   ├── enhancer.py                # StealthEnhancer: human delays/mouse/typing (Layer 6)
│   │   ├── actions.py                 # Stealth action overrides for browser-use
│   │   ├── patches.py                 # JS runtime injection patches
│   │   └── browser_controller.py      # ActionResult + BrowserController wrapper
│   │
│   ├── pipeline/                      # YAML Pipeline engine v2.3
│   │   ├── executor.py                # Pipeline executor with fallback/telemetry
│   │   ├── steps.py                   # Step implementations via StealthPageHandle
│   │   ├── template.py                # Template engine (19 filters)
│   │   ├── errors.py                  # Typed error hierarchy (6 categories)
│   │   ├── classifier.py              # Error category classifier
│   │   ├── fallback.py                # Auto-recovery strategies per error type
│   │   ├── debugger.py                # Single-step debugger + breakpoints
│   │   └── telemetry.py               # JSONL telemetry stats
│   │
│   ├── explore/                       # Site exploration module
│   │   ├── explorer.py                # Site explorer (network interception, API discovery)
│   │   ├── analysis.py                # DOM structure analysis + capability inference
│   │   ├── cascade.py                 # Cascade CSS selector generation
│   │   └── synthesizer.py             # YAML adapter auto-synthesis
│   │
│   ├── adapters/                      # Site adapter system
│   │   ├── loader.py                  # YAML adapter scanner/loader
│   │   ├── runner.py                  # Adapter execution engine
│   │   └── validator.py               # YAML validation (5 checks)
│   │
│   ├── intelligence/                  # AI agent mode
│   │   ├── __init__.py                # run_task() router
│   │   └── agent_runner.py            # browser-use Agent executor
│   │
│   ├── session/                       # Session management
│   │   ├── pool_manager.py            # Multi-user session pool
│   │   ├── profile_manager.py         # Browser profile management
│   │   └── session_manager.py         # Fingerprint-IP-Cookie consistency
│   │
│   ├── state/                         # Shared state store (distributed coordination)
│   │   └── store.py                   # K8s ConfigMap CAS + InMemory state backend
│   │
│   ├── cli/                           # CLI subsystem
│   │   ├── main.py                    # CLI entry point (Typer app)
│   │   └── commands.py                # CLI command definitions
│   │
│   ├── llm/                           # LLM factory
│   │   └── factory.py                 # OpenAI, Anthropic, GLM providers
│   │
│   ├── skill/                         # Claude Code skill
│   │   ├── SKILL.md                   # Skill definition (triggers, modes, error recovery)
│   │   ├── config.yaml                # Skill configuration (service URL, API key, mode)
│   │   ├── scripts/doctor.py          # Environment diagnostic + auto-fix
│   │   ├── scripts/browser_cli.py     # SkillBrowser client (HTTP facade for Claude Code)
│   │   └── references/                # Progressive disclosure docs
│   │
│   └── utils/                         # Shared utilities
│       ├── refs_generator.py          # Element reference generation (@e0, @e1)
│       ├── action_tracer.py           # Action tracing for debugging
│       └── persistent_session.py      # Cross-process session persistence
│
├── adapters/                          # YAML site adapters (boss, zhihu, bilibili, etc.)
├── tests/                             # Test suite (868 tests)
├── examples/                          # Example scripts
├── pyproject.toml                     # Package config (pip installable)
├── README.md                          # English documentation (source of truth)
├── README.zh-CN.md                    # Chinese translation
├── README.ja.md                       # Japanese translation
├── LICENSE                            # Apache 2.0
├── CONTRIBUTING.md                    # Contribution guidelines
└── .gitignore                         # docs/archive/, data/, profiles/ gitignored
```

### Architecture Diagram

```
+---------------------------------------------------------------------+
|                        main.py (Facade API)                          |
|                 Mode detection + ReAct/Agent routing                 |
+-------------------------------+---------------------------------------+
                                |
+-------------------------------v---------------------------------------+
|                    _ensure_backend() routing                          |
|              run_task() intelligent task dispatch                     |
+---------+-------------+------------------+---------------+-----------+
         |                               |                  |
+--------v------+    +-------------------v---+   +-----------v-----------+
| LocalCDPBackend|    |  ExtensionBackend     |   | RemoteAPIBackend      |
| (CloakBrowser) |    |  (Chrome DevTools)    |   | (HTTP transport)      |
| + BrowserDaemon|    |  + WebSocket          |   |  + aiohttp REST       |
| + StealthEnhncr|    |  + chrome.debugger    |   |  + X-API-Key auth     |
| + browser-use  |    |  + natural fingerprint|   |  + session_id mapping |
+--------+------+    +----------+------------+   +-----------+-----------+
         |                      |                              |
         +----------------------+------------------------------+
                                |
+-------------------------------v---------------------------------------+
|              StealthMiddleware (agent_browser.stealth.middleware)      |
|        pre/post delay + Bezier mouse + human typing + circuit breaker |
|                          (per-session scope)                          |
+-------------------------------+---------------------------------------+
                                |
              +-----------------+------------------+
              |                 |                  |
     +--------v----+  +---------v--------+  +------v--------+
     | BrowserDaemon|  | Pipeline Engine  |  | Explore Module|
     | (persistent  |  | (v2.3)          |  | (site explore |
     |  connection) |  |  + classifier    |  |  + synthesis) |
     +--------------+  |  + fallback      |  +---------------+
                      |  + debugger      |
                      |  + telemetry     |
                      +-----------------+
```

**Core design principles:**
- **LocalCDPBackend is the sole browser operation core**: all browser logic implemented once here
- **ExtensionBackend is the natural fingerprint alternative**: operates user's real Chrome, auto-fallback to LocalCDPBackend when no Extension available
- **RemoteAPIBackend is an HTTP transport layer**: zero business logic, only serialization/deserialization
- **StealthMiddleware is the centralized stealth layer**: auto-wraps all operations, circuit breaker prevents cascading failures
- **User isolation**: each user has independent session, profile, cookies, and fingerprint
- **Persistent sessions**: BrowserDaemon singleton maintains CDP connections across sessions

### Mode Matrix

| Calling Mode | Browser Mode | Backend Implementation | Intelligence | Data Flow |
|-------------|-------------|-----------------------|-------------|-----------|
| CLI | local | LocalCDPBackend (daemon) | LLM | Agent -> Python API -> CDP |
| CLI | extension | ExtensionBackend (Chrome) | LLM | Agent -> WS -> chrome.debugger -> CDP |
| CLI | local | LocalCDPBackend | Agent | Agent -> run_task -> browser-use -> CDP |
| API | local | RemoteAPIBackend -> localhost FastAPI | LLM/Agent | Agent -> HTTP -> FastAPI -> CDP |
| API | remote | RemoteAPIBackend -> Gateway -> Docker | LLM/Agent | Agent -> HTTP -> Gateway -> Docker CDP |

## Code Organization

### Key File Descriptions

**Facade layer:**
- `main.py` - Facade API, unified entry point for all operations
  - `_ensure_backend()` - mode detection + backend routing (local/extension/remote)
  - `run_task()` - Agent-mode task submission
  - `debug_pipeline()` - Pipeline debug entry point
  - Atomic operations: `create_session`, `snapshot`, `click`, `fill`, `scroll`, etc.

- `config.py` - Configuration system
  - `SkillConfig` dataclass - calling_mode, browser_mode, intelligence, daemon, stealth settings
  - `detect_mode()` - auto-detect (localhost:8000/health -> API mode)
  - `load_config()` - config priority: params > env vars > YAML > auto-detect

- `models.py` - Data models (BrowserInstance, UserSession, etc.)

- `deploy_config.py` - DeployConfig for Docker/K8s deployment scenarios

**Backend abstraction layer (`browser/`):**
- `browser/__init__.py` - Backend abstractions
  - `BrowserBackend` ABC - connect, disconnect, create_session, delete_session, get_page
  - `BrowserPageHandle` ABC - goto, evaluate, mouse_wheel, mouse_move, keyboard_press, on, close

- `browser/local.py` - **LocalCDPBackend (sole browser operation core)**
  - CDP connection + session management + StealthEnhancer integration
  - `PlaywrightPageHandle` - thin Playwright Page wrapper
  - Daemon integration: persistent connection + idle disconnect

- `browser/remote.py` - **RemoteAPIBackend (HTTP transport layer)**
  - aiohttp REST calls + X-API-Key authentication
  - `RemotePageHandle` - each method translates to HTTP request

- `browser/extension.py` - **ExtensionBackend (Chrome DevTools)**
  - Connects to Chrome Extension via WebSocket
  - Uses `chrome.debugger` to operate user's real browser
  - Natural fingerprints + inherits login state
  - Auto-fallback to LocalCDPBackend when no Extension available

- `browser/daemon.py` - **BrowserDaemon (persistent CDP singleton)**
  - `ensure_connected()` - lazy connect + auto-reconnect
  - `create_context()` / `destroy_context()` - session lifecycle
  - `_idle_monitor_loop()` - dual-condition idle disconnect

- `browser/stealth_launcher.py` - CloakBrowser launcher with conditional imports (only when `[cloak]` extra installed)

**Stealth layer (`stealth/`):**
- `stealth/middleware.py` - **StealthMiddleware (Layer 7, centralized stealth)**
  - `StealthPageHandle` decorator: auto-injects pre/post action delays by operation type
  - `_PerSessionCircuit` circuit breaker: per-session state machine (CLOSED->OPEN, threshold=5)
  - Operation classification: stealth-wrapped (goto/click/fill/scroll) vs passthrough (evaluate/title/url)

- `stealth/enhancer.py` - **StealthEnhancer (Layer 6)**
  - `pre_action()` - differentiated delays by operation type
  - `human_type()` - 50-250ms/char + 5% typo rate + 10% long pauses
  - `random_mouse_move()` - triple Bezier curves + sinusoidal speed variation
  - `inject_timing_noise()` - Date.now/performance.now offset

- `stealth/actions.py` - Stealth action overrides for browser-use Agent
- `stealth/patches.js` - JS runtime injection patches
- `stealth/browser_controller.py` - ActionResult + BrowserController wrapper

**Pipeline engine v2.3 (`pipeline/`):**
- `pipeline/executor.py` - Executor entry point; integrates fallback + telemetry when fail_fast=False
- `pipeline/steps.py` - Step implementations, all operations execute through StealthPageHandle
- `pipeline/template.py` - Template engine supporting 19 filters and arithmetic expressions
- `pipeline/errors.py` - Typed error hierarchy (6 exception categories + auto-generated fix_hint)
- `pipeline/classifier.py` - Error category classifier (ErrorCategory enum + heuristic matching)
- `pipeline/fallback.py` - Auto-recovery strategies (SELECTOR_DRIFT re-validation / TIMEOUT retry / AUTH_FAILURE marking)
- `pipeline/debugger.py` - Single-step debugger (DebugSession + breakpoints + step history)
- `pipeline/telemetry.py` - JSONL telemetry stats (record/get_stats/get_recent/clear)

**Site exploration module (`explore/`):**
- `explore/explorer.py` - Site explorer with network interception and API discovery
- `explore/analysis.py` - DOM structure analysis + interactive element capability inference
- `explore/cascade.py` - Cascade CSS selector generation
- `explore/synthesizer.py` - YAML adapter auto-synthesis

**Intelligence layer (`intelligence/`):**
- `intelligence/__init__.py` - `run_task()` router
- `intelligence/agent_runner.py` - browser-use Agent executor + stealth_actions + chunked execution

**Session management (`session/`):**
- `session/pool_manager.py` - Multi-user session pool
- `session/profile_manager.py` - Browser profile management
- `session/session_manager.py` - Fingerprint-IP-Cookie consistency enforcement

**Adapter system (`adapters/`):**
- `adapters/loader.py` - YAML adapter scanner/loader
- `adapters/runner.py` - Adapter execution engine
- `adapters/validator.py` - YAML validation (5 checks)

**CLI subsystem (`cli/`):**
- `cli/main.py` - CLI entry point (Typer app)
- `cli/commands.py` - CLI command definitions

**Shared utilities (`utils/`):**
- `utils/refs_generator.py` - Element reference generation (@e0, @e1, ...)
- `utils/action_tracer.py` - Action tracing for debugging
- `utils/persistent_session.py` - Cross-process session persistence

## Development Standards

### Naming Conventions

**File names:** snake_case
```python
stealth_launcher.py
pool_manager.py
local.py  # inside browser/
```

**Class names:** PascalCase
```python
class LocalCDPBackend:
class BrowserDaemon:
class StealthEnhancer:
class StealthMiddleware:
class ExtensionBackend:
class PipelineExecutor:
class ErrorClassifier:
```

**Functions/methods:** snake_case
```python
async def create_session():
async def _ensure_backend():  # private methods prefixed with _
```

**Variables:** snake_case
```python
session_id = "xxx"
_backend = None  # module-level private variables prefixed with _
```

**Constants:** UPPER_SNAKE_CASE
```python
CDP_PORT = 19222
MAX_SESSIONS = 10
```

### Type Hints

Type hints are required on all public APIs:
```python
from typing import Optional, Dict, List

async def create_session(
    cdp_url: str = None,
    mode: str = None,
) -> str:
    pass

class LocalCDPBackend:
    _sessions: Dict[str, LocalSession]
    _daemon: Optional["BrowserDaemon"]
```

### Async/Await Pattern

Async programming is used extensively throughout the codebase:
```python
# Async functions
async def connect():
    await daemon.ensure_connected()

# Background tasks
asyncio.create_task(idle_monitor_loop())
```

### Error Handling

Use custom exceptions from the typed error hierarchy introduced in Pipeline engine v2.2:
```python
from agent_browser.pipeline.errors import (
    PipelineError,              # Base class
    AdapterLoadError,           # Adapter loading failure
    AdapterValidationError,     # Adapter YAML validation failure
    PipelineStepError,          # Step execution error
    StepTimeoutError,           # Step timeout
    SelectorNotFoundError,      # Selector not found
    URLError,                   # URL error
)

# Each error carries context:
# step_index, step_name, adapter_name, fix_hint
err.to_dict()  # Structured output
err.user_message  # User-friendly format
```

All code and comments must be in English. Variable names, function names, and class names are always in English.

## Configuration Management

### Environment Variables

```bash
# Calling mode
AGENT_BROWSER_CALLING_MODE=cli          # cli | api
AGENT_BROWSER_BROWSER_MODE=local        # local | extension | remote
AGENT_BROWSER_INTELLIGENCE=llm          # llm | agent

# Connection config
AGENT_BROWSER_CDP_URL=http://127.0.0.1:19222
AGENT_BROWSER_API_URL=http://localhost:8000
AGENT_BROWSER_API_KEY=xxx

# Daemon config
AGENT_BROWSER_DAEMON_ENABLED=true
AGENT_BROWSER_DAEMON_IDLE_TIMEOUT=1800

# Stealth config
AGENT_BROWSER_STEALTH_ENABLED=true
AGENT_BROWSER_STEALTH_MODE=full           # full | vanilla

# LLM config (Agent mode / Pipeline engine)
LLM_PROVIDER=openai                     # openai | anthropic
LLM_MODEL=gpt-4                         # supports glm-5-turbo, etc.
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.openai.com/v1
ANTHROPIC_API_KEY=sk-ant-xxx
```

### Configuration Priority

1. Explicit parameters (`create_session(mode="api")`)
2. Environment variables (`AGENT_BROWSER_CALLING_MODE`)
3. YAML config (`~/.agent-browser/config.yaml`)
4. Auto-detection (localhost:8000/health)
5. Hardcoded default (CLI + local)

### Auto-Detection Logic

```python
async def detect_mode() -> SkillConfig:
    # 1. Try API mode
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("http://localhost:8000/health", timeout=2) as resp:
                if resp.status == 200:
                    return SkillConfig(calling_mode="api")
    except Exception:
        pass

    # 2. Detect local CDP
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("http://127.0.0.1:19222/json/version", timeout=2) as resp:
                if resp.status == 200:
                    return SkillConfig(calling_mode="cli")
    except Exception:
        pass

    # 3. Default to CLI
    return SkillConfig()
```

## Common Development Tasks

### Adding a New Atomic Operation

1. Define interface in `BrowserPageHandle` ABC (`agent_browser/browser/__init__.py`)
2. Implement in `PlaywrightPageHandle` (`agent_browser/browser/local.py`)
3. Implement in `ExtensionPageHandle` (`agent_browser/browser/extension.py`)
4. Add HTTP mapping in `RemotePageHandle` (`agent_browser/browser/remote.py`)
5. Expose API in `agent_browser/main.py`
6. Export from `agent_browser/__init__.py`

### Adding a New FastAPI Endpoint

1. Add endpoint in the FastAPI app (the server runs `agent_browser` internally)
2. Add corresponding HTTP call in `RemotePageHandle` (`agent_browser/browser/remote.py`)

### Adding a New Pipeline Step

1. Add step implementation in `agent_browser/pipeline/steps.py` (executes via StealthPageHandle)
2. Register step template in `agent_browser/pipeline/template.py` (if variable substitution needed)
3. Register in STEPS registry of `agent_browser/adapters/validator.py` (auto-detected)
4. Add corresponding error type in `agent_browser/pipeline/errors.py` (if needed)
5. Add heuristic classification rule in `agent_browser/pipeline/classifier.py` (if needed)

### Enhancing StealthMiddleware

**Key file:** `agent_browser/stealth/middleware.py`

```python
# Add new operation type mapping
delay_map["new_action"] = (0.3, 0.8)
```

**Also update:** `stealth_actions` in `agent_browser/intelligence/agent_runner.py`

### Adding a New Site Adapter

1. Manual: create YAML file under `adapters/{site}/` directory
2. Automatic: use `explore()` to analyze target site -> `synthesize()` to generate adapter YAML

### Adding a New Browser Backend

1. Create new backend file in `agent_browser/browser/`
2. Implement `BrowserBackend` and `BrowserPageHandle` ABCs
3. Register in `agent_browser/browser/__init__.py`
4. Add routing branch in `_ensure_backend()` in `agent_browser/main.py`
5. Update `browser_mode` enum in `agent_browser/config.py`

## Important Notes

### Anti-Detection Sensitivity

**Do not break anti-detection functionality:**
- Do not change the CDP port (19222)
- Do not remove CloakBrowser launch parameters
- Do not frequently attach/detach CDP sessions (use Daemon)
- Do not inject obvious automation markers into the browser
- Do not bypass StealthMiddleware (it is the centralized stealth layer; bypassing it causes inconsistent detection signals)

### Backend Abstraction

**Keep LocalCDPBackend as the sole browser operation core:**
- All browser operation logic is only implemented in `agent_browser/browser/local.py`
- RemoteAPIBackend only does HTTP serialization, zero business logic
- ExtensionBackend proxies via chrome.debugger, does not re-implement operation logic
- FastAPI server internally runs LocalCDPBackend

### Pipeline Engine Notes

- Adapter YAML must pass all 5 checks in `validator.py` before it can be loaded
- When `fail_fast=True`: errors are thrown immediately; when `fail_fast=False`: fallback is attempted first
- Telemetry writes are non-blocking and do not affect pipeline execution performance
- When debugger breakpoint hits: returns state dictionary, does not return data

### Resource Management

**BrowserDaemon lifecycle:**
- Lazy connection on first `ensure_connected()`
- Dual-condition disconnect: no active sessions AND exceeds idle_timeout
- State persisted to `~/.agent-browser/daemon-state.json`

**StealthMiddleware circuit breaker:**
- Per-session scope (not global), so one session cannot affect others
- Threshold defaults to 5 consecutive failures before OPEN (disables stealth for that session)
- New sessions automatically RESET (failure_count = 0)

### Optional Dependencies

The package has two installation modes:

**Basic install** (layers 6-7 only):
```bash
pip install agent-browser
```
Works with plain Playwright. Provides StealthEnhancer and StealthMiddleware (human behavior simulation), but no C++-level fingerprint spoofing.

**Full install** (all 7 layers):
```bash
pip install agent-browser[cloak]
```
Adds CloakBrowser (C++ compiled Chromium with 33 fingerprint patches), patchright driver-level patches, rebrowser-patches runtime fixes, and non-standard CDP port binding. This activates layers 1-5 of the anti-detection stack.

Code that depends on CloakBrowser uses conditional imports so the basic install never crashes -- features gracefully degrade when cloak extras are absent.

## Tech Stack Reference

**Core dependencies:**
- `playwright` / `patchright` - Browser automation
- `browser-use==0.12.2` - AI agent framework
- `langchain-openai` / `langchain-anthropic` - LLM integration
- `fastapi` + `uvicorn` - REST API
- `aiohttp` - HTTP client (RemoteAPIBackend)
- `cloakbrowser==0.3.18` - Anti-detection Chromium (optional, `[cloak]` extra; C++ compile-level fingerprint spoofing with 33 patches)

**CloakBrowser details (optional dependency):**
- Package name: `cloakbrowser`
- Version: `0.3.18`
- Install location: `.venv/lib/python3.13/site-packages` (when `[cloak]` extra installed)
- Dependencies: `httpx`, `playwright`
- Launch method: Must launch browser via CloakBrowser (not regular Chrome) to activate Layer 1 anti-detection
- CDP port: `127.0.0.1:19222`

**License:** Apache 2.0

## Related Documentation

- `README.md` - Project overview and quickstart (English, source of truth)
- `README.zh-CN.md` - Chinese translation
- `README.ja.md` - Japanese translation
- `CONTRIBUTING.md` - Contribution guidelines
- `LICENSE` - Apache 2.0 license
- `CHANGELOG.md` - Version history
- `AUTORESEARCH.md` - Autonomous optimization experiment rules

---

**Last updated:** 2026-04-13
