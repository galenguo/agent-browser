"""适配器运行器 — 查找适配器 → 创建会话 → 执行 pipeline → 返回结果"""
import logging
from typing import Any, Dict, List, Optional

from .loader import get_adapter, load_adapters
from ..pipeline.executor import execute_pipeline

logger = logging.getLogger(__name__)


async def run_adapter(
    site: str,
    command: str,
    session_id: Optional[str] = None,
    cdp_url: str = "http://127.0.0.1:19222",
    **kwargs: Any,
) -> List[dict]:
    """
    执行站点适配器命令（确定性，零 LLM 成本）。

    Args:
        site: 站点名（如 "baidu"）
        command: 命令名（如 "search"）
        session_id: 已有会话 ID（可选，不传则自动创建）
        cdp_url: CDP 连接地址
        **kwargs: 适配器参数

    Returns:
        提取的数据列表
    """
    # 确保 adapters 已加载
    load_adapters()

    adapter = get_adapter(site, command)
    if not adapter:
        raise ValueError(f"Adapter not found: {site}/{command}")

    # 验证必需参数
    args_spec = adapter.get("args", {})
    for arg_name, arg_spec in args_spec.items():
        if arg_spec.get("required") and arg_name not in kwargs:
            # 使用默认值
            if "default" in arg_spec:
                kwargs[arg_name] = arg_spec["default"]
            else:
                raise ValueError(f"Missing required arg: {arg_name}")

    # 填充默认值
    for arg_name, arg_spec in args_spec.items():
        if arg_name not in kwargs and "default" in arg_spec:
            kwargs[arg_name] = arg_spec["default"]

    # 管理会话
    own_session = False
    if not session_id:
        from ..main import create_session, delete_session
        session_id = await create_session(cdp_url)
        own_session = True

    try:
        # 隐匿性配置
        stealth = adapter.get("stealth", {})

        # 执行 pipeline
        pipeline = adapter.get("pipeline", [])
        result = await execute_pipeline(
            steps=pipeline,
            session_id=session_id,
            args=kwargs,
            stealth_config=stealth,
        )

        return result if isinstance(result, list) else [result] if result else []

    finally:
        if own_session:
            try:
                from ..main import delete_session
                await delete_session(session_id)
            except Exception:
                pass
