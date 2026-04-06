# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-04-06

### Breaking Changes

- Package structure completely changed: old `skills.agent_browser` and `src` modules no longer exist
- All import paths changed from `from skills.agent_browser.X` / `from src.X` to `from agent_browser.X`
- `BrowserController` now requires `(browser_session, session_id)` args (was previously no-arg)
- Old CLI entry points removed; new entry point: `agent-browser` (Typer app)
- `docs/` directory is now gitignored (local only)
- Chinese comments/docs removed from codebase; all code is English-only

### Added

- **Standalone pip-installable package**: `pip install agent-browser` or `pip install agent-browser[cloak]` for full anti-detection
- **AgentBrowser OOP facade class**: `from agent_browser import AgentBrowser` with session tracking and async context manager support
- **LLMFactory module**: Unified LLM creation for OpenAI, Anthropic, GLM providers at `agent_browser.llm.factory`
- **CI/CD workflows**: ci.yml (3-version matrix), lint.yml (fast ruff), security.yml (pip-audit + bandit)
- **GitHub templates**: Bug report, feature request, PR template with checklists
- **Adapter contribution guide**: `adapters/README.md` with YAML schema, step types, examples
- **Multi-language READMEs**: README.zh-CN.md (Chinese), README.ja.md (Japanese)

### Migrated Components (47+ source files)

- **browser/**: LocalCDPBackend, RemoteAPIBackend, ExtensionBackend, BrowserDaemon, stealth_launcher
- **stealth/**: StealthMiddleware (Layer 7), StealthEnhancer (Layer 6), actions, patches, controller
- **pipeline/**: executor, steps, template, errors, classifier, fallback, debugger, telemetry (v2.3)
- **explore/**: site explorer, DOM analysis, cascade selectors, adapter synthesizer
- **adapters/**: YAML loader, runner, validator
- **intelligence/**: run_task router, browser-use Agent runner
- **session/**: pool manager, profile manager, session manager
- **cli/**: Typer-based CLI with commands
- **utils/**: refs_generator, action_tracer, persistent_session

### Removed

- All OpenCLI vendored code (`references/opencli/`)
- Old dual-layer architecture (`src/`, `skills/`)
- Legacy test scripts and benchmark files
- Chinese documentation from codebase
- Vestigial root `__init__.py`

### Fixed

- Critical silent import bug: `from core.stealth_enhancer import StealthEnhancer` would silently fail, disabling ALL anti-detection. Now correctly imports from `agent_browser.stealth.enhancer`
- Adapter directory path resolution (`parents[3]` -> `parents[2]`)
- Unicode arrow characters in synthesizer.py causing SyntaxError
- Unclosed f-string in synthesizer.py build_adapter function
- 33 test files updated with new import paths (789 tests collect cleanly)

### Dependencies

**Core:**
- browser-use>=0.12.0
- playwright>=1.40.0
- pydantic>=2.0
- PyYAML>=6.0
- structlog>=24.0
- aiohttp>=3.9.0

**Optional `[cloak]`:**
- cloakbrowser>=0.3.0
- patchright>=0.1.0

**Optional `[full]`:**
- langchain packages
- fastapi, uvicorn
- websockets
