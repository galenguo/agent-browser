"""后端抽象 — 向后兼容重导出（实际实现在 src/browser/backends/）

DEPRECATED: 新代码应直接从 src.browser.backends 导入。
"""
import sys
from pathlib import Path

# 确保 src/ 在导入路径中
_src = str(Path(__file__).resolve().parent.parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from src.browser.backends import BrowserBackend, BrowserPageHandle  # noqa: F401

__all__ = ["BrowserBackend", "BrowserPageHandle"]
