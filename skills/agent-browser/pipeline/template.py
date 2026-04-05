"""
Pipeline Template Engine — ${{ }} expression engine with pipe filters.

Based on OpenCLI's template.ts, adapted for Python.

Syntax:
  ${{ args.keyword }}           — Simple variable access
  ${{ item.title }}             — Array item field (inside map/filter)
  ${{ index + 1 }}              — Arithmetic
  ${{ args.limit | default(20) }}  — Pipe filter
  ${{ item.title | upper }}     — Pipe: uppercase
  ${{ Math.min(args.limit, 50) }} — Full JS expression

Variables:
  args    → user-provided arguments (e.g., args.keyword, args.limit)
  data    → output from previous step
  item    → current array item (inside map/filter)
  index   → current index (inside map/filter)

Security: Sandboxed evaluation via AST-based safe eval.
"""
import re
import ast
import json
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus as _urlencode

logger = logging.getLogger(__name__)

# ── Template regex ──

TEMPLATE_PATTERN = re.compile(r'\$\{\{\s*(.*?)\s*\}\}')

# ── Built-in pipe filters (OpenCLI-compatible) ──

PIPE_FILTERS: Dict[str, callable] = {}


def _register_filter(name: str):
    """Pipe filter registration decorator"""
    def decorator(fn):
        PIPE_FILTERS[name] = fn
        return fn
    return decorator


@_register_filter("default")
def _filter_default(value: Any, arg=None) -> Any:
    return value if value is not None else (arg if arg is not None else "")


@_register_filter("upper")
def _filter_upper(value: Any, **kw) -> str:
    return str(value).upper() if value is not None else ""


@_register_filter("lower")
def _filter_lower(value: Any, **kw) -> str:
    return str(value).lower() if value is not None else ""


@_register_filter("truncate")
def _filter_truncate(value: Any, n=100, **kw) -> str:
    return str(value)[:int(n)] if value is not None else ""


@_register_filter("replace")
def _filter_replace(value: Any, old="", new="", **kw) -> str:
    return str(value).replace(old, new) if value is not None else ""


@_register_filter("join")
def _filter_join(value: Any, sep=", ", **kw) -> str:
    if isinstance(value, list):
        return sep.join(str(v) for v in value)
    return str(value) if value is not None else ""


@_register_filter("urlencode")
def _filter_urlencode(value: Any, **kw) -> str:
    return _urlencode(str(value)) if value is not None else ""


@_register_filter("strip")
def _filter_strip(value: Any, **kw) -> str:
    return str(value).strip() if value is not None else ""


@_register_filter("length")
def _filter_length(value: Any, **kw) -> int:
    return len(value) if value is not None else 0


@_register_filter("int")
def _filter_int(value: Any, **kw) -> int:
    try:
        return int(float(value)) if value is not None else 0
    except (ValueError, TypeError):
        return 0


@_register_filter("float")
def _filter_float(value: Any, **kw) -> float:
    try:
        return float(value) if value is not None else 0.0
    except (ValueError, TypeError):
        return 0.0


def apply_filter(value: Any, filter_expr: str) -> Any:
    """
    Apply a pipe filter to a value.

    Format: filter_name(arg1, arg2)
    Examples: default(20), upper, truncate(50), replace("foo", "bar")
    """
    filter_expr = filter_expr.strip()
    match = re.match(r'(\w+)(?:\((.*)\))?$', filter_expr)
    if not match:
        return value

    name = match.group(1)
    args_str = match.group(2)

    if name not in PIPE_FILTERS:
        logger.warning(f"Unknown pipe filter: {name}")
        return value

    fn = PIPE_FILTERS[name]

    # Parse arguments
    if args_str:
        kwargs = _parse_filter_args(args_str)
        return fn(value, **kwargs)
    else:
        return fn(value)


def _parse_filter_args(args_str: str) -> Dict[str, Any]:
    """Parse filter arguments like '20' or '"hello", "world"'"""
    args = {}
    parts = []
    current = ""
    in_quote = False
    quote_char = None
    for ch in args_str:
        if ch in ('"', "'") and not in_quote:
            in_quote = True
            quote_char = ch
        elif ch == quote_char and in_quote:
            in_quote = False
            quote_char = None
        elif ch == ',' and not in_quote:
            parts.append(current.strip())
            current = ""
            continue
        current += ch
    if current.strip():
        parts.append(current.strip())

    for i, part in enumerate(parts):
        if (part.startswith('"') and part.endswith('"')) or \
           (part.startswith("'") and part.endswith("'")):
            part = part[1:-1]
        try:
            part = int(part)
        except ValueError:
            try:
                part = float(part)
            except ValueError:
                pass
        args[f"arg{i}"] = part

    return args


# ── Public API (backward compatible) ──

def resolve(template: str, **context: Any) -> Any:
    """
    Resolve a template string. Backward-compatible entry point.
    Delegates to TemplateContext.resolve().
    """
    ctx = TemplateContext(
        args=context.get("args"),
        data=context.get("data"),
        item=context.get("item"),
        index=context.get("index"),
    )
    # If the entire template is a single ${{ }} expression, return raw value
    full_match = TEMPLATE_PATTERN.fullmatch(template.strip())
    if full_match:
        return ctx.resolve(full_match.group(1).strip())

    # Otherwise render as string (for embedded templates in URLs etc.)
    return render_template(template, ctx)


class TemplateContext:
    """
    Template evaluation context with variable scope.

    Variables available:
      - args: user-provided arguments
      - data: output from previous step
      - item: current array item (map/filter context)
      - index: current index (map/filter context)
    """

    def __init__(self, args: Dict[str, Any] | None = None, data: Any = None,
                 item: Any = None, index: int | None = None):
        self._args = args or {}
        self._data = data
        self._item = item
        self._index = index

    def resolve(self, expression: str) -> Any:
        """
        Resolve a template expression to a value.

        Handles:
          - Simple property access: args.keyword, item.title
          - Arithmetic: index + 1, args.limit * 2
          - Pipe filters: args.limit | default(20)
          - Complex expressions: Math.min(args.limit, 50)
        """
        expression = expression.strip()

        # Check for pipe filters
        if '|' in expression:
            parts = expression.split('|', 1)
            value = self.resolve(parts[0].strip())
            return apply_filter(value, parts[1].strip())

        # Try simple property path first
        value = self._resolve_property(expression)

        # If no operators present, return resolved property directly
        if not any(op in expression for op in ['+', '-', '*', '/', '>', '<', '===', '!==', '==', '!=', '&&', '||']):
            return value

        # For expressions with operators, use safe eval
        return self._safe_eval(expression, value)

    def _resolve_property(self, path: str) -> Any:
        """Resolve a dot-separated property path like 'args.keyword'"""
        parts = path.split('.')
        root = parts[0].strip()

        root_map = {
            "args": self._args,
            "data": self._data,
            "item": self._item,
            "index": self._index,
        }

        value = root_map.get(root)

        if value is None:
            # Literal values
            if root == "true":
                return True
            elif root == "false":
                return False
            elif root == "null" or root == "None":
                return None
            elif root.isdigit():
                return int(root)
            try:
                return float(root)
            except ValueError:
                return None

        # Navigate nested properties
        for part in parts[1:]:
            part = part.strip()
            if isinstance(value, dict):
                value = value.get(part)
            elif hasattr(value, part):
                value = getattr(value, part)
            else:
                return None
            if value is None:
                break

        return value

    def _safe_eval(self, expression: str, fallback: Any = None) -> Any:
        """
        Safe evaluation of arithmetic/comparison expressions using AST.
        Only allows basic operations: +, -, *, /, comparisons, boolean logic.
        """
        # Replace variables with their resolved values
        expr = expression
        var_map = {
            "args": repr(self._args),
            "data": repr(self._data),
            "item": repr(self._item),
            "index": repr(self._index),
        }
        for var, val in sorted(var_map.items(), key=lambda x: -len(x[0])):
            expr = re.sub(r'\b' + var + r'\b', val, expr)

        # Security check: block dangerous patterns
        dangerous_patterns = [
            r'import\s', r'__import__', r'exec\s*\(', r'eval\s*\(',
            r'__class__', r'__bases__', r'__subclasses__', r'__mro__',
            r'__globals__', r'__builtins__', r'open\s*\(',
            r'os\.', r'subprocess', r'sys\.', r'getattr\s*\(',
            r'setattr\s*\(', r'delattr\s*\(',
        ]
        for pattern in dangerous_patterns:
            if re.search(pattern, expr, re.IGNORECASE):
                logger.warning(f"Blocked potentially dangerous expression: {expression}")
                return fallback

        try:
            tree = ast.parse(expr, mode='eval')
            allowed_nodes = (
                ast.Expression, ast.BinOp, ast.UnaryOp, ast.Compare,
                ast.BoolOp, ast.Num, ast.Constant, ast.Name, ast.Load,
                ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv,
                ast.Mod, ast.Pow, ast.UAdd, ast.USub, ast.Not,
                ast.And, ast.Or, ast.Eq, ast.NotEq, ast.Lt, ast.LtE,
                ast.Gt, ast.GtE, ast.IfExp,
            )
            for node in ast.walk(tree):
                if not isinstance(node, allowed_nodes):
                    # Allow Math.* calls
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                        if node.func.attr in ('min', 'max', 'floor', 'ceil', 'round', 'abs'):
                            continue
                    return fallback
            return eval(compile(tree, '<template>', 'eval'))
        except Exception:
            return fallback


def render_template(template: str, ctx: TemplateContext) -> str:
    """
    Render a string template, replacing all ${{ }} expressions with resolved values.
    """
    def replacer(match):
        expr = match.group(1)
        value = ctx.resolve(expr)
        if value is None:
            return ""
        return str(value)

    return TEMPLATE_PATTERN.sub(replacer, template)


def render_value(value: Any, ctx: TemplateContext) -> Any:
    """
    Recursively render templates in strings, dicts, and lists.
    """
    if isinstance(value, str):
        rendered = render_template(value, ctx)
        # Try to convert numeric strings back
        if rendered != value:
            try:
                if '.' in rendered:
                    return float(rendered)
                return int(rendered)
            except (ValueError, TypeError):
                pass
        return rendered
    elif isinstance(value, dict):
        return {k: render_value(v, ctx) for k, v in value.items()}
    elif isinstance(value, list):
        return [render_value(v, ctx) for v in value]
    return value
