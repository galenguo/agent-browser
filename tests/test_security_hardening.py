"""
Security Hardening unit tests.

NOTE: These tests cover FastAPI api.py security features (JS sandbox, URL validation,
IDOR prevention, constant-time comparison). The FastAPI server module has not yet
been migrated to agent_browser/ package. These tests will be re-enabled once
the API server is added.
"""
import pytest

# FastAPI server (api.py) is an optional component not yet migrated.
# These tests are skipped until the API server module is added to agent_browser/.
pytest.skip(
    "FastAPI api module not yet migrated to agent_browser/ package",
    allow_module_level=True,
)
