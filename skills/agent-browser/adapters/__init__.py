"""适配器系统 — YAML 声明式站点操作"""
from .loader import load_adapters, list_adapters, get_adapter
from .runner import run_adapter

__all__ = ["load_adapters", "list_adapters", "get_adapter", "run_adapter"]
