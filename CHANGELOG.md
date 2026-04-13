# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **AgentConfig model** (`models.py`): 24-field Pydantic model for full browser-use Agent parameter exposure. Covers planning (`enable_planning`, `planning_replan_on_stall`, `planning_exploration_limit`), judge validation (`use_judge`), thinking mode (`use_thinking`), message compaction (`message_compaction`), reliability (`max_failures`, `final_response_after_failure`, `loop_detection_enabled`, `loop_detection_window`), timeouts (`llm_timeout`, `step_timeout`), vision (`use_vision`, `vision_detail_level`), flash mode (`flash_mode`), system prompts (`override_system_message`, `extend_system_message`), structured output (`extraction_schema`), fallback LLM (`fallback_llm_model`), recording (`generate_gif`, `save_conversation_path`), cost tracking (`calculate_cost`), skills ecosystem (`skill_ids`), and security (`sensitive_data`). All fields have sensible defaults matching browser-use 0.12.2.
- **14 new LLM-mode Actions**: Full browser-use Action coverage for step-by-step automation: `search_page` (regex/plain text search with context), `find_elements` (CSS selector with metadata), `get_dropdown_options` / `select_dropdown_option` (dropdown handling), `upload_file` (file upload), `screenshot` (page/element, PNG/JPEG), `save_as_pdf` (PDF export), `send_keys` (complex key sequences with modifiers), `scroll_to_text` (scroll-until-visible), tab management (`open_tab`, `switch_tab`, `close_tab`, `get_tabs_info`), `extract_content` (text/html/links/images extraction), and `structured_output` (JSON schema validation).
- **BrowserProfile configuration models** (`models.py`): `ProxySettingsModel`, `ViewportSettingsModel`, `WatchdogConfigModel`, and `SessionProfileConfig` -- typed config for session creation (viewport, proxy, user agent, headless, domains, extensions, device scale, watchdog toggles).
- **`agent_config` parameter across the stack**: `TaskSubmitRequest` (FastAPI app.py), `pool_manager.submit_task()` with `_build_agent_kwargs()` static method that maps valid Agent() constructor params (excluding pool-level fields like `fallback_llm_model`), and `SkillBrowser.run_task()` (browser_cli.py). Backward compatible -- all new params optional with defaults.
- **SKILL.md Agent Mode section**: Complete rewrite with basic usage, full AgentConfig example (24 params), comprehensive parameter table (22 rows), and 3 common config patterns (PROD_CONFIG, FAST_CONFIG, VISION_CONFIG).
- **api-reference.md AgentConfig section**: New reference documentation with full field listing, type defaults, descriptions, and quick-reference config patterns.

### Fixed
- **pytest stdin capture** (`test_anti_detection.py`): Guarded `input()` call with `os.getenv("PYTEST_CURRENT_TEST")` check so the anti-detection test runs cleanly under pytest without conflicting with stdout/stdin capture.

### Added (previous unreleased)
- **Skill config file separation**: client-side config now lives in `~/.agent-browser/skill.yaml` (flat YAML keys, no namespace) separate from server-side `~/.agent-browser/config.yaml`. `load_config()` reads `skill.yaml`; `load_deploy_config()` continues to read `config.yaml`.
- **`remote_type` field** (`SkillConfig`): `"aio"` or `"distributed"` -- only meaningful when `browser_mode="remote"`. Controls whether a single VNC endpoint or per-session endpoints are used. Env var: `AGENT_BROWSER_REMOTE_TYPE`.
- **`vnc_url` field** (`SkillConfig`): noVNC endpoint for AIO remote deployments. Empty for distributed (per-session URLs). Env var: `AGENT_BROWSER_VNC_URL`.
- **`generate_skill_config()`** (`deploy_config.py`): generates `~/.agent-browser/skill.yaml` from a `DeployConfig`. Maps all 5 deployment modes (local, docker-aio, docker-distributed, k8s-aio, k8s-distributed) to correct `SkillConfig` fields. Used by server admins to produce a shareable client config.
- **`session.py` script** (`agent_browser/skill/scripts/session.py`): unified session lifecycle entry point for the Claude Code skill. `check_config()` returns a structured guidance dict when `skill.yaml` is absent -- no blocking `input()`. Exposes `create()`, `open_page()`, `snapshot()`, `click()`, `fill()`, `scroll()`, `run_task()`, `delete()` as thin async wrappers.
- **`setup.py` script** (`agent_browser/skill/scripts/setup.py`): writes `~/.agent-browser/skill.yaml` from user-provided mode + params. Supports modes `local`, `remote-aio`, `remote-distributed`. Callable as CLI (`python -m agent_browser.skill.scripts.setup --mode ...`) or programmatically.
- **Remote mode doctor checks** (`doctor.py`): Check 5 (CDP) now skips with `status=skip` when `browser_mode=remote`. New Check 5b verifies remote API health at `config.api_url/health`. New Check 5c checks VNC URL reachability when `vnc_url` is set.

### Changed
- **`from_deploy_config()`** (`config.py`): full mode mapping table covering all 5 modes. `local` mode now correctly sets `api_url` from `DeployConfig.api_port` (previously left at default, causing `test_api_port_creates_api_url` to fail).
- **`SKILL.md` Quick Start**: updated to show `setup.py` commands for all 3 modes (`local`, `remote-aio`, `remote-distributed`). Session operations table now points to `session.py` script.
- **`_apply_yaml_overrides()`** (`config.py`): reads `remote_type` and `vnc_url` from flat YAML keys in `skill.yaml`.
- **`_apply_env_overrides()`** (`config.py`): applies `AGENT_BROWSER_REMOTE_TYPE` and `AGENT_BROWSER_VNC_URL`.

## [0.2.0] - 2026-04-07

### Added
- **Chrome Extension popup UI** (`extension/popup.html` + `popup.js`): Dark theme status panel (280x380px) showing connection state, current tab info, session stats, and troubleshoot section with copy-paste fix commands
- **Extension getStatus protocol**: background.js `chrome.runtime.onMessage` handler for popup status queries with auto-refresh every 2s
- **SKILL.md rewrite** (`agent_browser/skill/SKILL.md`, ~435 lines): Conforms to Claude Code skill spec with bilingual triggers (Chinese + English), ARGUMENTS/Execution Environment blockquotes, doctor.py Quick Start checklist, Extension Mode docs, conversational error recovery with IF/THEN decision tree, and progressive disclosure via references/
- **Reference docs** (`agent_browser/skill/references/`): adapter-guide.md for site adapters/explore pipeline; react-workflow.md, error-recovery.md, api-reference.md ported from canonical
- **Environment diagnostic** (`agent_browser/skill/scripts/doctor.py`): 7-check diagnosis (Python version, package, Playwright, CloakBrowser, CDP endpoint, LLM API key, websockets) with auto-fix capability and structured DoctorReport output
- **install-skill CLI command** (`agent-browser install-skill`): Copies SKILL.md + references + scripts to `~/.claude/skills/agent-browser/` for Claude Code discovery; supports `--path` and `--force` flags
- **91 tests** across 12 test classes in `tests/skill/test_skill_extension.py`: SKILL.md conformance (21), Extension popup (8), manifest (9), background.js (13), snapshot.js (8), doctor script (6), install-skill (5), config extension field (2), pyproject package data (6), reference docs (6), backend snapshot (2)

### Changed
- **ExtensionBackend.snapshot()**: New method on ExtensionBackend that routes snapshot commands through the page handle or bridge (previously missing, would crash with AttributeError)
- **SkillConfig.extension_enabled**: New field (default True) with env var (`AGENT_BROWSER_EXTENSION_ENABLED`) and YAML override support
- **Extension tools list**: Added `select_option` to LLM-mode tool list for Extension backend
- **manifest.json**: Added `default_popup: "popup.html"` so toolbar icon opens the status panel
- **DoctorReport.ready semantics**: Now requires both zero failures AND zero warnings (previously returned True with 7 warnings)
- **pyproject.toml package_data**: Added popup files (popup.html, popup.js) and reference docs to packaged data

### Fixed
- **pendingCommands variable shadowing** (background.js): `let pendingCommands = 0` shadowed the `const pendingCommands = Map()`, causing rejectAllPending() TypeError and always-zero command stats in popup. Renamed counter to `commandCount`
- **auto_fix() tally corruption** (doctor.py): Double-decremented both warned AND failed counters regardless of original check status, producing negative tallies. Now saves original status before overwrite
- **install_skill partial install** (cli/main.py): File operations now wrapped in try/except to prevent partial installs on failure (e.g., PermissionError midway through copytree)
- **JS injection in debugger ops** (background.js): All selector/value interpolation now uses jsEscape()/jsEscapeSelector() helpers with JSON.stringify+parse pattern for values, preventing arbitrary code execution via malicious LLM output
- **ensureDebuggerAttached() race condition** (background.js): Added attach mutex (_attaching promise) so concurrent commands queue instead of triggering duplicate chrome.debugger.attach() calls

- **SECURITY.md**: Vulnerability reporting policy, supported versions, security best practices for API keys, browser profiles, and CDP ports
- **CODE_OF_CONDUCT.md**: Contributor Covenant v2.1 for community governance

### Changed

- **Project restructure**: Consolidated deployment configs (`docker/` + `k8s/` + `helm/` -> `deploy/`), renamed `scripts/` -> `bin/`, organized 55 flat tests into `unit/`, `stealth/`, `browser/`, `scenarios/`, `skill/` subdirectories (868 tests, all discoverable)
- **Removed dead files**: 14 stale scripts/tests/docs deleted (30MB Chrome profile data, one-off benchmark scripts, redundant requirements.txt)
- **README.md rewritten**: Badge line (Python/license/PyPI/CI), quickstart-first structure, feature grid, mode matrix table, comparison with browser-use
- **Updated .gitignore**: Removed stale rules for moved directories, added runtime data exclusions
- **All documentation**: Fixed stale path references across INSTALL.md, TEST_GUIDE.md, ARCHITECTURE.md, deploy/README.md, AUTORESEARCH.md

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

- **868 total tests collected** across 9 test subdirectories (unit/stealth/browser/scenarios/skill/integration/e2e)
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
