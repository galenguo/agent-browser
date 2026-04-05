"""Adapter YAML 结构验证器 — 纯 dict 检查，零外部依赖。

使用实际 STEPS registry 作为 step 名称的唯一数据源（不会 drift）。
在 loader.py 的 _ensure_loaded() 中调用，实现加载时校验。
"""
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# 已知合法 strategy 值（含 OpenCLI 别名）
VALID_STRATEGIES = {"public", "cookie", "intercept", "ui", "store-action", "header"}
VALID_ARG_TYPES = {"str", "int", "float", "bool"}


def validate_adapter(adapter: Dict[str, Any]) -> List[str]:
    """
    验证 adapter dict 结构完整性。

    Returns:
        错误列表（空列表 = 通过）。

    Checks:
        1. 必填字段: site, name, pipeline
        2. pipeline 是非空 list
        3. 每个 pipeline step 有已知 op 名
        4. strategy 值合法
        5. args 类型标注合法
    """
    errors: List[str] = []

    if not adapter or not isinstance(adapter, dict):
        errors.append("Adapter is empty or not a dict")
        return errors

    # 1. 必填字段
    for field in ("site", "name", "pipeline"):
        if field not in adapter:
            errors.append(f"Missing required field: {field}")

    # 2. pipeline 结构
    pipeline = adapter.get("pipeline")
    if not isinstance(pipeline, list):
        errors.append("pipeline must be a list")
    elif len(pipeline) == 0:
        errors.append("pipeline must not be empty")
    else:
        # 延迟导入避免循环依赖
        from skills.agent_browser.pipeline.steps import STEPS
        for i, step in enumerate(pipeline):
            if not isinstance(step, dict) or len(step) != 1:
                errors.append(f"pipeline[{i}]: invalid step format (expected {{op: params}})")
            else:
                op = list(step.keys())[0]
                if op not in STEPS:
                    errors.append(f"pipeline[{i}]: unknown step '{op}'")

    # 3. strategy 校验（intercept 是 cookie 的 OpenCLI 别名，两者都接受）
    strategy = adapter.get("strategy", "")
    if strategy and strategy not in VALID_STRATEGIES:
        errors.append(
            f"Invalid strategy: '{strategy}'. "
            f"Must be one of {sorted(VALID_STRATEGIES)}"
        )

    # 4. args 类型校验
    args = adapter.get("args", {})
    if isinstance(args, dict):
        for arg_name, arg_spec in args.items():
            if isinstance(arg_spec, dict):
                arg_type = arg_spec.get("type", "")
                if arg_type and arg_type not in VALID_ARG_TYPES:
                    errors.append(
                        f"args.{arg_name}: invalid type '{arg_type}'. "
                        f"Must be one of {sorted(VALID_ARG_TYPES)}"
                    )

    # 5. browser 一致性检查（browser:false 不应有 navigate 步骤）
    browser = adapter.get("browser", True)
    if browser is False and isinstance(pipeline, list):
        nav_ops = [list(s.keys())[0] for s in pipeline if isinstance(s, dict) and len(s) == 1]
        if "navigate" in nav_ops:
            errors.append(
                "browser=false but pipeline contains 'navigate' step (contradiction)"
            )

    return errors


def validate_all_adapters() -> Dict[str, List[str]]:
    """批量验证所有已加载的 adapter。返回 {adapter_key: errors} dict。"""
    from .loader import list_adapters

    # 触发加载
    adapters = list_adapters()
    results: Dict[str, List[str]] = {}

    for adapter_meta in adapters:
        key = f"{adapter_meta['site']}/{adapter_meta['name']}"
        from .loader import get_adapter
        adapter = get_adapter(adapter_meta["site"], adapter_meta["name"])
        if adapter:
            results[key] = validate_adapter(adapter)
        else:
            results[key] = ["Adapter not found in registry"]

    return results
