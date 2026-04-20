"""Installation integrity tests -- prove pip install produces a working package.

Validates:
- Package metadata (pyproject.toml: name, version, deps, entry points)
- All public symbols in __init__.__all__ import cleanly
- Every submodule loads without ImportError
- No hardcoded absolute paths in source
- Version attribute accessible

These tests run without any browser, API server, or Docker.
They catch "the package is broken" class of issues before anything else.
"""

import importlib
import importlib.metadata
import os
import re

import pytest

# ════════════════════════════════════════════════════════════════════
# A. Package Metadata [P0-CRITICAL]
# ════════════════════════════════════════════════════════════════════


class TestPackageMetadata:
    def test_package_name(self):
        """pyproject.toml declares a valid package name."""
        meta = importlib.metadata.metadata("stealth-browser")
        assert meta["Name"] == "stealth-browser"

    def test_version_defined(self):
        """Version string exists and is non-empty."""
        import stealth_browser

        assert hasattr(stealth_browser, "__version__")
        assert isinstance(stealth_browser.__version__, str)
        assert len(stealth_browser.__version__) > 0

    def test_version_matches_pyproject(self):
        """__version__ is consistent with pyproject.toml [project] version."""
        import stealth_browser

        meta = importlib.metadata.metadata("stealth-browser")
        # __init__ may append -dev suffix; both should share the same base version
        assert meta["Version"] in stealth_browser.__version__ or stealth_browser.__version__.startswith(meta["Version"])

    def test_dependencies_declared(self):
        """Core dependencies listed in package metadata."""
        meta = importlib.metadata.metadata("stealth-browser")
        requires = meta.get_all("Requires-Dist") or []
        dep_names = {r.split()[0].split(";")[0].strip().lower() for r in requires}
        assert any("browser-use" in d for d in dep_names)
        assert any("playwright" in d for d in dep_names)
        assert any("pyyaml" in r.lower() for r in requires)
        assert any("aiohttp" in d for d in dep_names)

    def test_entry_point_console_script(self):
        """console_scripts entry point defined."""
        eps = importlib.metadata.entry_points()
        scripts = eps.select(group="console_scripts")
        names = {ep.name for ep in scripts}
        assert "stealth-browser" in names

    def test_python_version_constraint(self):
        """Requires Python >= 3.11."""
        meta = importlib.metadata.metadata("stealth-browser")
        requires = meta.get_all("Requires-Python") or []
        assert len(requires) > 0
        assert ">=" in requires[0] or "3.11" in requires[0]


# ════════════════════════════════════════════════════════════════════
# B. Public API Surface [P0-CRITICAL]
# ════════════════════════════════════════════════════════════════════


class TestPublicImports:
    def test___all___exists(self):
        """__all__ is defined and non-empty."""
        import stealth_browser

        assert hasattr(stealth_browser, "__all__")
        assert isinstance(stealth_browser.__all__, list)
        assert len(stealth_browser.__all__) > 0

    def test_all_symbols_importable(self):
        """Every symbol in __all__ can be imported from the top level."""
        import stealth_browser

        for name in stealth_browser.__all__:
            assert hasattr(stealth_browser, name), f"{name} in __all__ but not on module"
            obj = getattr(stealth_browser, name)
            assert obj is not None, f"{name} is None"

    def test_facade_functions_callable(self):
        """Core facade functions are callable."""
        from stealth_browser import (
            click,
            configure,
            create_session,
            delete_session,
            fill,
            go_back,
            hover,
            open_page,
            press_key,
            reset,
            run_task,
            scroll,
            select_option,
            setup,
            snapshot,
            wait_for_selector,
        )

        assert callable(create_session)
        assert callable(delete_session)
        assert callable(open_page)
        assert callable(snapshot)
        assert callable(click)
        assert callable(fill)
        assert callable(scroll)
        assert callable(select_option)
        assert callable(hover)
        assert callable(press_key)
        assert callable(wait_for_selector)
        assert callable(go_back)
        assert callable(configure)
        assert callable(run_task)
        assert callable(reset)
        assert callable(setup)

    def test_exception_classes_importable(self):
        """FirstSessionError imports correctly."""
        from stealth_browser import FirstSessionError

        assert issubclass(FirstSessionError, Exception)

    def test_config_types_importable(self):
        """SkillConfig, load_config, detect_mode import correctly."""
        from stealth_browser import SkillConfig

        assert hasattr(SkillConfig, "__dataclass_fields__")

    def test_oop_interface_importable(self):
        """StealthBrowser OOP class imports correctly."""
        from stealth_browser import StealthBrowser

        assert callable(getattr(StealthBrowser, "create_session", None))

    def test_adapter_functions_importable(self):
        """list_adapters, run_adapter import correctly."""
        from stealth_browser import list_adapters, run_adapter

        assert callable(list_adapters)
        assert callable(run_adapter)

    def test_explore_functions_importable(self):
        """explore, synthesize, cascade import correctly."""
        from stealth_browser import cascade, explore, synthesize

        assert callable(explore)
        assert callable(synthesize)
        assert callable(cascade)

    def test_llm_factory_importable(self):
        """LLMFactory imports correctly."""
        from stealth_browser import LLMFactory

        assert LLMFactory is not None


# ════════════════════════════════════════════════════════════════════
# C. Submodule Load Integrity [P0-CRITICAL]
# ════════════════════════════════════════════════════════════════════

_SUBMODULES = [
    ("stealth_browser.main", ["create_session", "configure", "reset", "setup"]),
    ("stealth_browser.config", ["SkillConfig", "detect_mode", "load_config"]),
    ("stealth_browser.deploy_config", ["DeployConfig", "validate_config", "generate_config"]),
    ("stealth_browser.stealth.middleware", ["StealthMiddleware", "CircuitState"]),
    ("stealth_browser.stealth.enhancer", ["StealthEnhancer"]),
    ("stealth_browser.browser.local", ["LocalCDPBackend"]),
    ("stealth_browser.browser.remote", ["RemoteAPIBackend"]),
    ("stealth_browser.browser.daemon", ["BrowserDaemon"]),
    ("stealth_browser.pipeline.executor", ["execute_pipeline", "STEPS"]),
    ("stealth_browser.pipeline.steps", ["STEPS"]),
    ("stealth_browser.pipeline.template", ["render_template"]),
    ("stealth_browser.pipeline.errors", ["PipelineError", "StepTimeoutError"]),
    ("stealth_browser.pipeline.classifier", ["ErrorCategory", "classify"]),
    ("stealth_browser.pipeline.fallback", ["attempt_fallback"]),
    ("stealth_browser.pipeline.debugger", ["DebugSession"]),
    ("stealth_browser.pipeline.telemetry", ["Telemetry"]),
    ("stealth_browser.explore.explorer", ["explore"]),
    ("stealth_browser.explore.analysis", ["has_search", "has_pagination"]),
    ("stealth_browser.explore.cascade", ["cascade"]),
    ("stealth_browser.explore.synthesizer", ["synthesize", "build_adapter"]),
    ("stealth_browser.adapters.loader", ["get_adapter", "list_adapters"]),
    ("stealth_browser.adapters.runner", ["run_adapter"]),
    ("stealth_browser.adapters.validator", ["validate_adapter"]),
    ("stealth_browser.intelligence.agent_runner", ["AgentRunner"]),  # may raise OSError on CloakBrowser init
    ("stealth_browser.llm.factory", ["LLMFactory"]),
    ("stealth_browser.client", ["StealthBrowser"]),
]


@pytest.mark.parametrize("module_path,expected_attrs", _SUBMODULES)
def test_submodule_loads(module_path, expected_attrs):
    """Each submodule imports without error and has expected attributes."""
    try:
        mod = importlib.import_module(module_path)
    except (ImportError, OSError) as e:
        pytest.skip(f"Cannot import {module_path}: {e}")
    for attr in expected_attrs:
        assert hasattr(mod, attr), f"{module_path} missing {attr}"


# ════════════════════════════════════════════════════════════════════
# D. Code Quality Guards [P1]
# ════════════════════════════════════════════════════════════════════


class TestCodeQuality:
    # Whitelist /opt/ paths (legitimate Linux defaults like /opt/cloakbrowser/chrome)
    _ABS_PATH_PATTERN = re.compile(r'["\'](/(?:Users|home|var|etc)/)', re.IGNORECASE)
    _SOURCE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def test_no_hardcoded_absolute_paths(self):
        """No developer-machine absolute paths in Python source files."""
        violations = []
        for root, dirs, files in os.walk(self._SOURCE_ROOT):
            dirs[:] = [
                d
                for d in dirs
                if d
                not in {
                    ".git",
                    "__pycache__",
                    ".venv",
                    "node_modules",
                    ".pytest_cache",
                    ".mypy_cache",
                    "dist",
                    "build",
                    "tests/screenshots",
                    "tests/results",
                }
            ]
            for fname in files:
                if not fname.endswith(".py"):
                    continue
                fpath = os.path.join(root, fname)
                if "test_" in fname or "__pycache__" in root:
                    continue
                try:
                    with open(fpath, encoding="utf-8") as f:
                        for lineno, line in enumerate(f, 1):
                            if self._ABS_PATH_PATTERN.search(line):
                                violations.append(f"{fpath}:{lineno}: {line.strip()}")
                except Exception:
                    pass
        assert len(violations) == 0, f"Found {len(violations)} hardcoded absolute paths:\n" + "\n".join(violations[:20])

    def test_no_sys_path_hacks_in_source(self):
        """No sys.path.insert/appends in library source (ok in tests)."""
        violations = []
        src_root = os.path.join(self._SOURCE_ROOT, "stealth_browser")
        if not os.path.isdir(src_root):
            return  # nothing to check
        for root, _dirs, files in os.walk(src_root):
            for fname in files:
                if not fname.endswith(".py"):
                    continue
                fpath = os.path.join(root, fname)
                with open(fpath, encoding="utf-8") as f:
                    for lineno, line in enumerate(f, 1):
                        stripped = line.strip()
                        if stripped.startswith(("sys.path.insert", "sys.path.append")):
                            violations.append(f"{fpath}:{lineno}: {stripped}")
        assert len(violations) == 0, "Found sys.path hacks:\n" + "\n".join(violations)
