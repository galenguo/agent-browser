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

### Basic Usage

```python
import asyncio
from agent_browser import create_session, open_page, snapshot, click, fill

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

asyncio.run(main())
```

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
├── browser/          # Backend ABCs + implementations (local, remote, extension)
├── stealth/         # Anti-detection: middleware, enhancer, actions, patches
├── pipeline/        # YAML pipeline engine v2.3
├── explore/         # Site explorer + adapter synthesizer
├── adapters/        # Site adapter loader/runner/validator
├── intelligence/    # Agent task execution (browser-use integration)
├── session/         # Multi-user session management
├── cli/             # Command-line interface
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
