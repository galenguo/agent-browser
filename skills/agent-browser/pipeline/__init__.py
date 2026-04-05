"""Pipeline 引擎 — YAML 适配器的声明式执行

16 built-in steps:
  Browser: navigate, click, type, wait, press, snapshot, evaluate,
           intercept, tap, download
  Data:    fetch, select, map, filter, sort, limit

Template engine: ${{ }} syntax with pipe filters
  ${{ args.keyword }}        — Variable access
  ${{ item.title | upper }} — Pipe filter
  ${{ index + 1 }}          — Arithmetic

Usage:
    from skills.agent_browser.pipeline import execute_pipeline, list_registered_steps

    result = await execute_pipeline(
        steps=[{"navigate": "https://example.com"}, {"evaluate": "document.title"}],
        session_id=sid,
        args={"query": "test"},
    )
"""
from .executor import execute_pipeline, list_registered_steps, PipelineResult
from .template import TemplateContext, render_template, resolve
from .steps import STEPS, register

__all__ = [
    "execute_pipeline",
    "list_registered_steps",
    "PipelineResult",
    "TemplateContext",
    "render_template",
    "resolve",
    "STEPS",
    "register",
]
