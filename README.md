[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE)
[![PyPI version](https://img.shields.io/pypi/v/agent-browser.svg)](https://pypi.org/project/agent-browser/)
[![CI](https://github.com/galen/agent-browser/actions/workflows/ci.yml/badge.svg)](https://github.com/galen/agent-browser/actions/workflows/ci.yml)

# Agent Browser

> Anti-detection browser automation framework built on [browser-use](https://github.com/browser-use/browser-use).

Agent Browser extends **browser-use** with industrial-grade anti-detection capabilities, a YAML pipeline engine, site exploration, and adapter synthesis. It is designed for **browser-use power users** who hit detection walls when automating interactions with protected websites.

## What It Does

- **Evades detection** -- 7-layer anti-detection stack from C++ fingerprint spoofing to AI-driven circuit breaker
- **Automates at scale** -- YAML pipeline engine v2.3 with auto-recovery, error classification, and single-step debugger
- **Runs anywhere** -- CLI, REST API, or Python library; local browser, Chrome extension, or remote gateway
- **Explores sites** -- automatic DOM analysis + cascade CSS selector generation + YAML adapter synthesis

## Quick Start

```bash
pip install agent-browser
```

```python
import asyncio
from agent_browser import create_session, open_page, snapshot, click, fill

async def main():
    session_id = await create_session()
    await open_page(session_id, "https://example.com")

    data = await snapshot(session_id)
    print(f"Found {len(data['elements'])} interactive elements")

    await click(session_id, "@e0")       # Click by element ref
    await fill(session_id, "@e1", "hello")  # Type into input

asyncio.run(main())
```

## Features

### Anti-Detection (7 Layers)

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
- Typed error hierarchy (6 categories)
- Automatic error classification and recovery
- Single-step debugger with breakpoints
- JSONL telemetry for execution tracking

### Multi-Mode Support

| Mode | Browser | Intelligence | Use Case |
|------|---------|-------------|----------|
| CLI + local | CloakBrowser / Playwright | LLM or Agent | Local development |
| CLI + extension | User's Chrome (real fingerprint) | LLM or Agent | Production scraping |
| API + local | FastAPI -> local CDP | LLM or Agent | Team server |
| API + remote | FastAPI -> Docker gateway | LLM or Agent | Distributed cluster |

### Site Exploration & Adapter Synthesis

- Automatic DOM structure analysis
- Cascade CSS selector generation
- One-command YAML adapter synthesis from exploration results

## Installation

```bash
# Basic (stealth layers 6-7 only, works with standard Playwright)
pip install agent-browser

# Full anti-detection (all 7 layers, requires CloakBrowser)
pip install agent-browser[cloak]

# With server mode (FastAPI + LLM integrations)
pip install agent-browser[full]
```

<details>
<summary>From Source</summary>

```bash
git clone https://github.com/galen/agent-browser.git
cd agent-browser
pip install -e ".[full]"
playwright install chromium
```

</details>

## Usage

### Getting Started with Claude Code

Agent Browser includes a **Claude Code skill** that lets you control browsers directly from conversation:

```bash
# 1. Install the package
pip install agent-browser

# 2. Install the Claude Code skill (copies SKILL.md to ~/.claude/skills/)
agent-browser install-skill

# 3. Restart Claude Code, then use it naturally:
#   "Open https://example.com and tell me what's on the page"
#   "Search for Python jobs on Boss Zhipin"
#   "Fill out this form with my details"
```

The skill auto-detects your environment, installs missing dependencies, and guides you through the ReAct loop (Observe -> Reason -> Act -> Check). See [skill/SKILL.md](agent_browser/skill/SKILL.md) for the full skill definition.

#### Skill Configuration (`~/.agent-browser/skill.yaml`)

The skill reads client config from `~/.agent-browser/skill.yaml` (flat YAML keys):

```yaml
# Local mode (default) -- direct CloakBrowser CDP, no server needed
calling_mode: cli
browser_mode: local
remote_type: aio
api_url: http://localhost:8000

# Remote AIO -- single server with noVNC
calling_mode: api
browser_mode: remote
remote_type: aio
api_url: http://my-server:8000
vnc_url: http://my-server:6080

# Remote distributed -- cluster deployment, per-session VNC
calling_mode: api
browser_mode: remote
remote_type: distributed
api_url: http://my-gateway:8000
```

Generate `skill.yaml` with the setup script:

```bash
# Local mode
python -m agent_browser.skill.scripts.setup --mode local

# Remote AIO (Docker/K8s all-in-one)
python -m agent_browser.skill.scripts.setup --mode remote-aio \
  --api-url http://my-server:8000 --vnc-url http://my-server:6080

# Remote distributed
python -m agent_browser.skill.scripts.setup --mode remote-distributed \
  --api-url http://my-gateway:8000
```

Server admins can also generate a `skill.yaml` from a `DeployConfig` programmatically using `generate_skill_config()` in `agent_browser.deploy_config`.

### Chrome Extension (Optional)

For natural fingerprints and inherited login state, load the included Chrome extension:

```bash
# The extension ships inside the pip package at agent_browser/extension/
# Load it in Chrome: chrome://extensions/ -> Developer mode -> Load unpacked
# Select: <python-site-packages>/agent_browser/extension/
```

When the extension is connected, Agent Browser automatically uses **Extension mode** (your real Chrome browser) instead of launching a separate browser instance.

Click the extension toolbar icon to open the **popup status panel** showing connection state, current tab info, session stats, and troubleshooting commands.

### Functional API

```python
import asyncio
from agent_browser import create_session, open_page, snapshot, click, fill, evaluate

async def main():
    session_id = await create_session()
    await open_page(session_id, "https://example.com")
    data = await snapshot(session_id)

    await click(session_id, "@e0")
    await fill(session_id, "@e1", "hello world")
    title = await evaluate(session_id, "document.title")

asyncio.run(main())
```

### OOP Interface

```python
import asyncio
from agent_browser import AgentBrowser

async def main():
    async with AgentBrowser() as ab:
        await ab.create_session()
        await ab.open_page("https://example.com")
        snap = await ab.snapshot()
        await ab.click("@e0")

        # Agent mode with full configuration
        result = await ab.run_task(
            "Find the search box and type 'python'",
            intelligence="agent",
            agent_config={
                "enable_planning": True,
                "use_judge": True,
                "max_failures": 8,
                "loop_detection_enabled": True,
            },
        )
        print(result['status'])

asyncio.run(main())
```

### Server Mode (FastAPI)

```bash
pip install agent-browser[full]
uvicorn agent_browser.api:app --port 8000
curl http://localhost:8000/health
```

**REST API endpoints:**

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Server health + pool stats |
| POST | `/sessions/create` | Create session |
| GET | `/sessions/{id}` | Session status |
| DELETE | `/sessions/{id}` | Delete session |
| POST | `/navigate` | Navigate to URL |
| POST | `/snapshot` | DOM snapshot |
| POST | `/click` | Click element by ref |
| POST | `/fill` | Fill input field |
| POST | `/evaluate` | Execute JavaScript |
| POST | `/task` | Submit LLM/Agent task |

### Pipeline Mode

```python
from agent_browser.pipeline import PipelineExecutor

executor = PipelineExecutor(stealth_enabled=True)
result = await executor.run("adapters/my-site.yaml")
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

    # Generate adapter YAML automatically
    adapter_yaml = Synthesizer.synthesize(snapshot)
    print(adapter_yaml)

asyncio.run(main())
```

### CLI

```bash
agent-browser --help
```

## Public API Reference

### Core Operations

| Function | Description |
|----------|-------------|
| `create_session(**profile)` | Create browser session, returns UUID (accepts BrowserProfile params) |
| `open_page(sid, url)` | Navigate to URL |
| `snapshot(sid, interactive_only, iframe_selector)` | Get DOM snapshot with `@eN` element refs |
| `click(sid, ref_or_x, y)` | Click by element ref or viewport coordinates |
| `fill(sid, ref, text)` | Type text into input element |
| `scroll(sid, direction, amount)` | Scroll page |
| `press_key(sid, key)` | Press keyboard key |
| `wait_for_selector(sel, timeout)` | Wait for CSS selector |
| `go_back(sid)` | Navigate back |
| `evaluate(sid, expr)` | Execute JS, return result |
| `delete_session(sid)` | Release session resources |

### Search & Discovery

| Function | Description |
|----------|-------------|
| `search_page(sid, pattern, ...)` | Search page text (regex/plain) with context |
| `find_elements(sid, selector, ...)` | Find elements by CSS selector with metadata |
| `get_dropdown_options(sid, ref)` | Get options from a `<select>` element |
| `select_dropdown_option(sid, ref, text)` | Select option by visible text |

### File & Media

| Function | Description |
|----------|-------------|
| `upload_file(sid, ref, paths)` | Upload files to `<input type=file>` |
| `screenshot(sid, ref, ...)` | Screenshot (page or element, PNG/JPEG) |
| `save_as_pdf(sid, path, landscape)` | Save page as PDF |

### Advanced Interaction

| Function | Description |
|----------|-------------|
| `send_keys(sid, keys)` | Complex key sequences (modifiers + keys) |
| `scroll_to_text(sid, text)` | Scroll until text becomes visible |
| `open_tab(sid, url)` | Open new tab (optional navigate) |
| `switch_tab(sid, index)` | Switch to tab by index |
| `close_tab(sid, index)` | Close tab |

### Data Extraction

| Function | Description |
|----------|-------------|
| `extract_content(sid, selector, type)` | Extract text/html/links/images |
| `structured_output(sid, schema, prompt)` | Extract data via JSON schema validation |

### Agent Mode

| Function | Description |
|----------|-------------|
| `run_task(sid, task, intelligence, ..., agent_config)` | Autonomous Agent task with full config (24 tunable params via `AgentConfig`) |

### Configuration

| Function | Description |
|----------|-------------|
| `configure(**kwargs)` | Update config for next session |
| `reset()` | Clear all global state |
| `setup()` | Full first-session setup with validation |

## Architecture

```
agent_browser/
├── __init__.py      # Public API exports + __version__
├── main.py          # Facade API (create_session, snapshot, click, run_task, etc.)
├── client.py        # AgentBrowser OOP interface (session tracking, context manager)
├── config.py        # SkillConfig dataclass + mode detection
├── browser/         # Backend ABCs + implementations (local, remote, extension)
├── stealth/         # Anti-detection: middleware, enhancer, profiles, actions, patches
├── pipeline/        # YAML pipeline engine v2.3
├── explore/         # Site explorer + adapter synthesizer
├── adapters/        # Site adapter loader/runner/validator
├── intelligence/    # Agent task execution (browser-use integration)
├── session/         # Multi-user session management
├── cli/             # Command-line interface (Typer)
├── llm/             # LLM factory (OpenAI, Anthropic, GLM)
├── skill/           # Claude Code skill (SKILL.md, daemon, cli, doctor script)
└── utils/           # Shared utilities
```

Full architecture guide: see [CLAUDE.md](CLAUDE.md) for detailed design decisions, mode routing, and development standards.

## Examples

See [`examples/`](examples/) directory:

- [`examples/getting_started/`](examples/getting_started/) -- Basic search, snapshot exploration, agent tasks, site-specific examples (Zhihu, Bilibili, batch search)
- [`examples/advanced/`](examples/advanced/) -- Advanced usage patterns

## How It Compares to Raw browser-use

| Feature | browser-use | Agent Browser |
|---------|------------|-------------|
| AI agent automation | 50+ params | Full exposure (24 tunable via `AgentConfig`) |
| Anti-detection | No | 7-layer stack |
| Human behavior simulation | No | Bezier mouse, per-char typing |
| Circuit breaker | No | Per-session auto-degradation |
| YAML pipeline engine | No | 19-filter template engine |
| Error classification | No | 6-category typed errors |
| Auto-recovery | No | Per-error-category fallback |
| Site exploration | No | DOM analysis -> adapter synthesis |
| LLM Actions (14) | Built-in | Exposed as atomic API operations |
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

## Documentation

- [Architecture Guide](CLAUDE.md) -- Full system design, mode matrix, development standards
- [Contributing Guide](CONTRIBUTING.md) -- Development setup, code style, PR process
- [Security Policy](SECURITY.md) -- Vulnerability reporting, security best practices
- [Deployment Guide](deploy/README.md) -- Docker, Kubernetes, Helm deployment
- [Install Guide](docs/INSTALL.md) -- Platform-specific installation and K8s setup
- [Test Guide](docs/TEST_GUIDE.md) -- Test architecture, tiers, and running instructions
- [CHANGELOG](CHANGELOG.md) -- Version history

## Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for:

- Development environment setup
- Code style guidelines (ruff formatter/linter)
- Pull request process
- Test suite (868 tests across unit, integration, scenario, stealth, browser, skill, and e2e tests)

## License

Apache 2.0. See [LICENSE](LICENSE) for details.

## Acknowledgments

Built on top of excellent open-source projects:

- [browser-use](https://github.com/browser-use/browser-use) -- AI browser agent framework (MIT)
- [Playwright](https://github.com/microsoft/playwright) -- Reliable browser automation (Apache 2.0)
- [CloakBrowser](https://github.com/nickyc975/cloakbrowser) -- C++ anti-detection Chromium (MIT)
