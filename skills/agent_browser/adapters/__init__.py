"""适配器系统 — YAML 声明式站点操作"""
from .loader import list_adapters, get_adapter
from .runner import run_adapter

__all__ = ["list_adapters", "get_adapter", "run_adapter"]
