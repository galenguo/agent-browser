"""Pipeline 引擎 — YAML 适配器的声明式执行

16 built-in steps:
  Browser: navigate, click, type, wait, press, snapshot, evaluate,
           intercept, tap, download
  Data:    fetch, select, map, filter, sort, limit

Template engine: ${{ }} syntax with pipe filters
  ${{ args.keyword }}        — Variable access
  ${{ item.title | upper }} — Pipe filter
  ${{ index + 1 }}          — Arithmetic

Error handling (v2.2):
  PipelineError hierarchy with step context, fix hints, HTTP 502 handler

Intelligence (v2.3):
  Error classification, agent fallback recovery, debugger, local telemetry

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

# v2.2: Typed error hierarchy
from .errors import (
    PipelineError,
    AdapterLoadError,
    AdapterValidationError,
    PipelineStepError,
    StepTimeoutError,
    SelectorNotFoundError,
    URLError,
    _generate_fix_hint,
)

# v2.3: Intelligence modules
from .classifier import ErrorCategory, classify, category_description
from .fallback import attempt_fallback, _FALLBACK_HANDLER_NAMES
from .debugger import DebugSession, debug_pipeline, _summarize
from .telemetry import Telemetry

__all__ = [
    # Core executor
    "execute_pipeline",
    "list_registered_steps",
    "PipelineResult",
    # Template engine
    "TemplateContext",
    "render_template",
    "resolve",
    # Step registry
    "STEPS",
    "register",
    # Errors (v2.2)
    "PipelineError",
    "AdapterLoadError",
    "AdapterValidationError",
    "PipelineStepError",
    "StepTimeoutError",
    "SelectorNotFoundError",
    "URLError",
    "_generate_fix_hint",
    # Classifier (v2.3)
    "ErrorCategory",
    "classify",
    "category_description",
    # Fallback (v2.3)
    "attempt_fallback",
    "_FALLBACK_HANDLER_NAMES",
    # Debugger (v2.3)
    "DebugSession",
    "debug_pipeline",
    "_summarize",
    # Telemetry (v2.3)
    "Telemetry",
]
