"""
StealthEnhancer — 反侦察增强器（re-export from src.core）

统一入口：无论从 skill 层还是 src/ 层导入，都指向同一个实现。
"""
import sys
from pathlib import Path

# 确保 src/ 在导入路径中（skill 层导入时需要）
_src = str(Path(__file__).resolve().parent.parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from core.stealth_enhancer import StealthEnhancer  # noqa: F401

__all__ = ["StealthEnhancer"]
