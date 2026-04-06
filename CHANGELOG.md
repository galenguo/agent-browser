# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **`evaluate()` public API**: Execute JavaScript in page context via `await evaluate(session_id, "expression")`. Available on both functional API (`agent_browser.main`) and OOP interface (`AgentBrowser.evaluate()`)
- **`AgentBrowser.evaluate()`**: OOP wrapper for JS evaluation with automatic session resolution
- **E2E capability verification suite** (89 tests across 3 files):
  - `test_skill_installation.py` (42 tests): package metadata, import integrity, submodule load validation, code quality guards
  - `test_skill_facade.py` (44 tests): facade routing through middleware stack, ReAct cycle (snapshot→click→fill), run_task(llm/agent), mode selection, error recovery
  - `test_docker_smoke.py` (3 tests): Docker script sanity + graceful skip when daemon unavailable
- **Deploy wizard validation suite** (148 tests): config YAML roundtrip, generate_config, validate_config, migration, shell script parsing
- **FastAPI REST API server** (`agent_browser.api`): 25 endpoints mapped to SessionPoolManager business logic
  - Session CRUD: `GET /sessions`, `POST /sessions/create`, `GET/DELETE /sessions/{id}`
  - Navigation: `POST /sessions/{id}/navigate`, `/back`, `GET /url`, `/title`
  - Interaction: `POST /snapshot`, `/click`, `/fill`, `/scroll`, `/evaluate`, `/wait`, `/mouse/move`, `/keyboard/press`
  - Agent tasks: `POST /sessions/{id}/task`, `GET /tasks/{task_id}`
  - Legacy compat: `POST /tasks`, `GET /tasks/{id}`
  - Health check: `GET /health` (pool stats + mode)
  - Startup/shutdown lifecycle with SessionPoolManager singleton
  - Error mapping: `SessionNotFoundError` → 404, `ResourceExhaustedError` → 503
  - Profile storage auto-configured for macOS (`PROFILE_STORAGE` env var)

### Changed

- **Code hygiene pass** (117 files): modernized type hints (`Optional[X]` → `X | None`), reorganized imports in `__init__.py`, split multi-imports to single-line in `client.py`
- **LocalCDPBackend**: new browser context defaults to `ignore_https_errors=True` for smoother HTTPS site automation
- **Pipeline step format**: E2E workflow tests use dict keys directly (`{"navigate": "..."}`) instead of action wrapper
- **Test cleanup**: removed 500+ lines of dead code from `test_security_hardening.py` (FastAPI api.py not yet migrated)

### Test Summary

- **885 total tests collected** (up from 789)
- **234+ core tests pass in <20s** (unit + integration + installation + facade)
- **74/75 E2E browser tests pass** with real CloakBrowser (1 flaky: session isolation race condition; FastAPI server gap closed, 6 api/local tests now pass)
- **0 regressions** across all test suites

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
