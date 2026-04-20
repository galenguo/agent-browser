"""Pipeline Template Engine — ${{ }} expression engine with pipe filters.

Template engine with 19 pipe filters for variable substitution.

Syntax:
  ${{ args.keyword }}           — Simple variable access
  ${{ item.title }}             — Array item field (inside map/filter)
  ${{ index + 1 }}              — Arithmetic
  ${{ args.limit | default(20) }}  — Pipe filter
  ${{ item.title | upper }}     — Pipe: uppercase
  ${{ item.a || item.b | upper }} — Pipe with logical OR (chained)
  ${{ Math.min(args.limit, 50) }} — Full JS expression

Variables:
  args    → user-provided arguments (e.g., args.keyword, args.limit)
  data    → output from previous step
  item    → current array item (inside map/filter)
  index   → current index (inside map/filter)

Security: Sandboxed evaluation via AST-based safe eval with context sanitization.
"""

import ast
import contextlib
import json
import logging
import re
import unicodedata
from typing import Any
from urllib.parse import quote_plus as _urlencode
from urllib.parse import unquote as _urldecode

logger = logging.getLogger(__name__)

# ── Template regex ──

TEMPLATE_PATTERN = re.compile(r"\$\{\{\s*(.*?)\s*\}\}")

# ── Pipe split regex (splits on single |, preserves ||) ──

_PIPE_SPLIT_RE = re.compile(r"(?<!\|)\|(?!\|)")

# ── Built-in pipe filters (19 total) ──

PIPE_FILTERS: dict[str, callable] = {}


def _register_filter(name: str):
    """Pipe filter registration decorator"""

    def decorator(fn):
        PIPE_FILTERS[name] = fn
        return fn

    return decorator


# ── Filters WITH arguments ──


@_register_filter("default")
def _filter_default(value: Any, **kw) -> Any:
    # Triggers on None, undefined, AND empty string ""
    arg = kw.get("arg")
    if value is None or value == "":
        return arg if arg is not None else ""
    return value


@_register_filter("truncate")
def _filter_truncate(value: Any, **kw) -> str:
    s = str(value) if value is not None else ""
    n = int(kw.get("arg", 50))
    if len(s) > n:
        return s[:n] + "..."  # Append ellipsis when truncated
    return s


@_register_filter("replace")
def _filter_replace(value: Any, **kw) -> str:
    old = kw.get("arg0", "")
    new = kw.get("arg1", "")
    return str(value).replace(old, new) if value is not None else ""


@_register_filter("join")
def _filter_join(value: Any, **kw) -> str:
    sep = kw.get("arg", ", ")
    if isinstance(value, list):
        return sep.join(str(v) for v in value)
    return str(value) if value is not None else ""


# ── Filters WITHOUT arguments ──


@_register_filter("upper")
def _filter_upper(value: Any, **kw) -> str:
    return str(value).upper() if value is not None else ""


@_register_filter("lower")
def _filter_lower(value: Any, **kw) -> str:
    return str(value).lower() if value is not None else ""


@_register_filter("trim")
def _filter_trim(value: Any, **kw) -> str:
    return str(value).strip() if value is not None else ""


@_register_filter("strip")
def _filter_strip(value: Any, **kw) -> str:
    return str(value).strip() if value is not None else ""


@_register_filter("keys")
def _filter_keys(value: Any, **kw) -> list:
    if isinstance(value, dict):
        return list(value.keys())
    return []


@_register_filter("length")
def _filter_length(value: Any, **kw) -> int:
    if value is None:
        return 0
    try:
        return len(value)
    except TypeError:
        return 0


@_register_filter("first")
def _filter_first(value: Any, **kw) -> Any:
    if isinstance(value, list) and len(value) > 0:
        return value[0]
    return value


@_register_filter("last")
def _filter_last(value: Any, **kw) -> Any:
    if isinstance(value, list) and len(value) > 0:
        return value[-1]
    return value


@_register_filter("json")
def _filter_json(value: Any, **kw) -> str:
    return json.dumps(value, ensure_ascii=False) if value is not None else "null"


@_register_filter("slugify")
def _filter_slugify(value: Any, **kw) -> str:
    s = str(value).lower() if value is not None else ""
    # Unicode-aware: keep only letters and numbers, replace rest with hyphen
    s = re.sub(r"[^\w\s-]", "", unicodedata.normalize("NFKD", s))
    s = re.sub(r"[\s_]+", "-", s)
    s = r"^-+|-+$".sub("", s) if hasattr(r"^-+|-+$", "sub") else re.sub(r"^-+|-+$", "", s)
    # Fix: use re.sub properly
    return re.sub(r"^-+|-+$", "", s)


@_register_filter("sanitize")
def _filter_sanitize(value: Any, **kw) -> str:
    """Replace invalid filename characters with underscore."""
    s = str(value) if value is not None else ""
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s)


@_register_filter("ext")
def _filter_ext(value: Any, **kw) -> str:
    """Extract file extension (everything after last . after last / or \\)."""
    s = str(value) if value is not None else ""
    last_dot = s.rfind(".")
    last_slash = max(s.rfind("/"), s.rfind("\\"))
    if last_dot > last_slash:
        return s[last_dot:]
    return ""


@_register_filter("basename")
def _filter_basename(value: Any, **kw) -> str:
    """Extract basename from URL or file path."""
    s = str(value) if value is not None else ""
    parts = re.split(r"[/\\]", s)
    return parts[-1] if parts else s


@_register_filter("urlencode")
def _filter_urlencode(value: Any, **kw) -> str:
    return _urlencode(str(value)) if value is not None else ""


@_register_filter("urldecode")
def _filter_urldecode(value: Any, **kw) -> str:
    try:
        return _urldecode(str(value)) if value is not None else ""
    except Exception:
        return str(value) if value is not None else ""


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

    Format: filter_name(arg1, arg2) or filter_name.property_path
    Examples: default(20), upper, truncate(50), first.name, items[0].title
    """
    filter_expr = filter_expr.strip()

    # Check for filter.property access pattern
    prop_match = re.match(r"(\w+)(?:\((.*)\))?\.([\w.]+)$", filter_expr)
    if prop_match:
        name = prop_match.group(1)
        args_str = prop_match.group(2)
        prop_path = prop_match.group(3)
    else:
        match = re.match(r"(\w+)(?:\((.*)\))?$", filter_expr)
        if not match:
            return value
        name = match.group(1)
        args_str = match.group(2)
        prop_path = None

    if name not in PIPE_FILTERS:
        logger.warning(f"Unknown pipe filter: {name}")
        return value

    fn = PIPE_FILTERS[name]

    # Parse arguments
    if args_str:
        kwargs = _parse_filter_args(args_str)
        result = fn(value, **kwargs)
    else:
        result = fn(value)

    # Access property on result (e.g., first.name → apply first, then .name)
    if prop_path is not None and result is not None:
        for part in prop_path.split("."):
            if isinstance(result, dict):
                result = result.get(part)
            elif hasattr(result, part):
                result = getattr(result, part)
            else:
                return None
            if result is None:
                break

    return result


def _parse_filter_args(args_str: str) -> dict[str, Any]:
    """Parse filter arguments like '20' or '"hello", "world"'

    Returns dict with 'arg' (first arg, for single-arg filters) plus
    'arg0', 'arg1', etc. (for multi-arg filters).

    Quoted arguments are kept as strings; unquoted numeric-looking args
    are auto-converted to int/float.
    """
    args = {}
    raw_parts = []
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
        elif ch == "," and not in_quote:
            raw_parts.append((current.strip(), in_quote))
            current = ""
            continue
        current += ch
    if current.strip():
        raw_parts.append((current.strip(), in_quote))

    for i, (part, was_quoted) in enumerate(raw_parts):
        if (part.startswith('"') and part.endswith('"')) or (part.startswith("'") and part.endswith("'")):
            part = part[1:-1]
            was_quoted = True

        # Only convert to numeric if NOT originally quoted
        if not was_quoted:
            try:
                part = int(part)
            except ValueError:
                with contextlib.suppress(ValueError):
                    part = float(part)

        args[f"arg{i}"] = part

    # Convenience: also provide 'arg' for single-argument filters
    if "arg0" in args:
        args["arg"] = args["arg0"]

    return args


# ── Context Sanitization (security layer) ──


def _sanitize_context(obj: Any) -> Any:
    """
    Deep-copy via JSON round-trip to sever prototype chains.

    This neutralizes constructor-based sandbox escapes like:
      args['constructor']['constructor']('return process')()

    After sanitization, obj.constructor points to Object, and
    Object.constructor.constructor will fail because we don't
    expose Function/eval in the eval namespace.
    """
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    try:
        return json.loads(json.dumps(obj))
    except (TypeError, ValueError):
        return {}


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

    Security: All context values are sanitized before use in _safe_eval().
    """

    def __init__(
        self, args: dict[str, Any] | None = None, data: Any = None, item: Any = None, index: int | None = None
    ):
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
          - Pipe chaining: item.a || item.b | upper (splits on single | only)
          - Complex expressions: Math.min(args.limit, 50)
        """
        expression = expression.strip()

        # Check for pipe filters
        pipe_parts = _PIPE_SPLIT_RE.split(expression)
        if len(pipe_parts) > 1:
            # First segment: evaluate normally
            value = self.resolve(pipe_parts[0].strip())
            # Remaining segments: chain through filters
            for segment in pipe_parts[1:]:
                value = apply_filter(value, segment.strip())
            return value

        # Try simple property path first
        value = self._resolve_property(expression)

        # If no operators present, return resolved property directly
        if not any(
            op in expression for op in ["+", "-", "*", "/", ">", "<", "(", "===", "!==", "==", "!=", "&&", "||"]
        ):
            return value

        # For expressions with operators, use safe eval
        return self._safe_eval(expression, value)

    def _resolve_property(self, path: str) -> Any:
        """Resolve a dot-separated property path like 'args.keyword'"""
        parts = path.split(".")
        root = parts[0].strip()

        root_map = {
            "args": self._args,
            "data": self._data,
            "item": self._item,
            "index": self._index,
        }

        value = root_map.get(root)

        if value is None:
            # Bare variable name: fall back to args
            if len(parts) == 1 and root in self._args:
                value = self._args[root]
            # Literal values
            elif root == "true":
                return True
            elif root == "false":
                return False
            elif root == "null" or root == "None":
                return None
            elif root.isdigit():
                return int(root)
            else:
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

        Security layers:
          1. Length limit (prevent DoS via huge expressions)
          2. Forbidden pattern blocklist (constructor, __proto__, etc.)
          3. Context sanitization (JSON round-trip severs prototype chains)
          4. AST node whitelist (only allow safe operations)
          5. Restricted globals (no dangerous builtins exposed)
        """
        # Layer 1: Length limit
        if len(expression) > 2000:
            logger.warning(f"Expression too long ({len(expression)} chars), blocked")
            return fallback

        # Layer 2: Forbidden pattern blocklist
        forbidden = r"\b(constructor|__proto__|prototype|globalThis|process|require|import|eval)\b"
        if re.search(forbidden, expression):
            logger.warning(f"Blocked forbidden pattern in expression: {expression}")
            return fallback

        # Layer 3: Sanitize context (sever prototype chains)
        sanitized_args = _sanitize_context(self._args)
        sanitized_data = _sanitize_context(self._data)
        sanitized_item = _sanitize_context(self._item)

        # Build eval namespace with ONLY safe globals (no Function, eval, __import__, etc.)
        eval_globals = {
            "__builtins__": {},  # Block access to Python builtins entirely
            "args": sanitized_args,
            "data": sanitized_data,
            "item": sanitized_item,
            "index": self._index,
            # Safe utility globals
            "json": json,
            "Math": type(
                "Math",
                (),
                {
                    "min": min,
                    "max": max,
                    "floor": lambda x: int(x),
                    "ceil": lambda x: int(x),
                    "round": round,
                    "abs": abs,
                },
            )(),
            "Number": type(
                "Number",
                (),
                {
                    "parseInt": lambda x, *_a: int(float(x)),
                    "parseFloat": float,
                },
            )(),
            "String": str,
            "Boolean": bool,
            "Array": list,
            "len": len,
            "int": int,
            "float": float,
            "str": str,
            "True": True,
            "False": False,
            "None": None,
        }

        # Expose individual arg keys as top-level variables
        # This allows expressions like '${{ a || b }}' where a,b are args
        if isinstance(sanitized_args, dict):
            for k, v in sanitized_args.items():
                if k not in eval_globals:  # Don't override builtins
                    eval_globals[k] = v

        # Replace variable references with sanitized namespace access
        expr = expression

        # Translate JS-style operators to Python
        expr = re.sub(r"\|\|\s*", " or ", expr)
        expr = re.sub(r"&&\s*", " and ", expr)
        expr = re.sub(r"===", "==", expr)
        expr = re.sub(r"!==", "!=", expr)

        try:
            tree = ast.parse(expr, mode="eval")
            allowed_nodes = (
                ast.Expression,
                ast.BinOp,
                ast.UnaryOp,
                ast.Compare,
                ast.BoolOp,
                ast.Num,
                ast.Constant,
                ast.Name,
                ast.Load,
                ast.Add,
                ast.Sub,
                ast.Mult,
                ast.Div,
                ast.FloorDiv,
                ast.Mod,
                ast.Pow,
                ast.UAdd,
                ast.USub,
                ast.Not,
                ast.And,
                ast.Or,
                ast.Eq,
                ast.NotEq,
                ast.Lt,
                ast.LtE,
                ast.Gt,
                ast.GtE,
                ast.IfExp,
                ast.Attribute,
            )
            for node in ast.walk(tree):
                if not isinstance(node, allowed_nodes):
                    # Allow Math.* calls
                    if (
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr in ("min", "max", "floor", "ceil", "round", "abs", "parseInt", "parseFloat")
                    ):
                        continue
                    return fallback
            return eval(compile(tree, "<template>", "eval"), eval_globals)
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
                if "." in rendered:
                    return float(rendered)
                return int(rendered)
            except (ValueError, TypeError):
                pass
        return rendered
    if isinstance(value, dict):
        return {k: render_value(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [render_value(v, ctx) for v in value]
    return value
