"""
API Key authentication + session ownership tests.

NOTE: These tests cover FastAPI api.py auth features (API key enforcement,
session ownership, multi-tenant isolation). The FastAPI server module has
not yet been migrated to stealth_browser/ package. These tests will be
re-enabled once the API server is added.
"""

import pytest

# FastAPI server (api.py) is an optional component not yet migrated.
# These tests are skipped until the API server module is added to stealth_browser/.
pytest.skip(
    "FastAPI api module not yet migrated to stealth_browser/ package",
    allow_module_level=True,
)
