"""模板表达式引擎 — 解析 ${{ }} 表达式"""
import re
from typing import Any
def quote_plus_direct(value):
    return quote_plus(str(value)) if value is not None else ""


# 匹配 ${{ expr }} 模板
_TEMPLATE_RE = re.compile(r"\$\{\{\s*(.+?)\s*\}\}")


def resolve(template: str, **context: Any) -> Any:
    """
    解析模板表达式。

    支持的表达式:
      - 变量引用: ${{ args.query }}
      - 算术运算: ${{ index + 1 }}
      - 管道过滤器: ${{ args.query | urlencode }}
      - 属性访问: ${{ item.title }}
    """
    if not isinstance(template, str):
        return template

    # 检查是否整个字符串就是一个模板（无多余文本）
    full_match = _TEMPLATE_RE.fullmatch(template.strip())
    if full_match:
        return _eval_expr(full_match.group(1).strip(), context)

    # 字符串中嵌入模板 — 替换所有匹配
    def replacer(m: re.Match) -> str:
        result = _eval_expr(m.group(1).strip(), context)
        return str(result) if result is not None else ""

    return _TEMPLATE_RE.sub(replacer, template)


def _eval_expr(expr: str, context: dict) -> Any:
    """评估单个表达式（支持管道）"""
    parts = [p.strip() for p in expr.split("|")]
    value = _eval_atom(parts[0], context)
    for pipe in parts[1:]:
        value = _apply_pipe(value, pipe.strip())
    return value


def _eval_atom(expr: str, context: dict) -> Any:
    """评估原子表达式"""
    # 尝试简单的点路径解析
    tokens = expr.split()
    if len(tokens) == 1:
        return _resolve_path(tokens[0], context)
    # 简单算术: index + 1, args.limit * 2 等
    if len(tokens) == 3:
        left = _resolve_path(tokens[0], context)
        right = _resolve_path(tokens[2], context)
        op = tokens[1]
        if op == "+":
            return left + right
        elif op == "-":
            return left - right
        elif op == "*":
            return left * right
        elif op == "/":
            return left / right if right != 0 else 0
        elif op == "==":
            return left == right
        elif op == "!=":
            return left != right
        elif op == ">":
            return left > right
        elif op == "<":
            return left < right
    # 字符串字面量
    if expr.startswith("'") and expr.endswith("'"):
        return expr[1:-1]
    if expr.startswith('"') and expr.endswith('"'):
        return expr[1:-1]
    # 数字字面量
    try:
        return int(expr)
    except ValueError:
        pass
    try:
        return float(expr)
    except ValueError:
        pass
    return _resolve_path(expr, context)


def _resolve_path(path: str, context: dict) -> Any:
    """解析点路径: args.query, item.title, index, 或字面量"""
    parts = path.split(".")
    value = context.get(parts[0])
    if value is not None:
        for part in parts[1:]:
            if value is None:
                return None
            if isinstance(value, dict):
                value = value.get(part)
            elif isinstance(value, (list, tuple)):
                try:
                    value = value[int(part)]
                except (ValueError, IndexError):
                    return None
            else:
                value = getattr(value, part, None)
        return value
    # 尝试解析为字面量
    if path.startswith("'") and path.endswith("'"):
        return path[1:-1]
    if path.startswith('"') and path.endswith('"'):
        return path[1:-1]
    try:
        return int(path)
    except ValueError:
        pass
    try:
        return float(path)
    except ValueError:
        pass
    return None


def _apply_pipe(value: Any, pipe_name: str) -> Any:
    """应用管道过滤器"""
    if pipe_name == "urlencode":
        return quote_plus(str(value)) if value is not None else ""
    elif pipe_name == "lower":
        return str(value).lower()
    elif pipe_name == "upper":
        return str(value).upper()
    return value
