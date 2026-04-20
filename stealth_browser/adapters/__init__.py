"""Site adapter system.

Loads, validates, and runs YAML site adapters.
"""

from .loader import get_adapter, list_adapters
from .runner import run_adapter
from .validator import validate_adapter

__all__ = ["get_adapter", "list_adapters", "run_adapter", "validate_adapter"]
