# Agent Browser

> Anti-detection browser automation framework built on [browser-use](https://github.com/browser-use/browser-use).

Agent Browser extends **browser-use** with industrial-grade anti-detection capabilities, a YAML pipeline engine, site exploration, and adapter synthesis. It is designed for **browser-use power users** who hit detection walls when automating interactions with protected websites.

## Features

### 7-Layer Anti-Detection Stack

| Layer | Component | What it does |
|-------|-----------|--------------|
| 1 | CloakBrowser | C++-level fingerprint spoofing (33 patches) |
| 2 | patchright | Driver-level CDP patching |
| 3 | rebrowser-patches | Runtime.Enable leak fix |
| 4 | Non-standard port 19222 | Connection obfuscation |
| 5 | Persistent CDP sessions | Prevents frequent attach/detach |
| 6 | StealthEnhancer | Human-like delays, Bezier mouse curves, per-character typing |
| 7 | StealthMiddleware | Centralized stealth layer with per-session circuit breaker |

### Pipeline Engine v2.3

- YAML-driven automation pipelines
- 19 template filters with arithmetic expressions
- Typed error hierarchy (6 error categories)
- Automatic error classification and recovery
- Single-step debugger with breakpoints
- JSONL telemetry for execution tracking

### Site Explorer

- Automatic DOM structure analysis
- Cascade CSS selector generation
- YAML adapter synthesis from exploration results

## Quick Start

### Install

```bash
# Basic (stealth layers 6-7 only, works with standard Playwright)
pip install agent-browser

# Full anti-detection (all 7 layers, requires CloakBrowser)
pip install agent-browser[cloak]

# With server mode (FastAPI + LLM integrations)
pip install agent-browser[full]
```

### Basic Usage (Functional API)

```python
import asyncio
from agent_browser import create_session, open_page, snapshot, click, fill, evaluate

async def main():
    # Create a stealth-wrapped browser session
    session_id = await create_session()

    # Navigate to a page (automatic stealth delays applied)
    await open_page(session_id, "https://example.com")

    # Take a snapshot (returns interactive elements with refs)
    data = await snapshot(session_id)
    print(f"Found {len(data['elements'])} elements")

    # Interact using element refs
    await click(session_id, "@e0")  # Click first interactive element
    await fill(session_id, "@e1", "hello world")

    # Execute JavaScript in page context
    title = await evaluate(session_id, "document.title")
    print(f"Page title: {title}")

asyncio.run(main())
```

### OOP Interface

```python
import asyncio
from agent_browser import AgentBrowser

async def main():
    async with AgentBrowser() as ab:
        # Create session (auto-tracked)
        await ab.create_session()

        # All methods omit session_id when tracked
        await ab.open_page("https://example.com")
        snap = await ab.snapshot()
        print(f"Found {len(snap['elements'])} elements")

        await ab.click("@e0")
        await ab.fill("@e1", "hello world")
        result = await ab.evaluate("document.title")
        print(f"Title: {result}")

        # Run autonomous agent task
        task_result = await ab.run_task("Find the search box and type 'python'")
        print(f"Task: {task_result['status']}")

asyncio.run(main())
```

### Server Mode (FastAPI)

```bash
# Install with server dependencies
pip install agent-browser[full]

# Start the API server
uvicorn agent_browser.api:app --port 8000

# Check health
curl http://localhost:8000/health
# {"status":"ok","sessions":0,"max_concurrent":10,"browser_mode":"local"}
```

**REST API endpoints** (all under `/sessions/{session_id}/`):

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Server health + pool stats |
| POST | `/sessions/create` | Create session (`{"user_id": "..."}`) |
| GET | `/sessions/{id}` | Session status |
| DELETE | `/sessions/{id}` | Delete session |
| POST | `/navigate` | Navigate to URL |
| POST | `/snapshot` | DOM snapshot |
| POST | `/click` | Click element by ref |
| POST | `/fill` | Fill input field |
| POST | `/evaluate` | Execute JavaScript |
| POST | `/task` | Submit LLM/Agent task |

### Public API Reference

| Function | Description |
|----------|-------------|
| `create_session()` | Create browser session, returns UUID |
| `open_page(sid, url)` | Navigate to URL |
| `snapshot(sid)` | Get DOM snapshot with `@eN` element refs |
| `click(sid, ref)` | Click element by ref (`"@e0"`) |
| `fill(sid, ref, text)` | Type text into input element |
| `scroll(sid, direction, amount)` | Scroll page |
| `select_option(sid, ref, value)` | Select dropdown option |
| `hover(sid, ref)` | Move mouse to element center |
| `press_key(sid, key)` | Press keyboard key |
| `wait_for_selector(sel, timeout)` | Wait for CSS selector |
| `go_back(sid)` | Navigate back |
| **`evaluate(sid, expr)`** | Execute JS, return result |
| `run_task(sid, task, intelligence)` | LLM/Agent autonomous task |
| `delete_session(sid)` | Release session resources |
| `configure(**kwargs)` | Update config for next session |
| `reset()` | Clear all global state |
| `setup()` | Full first-session setup with validation |

### Pipeline Mode

```python
from agent_browser.pipeline import PipelineExecutor

executor = PipelineExecutor(stealth_enabled=True)
result = await executor.run("adapters/my-site.yaml")
print(result)
```

### Explore Mode

```python
from agent_browser.explore import Explorer, Synthesizer
from agent_browser import create_session, open_page

async def main():
    session_id = await create_session()
    await open_page(session_id, "https://target.com")

    explorer = Explorer(session_id)
    snapshot = await explorer.explore()

    # Generate an adapter YAML from the exploration snapshot
    adapter_yaml = Synthesizer.synthesize(snapshot)
    print(adapter_yaml)

asyncio.run(main())
```

### CLI

```bash
agent-browser --help
```

## Architecture

```
agent_browser/
├── __init__.py      # Public API exports + __version__
├── main.py          # Facade API (create_session, snapshot, click, run_task, etc.)
├── client.py        # AgentBrowser OOP interface (session tracking, context manager)
├── config.py        # SkillConfig dataclass + mode detection
├── deploy_config.py # DeployConfig for Docker/K8s deployments
├── browser/         # Backend ABCs + implementations (local, remote, extension)
├── stealth/         # Anti-detection: middleware, enhancer, actions, patches
├── pipeline/        # YAML pipeline engine v2.3
├── explore/         # Site explorer + adapter synthesizer
├── adapters/        # Site adapter loader/runner/validator
├── intelligence/    # Agent task execution (browser-use integration)
├── session/         # Multi-user session management
├── cli/             # Command-line interface (Typer)
├── llm/             # LLM factory (OpenAI, Anthropic, GLM)
└── utils/           # Shared utilities
```

## How It Compares to Raw browser-use

| Feature | browser-use | Agent Browser |
|---------|------------|-------------|
| AI agent automation | Yes | Yes (wraps browser-use) |
| Anti-detection | No | 7-layer stack |
| Human behavior simulation | No | Bezier mouse, per-char typing |
| Circuit breaker | No | Per-session auto-degradation |
| YAML pipeline engine | No | 19-filter template engine |
| Error classification | No | 6-category typed errors |
| Auto-recovery | No | Per-error-category fallback |
| Site exploration | No | DOM analysis -> adapter synthesis |
| Telemetry | No | JSONL execution tracing |
| Debugger | No | Single-step with breakpoints |

## Dependencies

### Core (always installed)

- `browser-use>=0.12.0` - AI browser agent framework
- `playwright>=1.40.0` - Browser automation
- `pydantic>=2.0` - Data validation
- `PyYAML>=6.0` - YAML config/pipeline parsing
- `structlog>=24.0` - Structured logging
- `aiohttp>=3.9.0` - Async HTTP client

### Optional

- `[cloak]` - CloakBrowser C++ fingerprinting + patchright (layers 1-5)
- `[full]` - FastAPI server + LLM integrations (langchain-openai, langchain-anthropic)

## License

Apache 2.0. See [LICENSE](LICENSE) for details.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, code style guidelines, and pull request process.
