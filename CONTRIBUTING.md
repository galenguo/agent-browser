# Contributing to Agent Browser

Thank you for contributing! This document covers development setup, code style, and the pull request process.

## Development Setup

### Prerequisites

- Python 3.11+
- pip or uv
- (Optional) CloakBrowser for full anti-detection testing: `pip install cloakbrowser==0.3.18`

### Install

```bash
# Clone the repo
git clone https://github.com/your-org/agent-browser.git
cd agent-browser

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install in editable mode with dev dependencies
pip install -e ".[dev]"

# Install Playwright browsers
playwright install chromium
```

### Running Tests

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/stealth/test_stealth_middleware.py -v

# Run with coverage
pytest --cov=agent_browser --cov-report=term-missing

# Run e2e tests (require running browser)
pytest tests/e2e/ -v
```

## Code Style

### Language

- **All source code, comments, and docstrings MUST be in English.**
- No non-ASCII characters in `.py` files outside of string literals and user-facing messages.
- Commit messages MUST be in English.

### Import Style

- Use absolute imports within the package: `from agent_browser.stealth.middleware import StealthMiddleware`
- Use relative imports for same-submodule references: `from .config import SkillConfig`
- Never use `sys.path.insert()` hacks
- Never use bare module imports that rely on `src/` being on `sys.path` (e.g., `from core.X import Y`)

### Type Hints

- All public functions and methods MUST have type hints
- Use `typing.Optional`, `typing.Dict`, `typing.List`, etc.
- Return types are required for all functions

### Documentation

- Public APIs MUST have docstrings (Google style or NumPy style)
- Docstrings should explain what the function does, not how
- Keep docstrings concise — one paragraph for simple functions

### Anti-Detection Sensitivity

**Do not break anti-detection features:**
- Do not modify CDP port 19222
- Do not remove CloakBrowser launch parameters
- Do not frequently attach/detach CDP sessions (use BrowserDaemon)
- Do not inject obvious automation markers
- Do not bypass StealthMiddleware

## Project Structure

```
agent_browser/           # Package root (all source code here)
├── browser/            # Backend ABCs + implementations
├── stealth/            # Anti-detection layer
├── pipeline/           # YAML pipeline engine
├── explore/            # Site explorer + adapter synthesis
├── adapters/           # Site adapter system
├── intelligence/       # Agent task execution
├── session/            # Session management
├── cli/                # CLI interface
└── utils/              # Shared utilities

tests/                  # Test suite (1000+ tests)
├── conftest.py         # Shared fixtures
├── unit/               # Unit tests (~31 files)
├── stealth/            # Anti-detection layer tests
├── browser/            # Browser backend tests
├── scenarios/          # Multi-step scenario tests (7 files)
├── skill/              # Skill facade, extension & deploy wizard tests
├── integration/        # Integration tests
└── e2e/                # End-to-end tests

adapters/               # Community-contributed site adapters (YAML)
examples/              # Example scripts
│   └── getting_started/  # Basic usage examples (6 files)
bin/                   # Dev/utility scripts (install, audit)
deploy/                # Unified deployment (docker, k8s, helm)
docs/                   # Architecture, install guide, test guide
```

## Making Changes

1. Create a branch from `main`: `git checkout -b your-feature-name`
2. Make your changes following the code style guidelines
3. Run tests to ensure nothing is broken: `pytest`
4. Commit with a clear message (English)
5. Push and create a pull request

## Pull Request Process

1. **Update tests if you change behavior** — new features need tests
2. **Update README.md if you change the public API**
3. **Ensure all CI checks pass** — lint, type check, and tests
4. **Link any related issues** in the PR description
5. **Keep PRs focused** — one feature or bugfix per PR when possible

## Adding New Features

### Adding a New Atomic Operation

1. Define interface in `agent_browser/browser/__init__.py` (BrowserPageHandle ABC)
2. Implement in `agent_browser/browser/local.py` (PlaywrightPageHandle)
3. Implement in `agent_browser/browser/remote.py` (RemotePageHandle)
4. Expose in `agent_browser/main.py` as a facade function
5. Export in `agent_browser/__init__.py`
6. Add tests

### Adding a New Pipeline Step

1. Implement in `agent_browser/pipeline/steps.py`
2. Register template in `agent_browser/pipeline/template.py` (if needed)
3. Validate in `agent_browser/adapters/validator.py`
4. Add error type in `agent_browser/pipeline/errors.py` (if needed)
5. Add classifier rule in `agent_browser/pipeline/classifier.py` (if needed)

### Adding a New Site Adapter

1. Create YAML file in `adapters/{site}/` directory
2. Follow the adapter schema (see existing examples)
3. Test with `agent_browser.adapters.run_adapter()`

## Reporting Bugs

When reporting bugs, please include:
- Python version
- OS version
- browser-use version
- Whether `[cloak]` extra is installed
- Full error traceback
- Steps to reproduce
- Expected vs actual behavior

## License

By contributing, you agree that your contributions will be licensed under Apache 2.0.
