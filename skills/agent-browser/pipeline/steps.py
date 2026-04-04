"""Pipeline Step 处理器 — 所有浏览器操作经过 StealthMiddleware 隐匿封装"""
import asyncio
import json
import re
from typing import Any, Callable, Dict

from .template import resolve

STEPS: Dict[str, Callable] = {}

# CSS selector 允许的字符集（防止注入）
_CSS_SELECTOR_RE = re.compile(r'^[a-zA-Z0-9_\-#\.\[\]\(\)=*~^$|:+> ]+$')


def register(name: str):
    """注册 step 处理器装饰器"""
    def decorator(fn: Callable) -> Callable:
        STEPS[name] = fn
        return fn
    return decorator


def _escape_selector(selector: str) -> str:
    """验证并清理 CSS 选择器，防止注入攻击"""
    if not selector:
        raise ValueError("Empty selector is not allowed")
    if not _CSS_SELECTOR_RE.match(selector):
        raise ValueError(
            f"Invalid CSS selector characters in: {selector!r}. "
            "Only alphanumeric, #.[]()=*~^$|:+> and whitespace are allowed."
        )
    return selector


def _validate_url(url: str) -> str:
    """验证 URL 安全性（防止 SSRF 和危险 scheme）"""
    url = url.strip()
    if not url:
        raise ValueError("Empty URL is not allowed")
    # 只允许 http/https
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"URL must use http(s) scheme, got: {url[:20]}...")
    # 阻止 javascript:/data:/file: 协议
    lower = url.lower()
    for blocked in ("javascript:", "data:", "file:", "vbscript:", "blob:"):
        if lower.startswith(blocked):
            raise ValueError(f"Blocked URL scheme: {blocked}")
    return url


async def _get_handle(session_id: str):
    """通过 StealthMiddleware 获取 BrowserPageHandle（自动隐匿包装）"""
    from ..main import _ensure_middleware
    mw = await _ensure_middleware()
    return await mw.get_page(session_id)


# ─── 浏览器 Steps ─────────────────────────────────────────


@register("navigate")
async def step_navigate(session_id: str, params: Any, data: Any,
                        context: dict, stealth: dict) -> Any:
    url = _validate_url(resolve(str(params), **context))
    page = await _get_handle(session_id)
    await page.goto(url, wait_until="domcontentloaded", timeout=20000)
    return data


@register("evaluate")
async def step_evaluate(session_id: str, params: Any, data: Any,
                        context: dict, stealth: dict) -> Any:
    js_code = resolve(str(params), **context)
    page = await _get_handle(session_id)
    result = await page.evaluate(js_code)
    return result


@register("click")
async def step_click(session_id: str, params: Any, data: Any,
                     context: dict, stealth: dict) -> Any:
    selector = _escape_selector(resolve(str(params), **context))
    page = await _get_handle(session_id)

    safe_sel = json.dumps(selector)  # JSON 编码确保安全嵌入 JS 字符串
    result = await page.evaluate(
        f"""(() => {{
            const el = document.querySelector({safe_sel});
            if (!el) return {{error: 'not found'}};
            el.scrollIntoView({{block: 'center'}});
            el.click();
            return {{status: 'ok'}};
        }})()"""
    )
    if result and result.get("error"):
        raise ValueError(f"Click target not found: {selector}")
    return data


@register("type")
async def step_type(session_id: str, params: Any, data: Any,
                    context: dict, stealth: dict) -> Any:
    if isinstance(params, dict):
        selector = _escape_selector(resolve(str(params.get("selector", "")), **context))
        text = resolve(str(params.get("text", "")), **context)
    else:
        raise ValueError("type step requires {selector, text} dict")

    page = await _get_handle(session_id)
    escaped = json.dumps(text)
    safe_sel = json.dumps(selector)  # JSON 编码选择器
    await page.evaluate(
        f"""(() => {{
            const el = document.querySelector({safe_sel});
            if (!el) return;
            el.focus();
            el.value = {escaped};
            el.dispatchEvent(new Event('input', {{bubbles: true}}));
            el.dispatchEvent(new Event('change', {{bubbles: true}}));
        }})()"""
    )
    return data


@register("wait")
async def step_wait(session_id: str, params: Any, data: Any,
                    context: dict, stealth: dict) -> Any:
    page = await _get_handle(session_id)

    if isinstance(params, (int, float)):
        await asyncio.sleep(float(params))
    elif isinstance(params, str):
        resolved = resolve(params, **context)
        try:
            await asyncio.sleep(float(resolved))
        except ValueError:
            await page.wait_for_selector(resolved, timeout=10000)
    elif isinstance(params, dict):
        if "seconds" in params:
            await asyncio.sleep(float(resolve(str(params["seconds"]), **context)))
        elif "selector" in params:
            sel = resolve(str(params["selector"]), **context)
            timeout = int(params.get("timeout", 10000))
            await page.wait_for_selector(sel, timeout=timeout)

    return data


@register("fetch")
async def step_fetch(session_id: str, params: Any, data: Any,
                     context: dict, stealth: dict) -> Any:
    """
    HTTP 请求（串行，通过 StealthPageHandle 自动隐匿延迟）。

    支持两种模式:
      - 浏览器内 fetch（credentials: include，保持 cookie）
      - Python aiohttp（公共 API）

    安全: URL 经过 scheme + 私有 IP 校验。
    """
    if isinstance(params, str):
        params = {"url": params}

    url = _validate_url(resolve(str(params.get("url", "")), **context))

    # SSRF 防护：阻止私有/internal IP 段访问
    from urllib.parse import urlparse
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    # 阻止 loopback / link-local / private / cloud metadata
    blocked_prefixes = (
        "127.", "0.", "169.254.", "10.", "192.168.",
        "fc00:", "fe80:", "::1", "::ffff", "[::",
        "localhost", "metadata.google.internal",
    )
    for prefix in blocked_prefixes:
        if hostname == prefix or hostname.startswith(prefix):
            raise ValueError(
                f"SSRF blocked: cannot fetch internal/private address: {hostname}"
            )

    method = params.get("method", "GET")
    headers = params.get("headers", {})
    body = params.get("body")
    use_browser = params.get("browser", True)

    if use_browser:
        page = await _get_handle(session_id)
        safe_url = json.dumps(url)
        fetch_opts = f"{{method: '{method}', credentials: 'include'"
        if headers:
            fetch_opts += f", headers: {json.dumps(headers)}"
        if body:
            resolved_body = resolve(str(body), **context)
            fetch_opts += f", body: JSON.stringify({json.dumps(resolved_body)})"
        fetch_opts += "}"

        js = f"""
        (() => {{
            return fetch({safe_url}, {fetch_opts})
                .then(r => r.text())
                .then(t => {{
                    try {{ return JSON.parse(t); }}
                    catch {{ return t; }}
                }});
        }})()
        """
        result = await page.evaluate(js)
    else:
        import aiohttp
        async with aiohttp.ClientSession() as http:
            async with http.request(method, url, headers=headers) as resp:
                text = await resp.text()
                try:
                    result = json.loads(text)
                except json.JSONDecodeError:
                    result = text

    return result


# ─── 数据 Steps（不需要浏览器）─────────────────────────────


@register("select")
async def step_select(session_id: str, params: Any, data: Any,
                      context: dict, stealth: dict) -> Any:
    if isinstance(params, str):
        js_selector = resolve(params, **context)
        page = await _get_handle(session_id)

        js = f"""
        (() => {{
            const els = {js_selector};
            return Array.from(els).map(el => {{
                const result = {{}};
                for (const attr of el.attributes) {{
                    result[attr.name] = attr.value;
                }}
                result._text = (el.textContent || '').trim();
                result._html = el.innerHTML;
                return result;
            }}).slice(0, 100);
        }})()
        """
        return await page.evaluate(js)

    if isinstance(params, dict):
        path = params.get("path", "")
        parts = path.split(".")
        result = data
        for part in parts:
            if result is None:
                return None
            if isinstance(result, dict):
                result = result.get(part)
            elif isinstance(result, list):
                try:
                    result = result[int(part)]
                except (ValueError, IndexError):
                    return None
        return result

    return data


@register("map")
async def step_map(session_id: str, params: Any, data: Any,
                   context: dict, stealth: dict) -> Any:
    if not isinstance(data, list):
        if isinstance(data, dict):
            data = [data]
        else:
            return data

    if not isinstance(params, dict):
        return data

    result = []
    for i, item in enumerate(data):
        row = {}
        for key, tmpl in params.items():
            row[key] = resolve(str(tmpl), item=item, index=i, **context)
        result.append(row)
    return result


@register("filter")
async def step_filter(session_id: str, params: Any, data: Any,
                      context: dict, stealth: dict) -> Any:
    if not isinstance(data, list):
        return data

    if isinstance(params, str):
        # 安全过滤表达式：白名单验证，只允许 field==value / field!=value 格式
        # 支持格式: item.field == "value", item.field != 'value', && / || 组合
        expr = params.strip()
        _FILTER_EXPR_RE = re.compile(
            r'^('  # 一个或多个条件，用 && 或 || 连接
            r'(?:item\.[a-zA-Z_]\w*(?:\.\w+)*\s*(?:==|!=)\s*["\'][^"\']*["\'])'
            r'(?:\s*(?:&&|\|\|)\s*'
            r'(?:item\.[a-zA-Z_]\w*(?:\.\w+)*\s*(?:==|!=)\s*["\'][^"\']*["\']))*'
            r')$'
        )
        if not _FILTER_EXPR_RE.match(expr):
            raise ValueError(
                f"Unsafe filter expression: {expr!r}. "
                "Only item.field == 'value' / item.field != 'value' patterns "
                "combined with && or || are allowed."
            )

        page = await _get_handle(session_id)
        safe_expr = json.dumps(expr)
        js = f"""
        (() => {{
            const items = arguments[0];
            const text = typeof item === 'string' ? item : JSON.stringify(item);
            // 安全：只做属性访问比较，不执行任意代码
            const fields = {safe_expr}.split(/&&|\\|\\|/);
            for (const f of fields) {{
                const [k, op, v] = f.trim().split(/\\s+/);
                if (!k || !op) continue;
                const val = item[k];
                if (op === '==' && String(val) === v) return true;
                if (op === '!=' && String(val) !== v) return false;
            }}
            return false;
        }})()
        """
        result = await page.evaluate(js, data)
        # 布尔回布尔值或原始数据（保持向后兼容）
        if isinstance(result, bool) and not result:
            return []
        return data if not result else []

    if isinstance(params, dict):
        result = []
        for item in data:
            keep = True
            for key, expected in params.items():
                actual = item.get(key) if isinstance(item, dict) else None
                expected_val = resolve(str(expected), **context)
                if actual != expected_val:
                    keep = False
                    break
            if keep:
                result.append(item)
        return result

    return data


@register("limit")
async def step_limit(session_id: str, params: Any, data: Any,
                     context: dict, stealth: dict) -> Any:
    if isinstance(params, str):
        n = int(resolve(params, **context))
    else:
        n = int(params)

    if isinstance(data, list):
        return data[:n]
    return data
