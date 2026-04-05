"""
CLI 输出格式化

统一 CLI 命令的输出格式：
- 成功：{"status": "success", "data": {...}}
- 失败：{"status": "error", "error": "...", "data": {...}}
- trace 信息嵌入

支持 --format json / text 两种输出模式。
"""
import json
import sys
from typing import Any, Optional


def success(data: dict, trace: Optional[dict] = None) -> str:
    """格式化成功输出"""
    output = {
        "status": "success",
        "data": data,
    }
    if trace:
        output["trace"] = trace
    return json.dumps(output, ensure_ascii=False, indent=None)


def error(message: str, data: Optional[dict] = None) -> str:
    """格式化错误输出"""
    output = {
        "status": "error",
        "error": message,
    }
    if data:
        output["data"] = data
    return json.dumps(output, ensure_ascii=False, indent=None)


def destroyed(resource_id: str, resource_type: str = "session") -> str:
    """格式化资源销毁输出"""
    return json.dumps({
        "status": "destroyed",
        "data": {resource_type: resource_id},
    }, ensure_ascii=False)


def format_result(result: Any) -> str:
    """
    统一格式化 ActionResult 或原始数据。

    接受 BrowserController 的 ActionResult，或普通 dict。
    """
    if hasattr(result, "to_dict"):
        # ActionResult 对象
        d = result.to_dict()
        return json.dumps(d, ensure_ascii=False, indent=None)
    elif isinstance(result, dict):
        return json.dumps(result, ensure_ascii=False, indent=None)
    else:
        return json.dumps({"status": "success", "data": {"result": str(result)}}, ensure_ascii=False)


def echo(output: str, err: bool = False):
    """输出到 stdout/stderr"""
    if err:
        print(output, file=sys.stderr)
    else:
        print(output)
