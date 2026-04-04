"""RemoteAPIBackend — 向后兼容重导出（实际实现在 src/browser/backends/remote.py）

DEPRECATED: 新代码应直接从 src.browser.backends.remote 导入。
"""
import sys
from pathlib import Path

_src = str(Path(__file__).resolve().parent.parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from src.browser.backends.remote import RemoteAPIBackend, RemotePageHandle  # noqa: F401

__all__ = ["RemoteAPIBackend", "RemotePageHandle"]
