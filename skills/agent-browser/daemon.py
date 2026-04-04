"""BrowserDaemon — 向后兼容重导出（实际实现在 src/browser/daemon.py）

DEPRECATED: 新代码应直接从 src.browser.daemon 导入。
"""
import sys
from pathlib import Path

_src = str(Path(__file__).resolve().parent.parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from src.browser.daemon import BrowserDaemon  # noqa: F401

__all__ = ["BrowserDaemon"]
