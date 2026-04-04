"""
StealthEnhancer — 反侦察增强器（向后兼容重导出，实际实现在 core/）

DEPRECATED: 新代码应直接从 core.stealth_enhancer 导入。
"""
import sys
import warnings
from pathlib import Path

# 确保 src/ 在导入路径中（skill 层导入时需要）
_src = str(Path(__file__).resolve().parent.parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

warnings.warn(
    "Importing from skills.agent_browser.stealth is DEPRECATED. "
    "Use 'from core.stealth_enhancer import StealthEnhancer' instead.",
    DeprecationWarning,
    stacklevel=2,
)

from core.stealth_enhancer import StealthEnhancer  # noqa: F401

__all__ = ["StealthEnhancer"]
