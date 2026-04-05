"""Pipeline Step 处理器 — 16 内置步骤，所有浏览器操作经过 StealthMiddleware 隐匿封装

Steps Registry:
  Browser steps (need page handle):
    navigate     — goto URL + wait for DOM stable
    click        — Click element by CSS selector
    type         — Type text into element
    wait         — Wait seconds / text / selector
    press        — Press keyboard key
    snapshot     — DOM tree extraction
    evaluate     — Execute JS in page context
    intercept    — XHR/Fetch network interception
    tap          — Vue/Pinia store action (declarative data fetch)
    download     — Download file to disk

  Data steps (pure transformation):
    fetch        — HTTP GET/POST (browser or direct)
    select       — Extract sub-field by path
    map          — Transform array items
    filter       — Filter array by expression
    sort         — Sort array by field
    limit        — Truncate array
"""
import asyncio
import json
import re
import os
import logging
from typing import Any, Callable, Dict

from .template import resolve

logger = logging.getLogger(__name__)

STEPS: Dict[str, Callable] = {}

# CSS selector allowed characters (prevent injection)
_CSS_SELECTOR_RE = re.compile(r'^[a-zA-Z0-9_\-#\.\[\]\(\)=*~^$|:\',"+> ]+$')


def register(name: str):
    """Register step handler decorator"""
    def decorator(fn: Callable) -> Callable:
        STEPS[name] = fn
        return fn
    return decorator


def _escape_selector(selector: str) -> str:
    """Validate and sanitize CSS selector"""
    if not selector:
        raise ValueError("Empty selector is not allowed")
    if not _CSS_SELECTOR_RE.match(selector):
        raise ValueError(
            f"Invalid CSS selector characters in: {selector!r}. "
            "Only alphanumeric, #.[]()=*~^$|:+> and whitespace are allowed."
        )
    return selector


def _validate_url(url: str) -> str:
    """Validate URL safety (prevent SSRF and dangerous schemes)"""
    url = url.strip()
    if not url:
        raise ValueError("Empty URL is not allowed")
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"URL must use http(s) scheme, got: {url[:20]}...")
    lower = url.lower()
    for blocked in ("javascript:", "data:", "file:", "vbscript:", "blob:"):
        if lower.startswith(blocked):
            raise ValueError(f"Blocked URL scheme: {blocked}")
    return url


async def _get_handle(session_id: str):
    """Get BrowserPageHandle via StealthMiddleware (auto stealth wrapping)"""
    from ..main import _ensure_middleware
    mw = await _ensure_middleware()
    return await mw.get_page(session_id)


# ══════════════════════════════════════════════
#  BROWSER STEPS (need page handle)
# ══════════════════════════════════════════════


@register("navigate")
async def step_navigate(session_id: str, params: Any, data: Any,
                        context: dict, stealth: dict) -> Any:
    """Navigate to URL. Returns data unchanged."""
    url = _validate_url(resolve(str(params), **context))
    page = await _get_handle(session_id)
    await page.goto(url, wait_until="domcontentloaded", timeout=20000)
    return data


@register("click")
async def step_click(session_id: str, params: Any, data: Any,
                     context: dict, stealth: dict) -> Any:
    """Click element by CSS selector. Returns data unchanged."""
    selector = _escape_selector(resolve(str(params), **context))
    page = await _get_handle(session_id)

    safe_sel = json.dumps(selector)
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
    """Type text into element. Returns data unchanged."""
    if isinstance(params, dict):
        selector = _escape_selector(resolve(str(params.get("selector", "")), **context))
        text = resolve(str(params.get("text", "")), **context)
    else:
        raise ValueError("type step requires {selector, text} dict")

    page = await _get_handle(session_id)
    escaped = json.dumps(text)
    safe_sel = json.dumps(selector)
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
    """Wait seconds / for text / for selector. Returns data unchanged."""
    page = await _get_handle(session_id)

    if isinstance(params, (int, float)):
        await asyncio.sleep(float(params))
    elif isinstance(params, str):
        resolved = resolve(params, **context)
        try:
            await asyncio.sleep(float(resolved))
        except ValueError:
            sel = _escape_selector(resolved)
            await page.wait_for_selector(sel, timeout=10000)
    elif isinstance(params, dict):
        if "seconds" in params:
            await asyncio.sleep(float(resolve(str(params["seconds"]), **context)))
        elif "selector" in params:
            sel = _escape_selector(resolve(str(params["selector"]), **context))
            timeout = int(params.get("timeout", 10000))
            await page.wait_for_selector(sel, timeout=timeout)

    return data


@register("press")
async def step_press(session_id: str, params: Any, data: Any,
                     context: dict, stealth: dict) -> Any:
    """Press keyboard key. Returns data unchanged."""
    key = resolve(str(params), **context)
    page = await _get_handle(session_id)
    await page.keyboard_press(key)
    return data


@register("snapshot")
async def step_snapshot(session_id: str, params: Any, data: Any,
                        context: dict, stealth: dict) -> Any:
    """
    Extract DOM tree as structured data.

    Params:
      - string: CSS selector to extract elements from
      - dict: {selector, fields} for field-specific extraction

    Returns: list of dicts (DOM elements as data)
    """
    from ..main import _ensure_middleware
    mw = await _ensure_middleware()

    if isinstance(params, str):
        selector = _escape_selector(resolve(params, **context))
        page = await _get_handle(session_id)
        safe_sel = json.dumps(selector)
        js = f"""
        (() => {{
            const els = document.querySelectorAll({safe_sel});
            return Array.from(els).map((el, i) => ({{
                _index: i,
                tag: el.tagName.toLowerCase(),
                text: (el.textContent || '').trim().substring(0, 500),
                attrs: Object.fromEntries(
                    [...el.attributes].filter(a =>
                        ['id', 'class', 'href', 'src', 'data-', 'title', 'role',
                         'aria-label', 'name', 'type', 'value', 'placeholder'].includes(a.name)
                    ).map(a => [a.name, a.value])
                ),
            }})).slice(0, 200);
        }})()
        """
        result = await page.evaluate(js)
        return result

    elif isinstance(params, dict):
        selector = params.get("selector", "*")
        fields = params.get("fields", [])
        page = await _get_handle(session_id)
        safe_sel = json.dumps(selector)
        js = f"""
        (() => {{
            const els = document.querySelectorAll({safe_sel});
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
        result = await page.evaluate(js)
        return result

    # No params: full page snapshot via middleware
    return await mw.snapshot(session_id, interactive_only=False)


@register("evaluate")
async def step_evaluate(session_id: str, params: Any, data: Any,
                        context: dict, stealth: dict) -> Any:
    """Execute JavaScript in page context (sandboxed). Returns JS result as data."""
    js_code = resolve(str(params), **context)

    # Pipeline JS 安全检查（与 API 端点一致）
    _dangerous_js = (
        'fetch(', 'XMLHttpRequest', 'WebSocket', 'eval(', 'Function(',
        'document.write', 'document.cookie', 'localStorage',
        'sessionStorage', 'indexedDB', '.src=', 'location.assign',
        'location.replace', 'window.open', '<script', 'import(',
        'require(',
    )
    lowered = js_code.lower()
    for pat in _dangerous_js:
        if pat.lower() in lowered:
            raise ValueError(
                f"Blocked JavaScript in evaluate: {pat!r}"
            )

    page = await _get_handle(session_id)
    result = await page.evaluate(js_code)
    return result


@register("intercept")
async def step_intercept(session_id: str, params: Any, data: Any,
                          context: dict, stealth: dict) -> Any:
    """
    Install network interceptor for XHR/Fetch matching a pattern.

    Params:
      - url_pattern: regex or substring to match request URLs
      - method: GET/POST (default: any)
      - max_results: max responses to capture (default: 50)

    Returns: list of intercepted response objects.
    """
    if isinstance(params, str):
        params = {"url_pattern": params}

    url_pattern = params.get("url_pattern", "")
    method_filter = params.get("method", "").upper()
    max_results = int(params.get("max_results", 50))

    page = await _get_handle(session_id)
    safe_pattern = json.dumps(url_pattern)
    safe_method = json.dumps(method_filter)
    safe_max = json.dumps(max_results)

    js = f"""
    (() => {{
        const results = [];
        const origFetch = window.fetch;
        const origXHROpen = XMLHttpRequest.prototype.open;
        const origXHRSend = XMLHttpRequest.prototype.send;

        // Intercept fetch
        window.fetch = async function(...args) {{
            const url = typeof args[0] === 'string' ? args[0] : args[0]?.url || '';
            const match = {safe_pattern} ? url.includes({safe_pattern}) : true;
            const methodMatch = {safe_method} ? args[1]?.method?.toUpperCase() === {safe_method} : true;

            if (match && methodMatch && results.length < {safe_max}) {{
                try {{
                    const resp = await origFetch.apply(this, args);
                    const clone = resp.clone();
                    const body = await clone.text();
                    let parsed = body;
                    try {{ parsed = JSON.parse(body); }} catch(e) {{}}
                    results.push({{
                        url, method: args[1]?.method || 'GET',
                        status: resp.status, body: parsed
                    }});
                    return resp;
                }} catch(e) {{ return origFetch.apply(this, args); }}
            }}
            return origFetch.apply(this, args);
        }};

        // Intercept XHR (simplified)
        XMLHttpRequest.prototype.open = function(method, url, ...rest) {{
            this._ab_url = url;
            this._ab_method = method;
            return origXHROpen.call(this, method, url, ...rest);
        }};
        XMLHttpRequest.prototype.send = function(body) {{
            const match = {safe_pattern} ? (this._ab_url || '').includes({safe_pattern}) : true;
            const methodMatch = {safe_method} ? (this._ab_method || '') === {safe_method} : true;
            if (match && methodMatch && results.length < {safe_max}) {{
                this.addEventListener('load', function() {{
                    try {{
                        let parsed = this.responseText;
                        try {{ parsed = JSON.parse(this.responseText); }} catch(e) {{}}
                        results.push({{
                            url: this._ab_url, method: this._ab_method,
                            status: this.status, body: parsed
                        }});
                    }} catch(e) {{}}
                }});
            }}
            return origXHRSend.call(this, body);
        }};

        // Auto-cleanup after delay
        setTimeout(() => {{
            window.fetch = origFetch;
            XMLHttpRequest.prototype.open = origXHROpen;
            XMLHttpRequest.prototype.send = origXHRSend;
        }}, 30000);

        return results;
    }})()
    """
    result = await page.evaluate(js)
    return result if isinstance(result, list) else []


@register("tap")
async def step_tap(session_id: str, params: Any, data: Any,
                   context: dict, stealth: dict) -> Any:
    """
    Call Vue/Pinia store action declaratively.

    This is the highest-performance strategy: zero network requests,
    directly reads from the app's in-memory state management.

    Params:
      - store: Pinia store name (e.g., 'jobStore')
      - action: action name (e.g., 'fetchJobs')
      - args: action arguments (dict)
      - getter: getter name to read after action (e.g., 'jobs')

    Returns: Store data (the getter value).
    """
    if isinstance(params, str):
        params = {"getter": params}

    store_name = params.get("store", "")
    action_name = params.get("action", "")
    getter_name = params.get("getter", "")
    action_args = params.get("args", {})

    page = await _get_handle(session_id)
    safe_store = json.dumps(store_name)
    safe_action = json.dumps(action_name)
    safe_getter = json.dumps(getter_name)
    safe_args = json.dumps(action_args)

    js = f"""
    (() => {{
        // Try to access Vue/Pinia instance
        const app = document.querySelector('#app')?.__vue_app__;
        if (!app) {{
            // Try global Vue instance
            const vue = window.__VUE__ || window.Vue || window.vue;
            if (!vue) return {{error: 'No Vue/Pinia instance found'}};
        }}

        // Access Pinia stores
        const pinia = app?.config?.globalProperties?.$pinia;
        if (!pinia) return {{error: 'Pinia not found'}};

        const store = pinia._s.get({safe_store});
        if (!store) return {{error: 'Store not found: ' + {safe_store}}};

        // Call action if specified
        if ({safe_action} && typeof store[{safe_action}] === 'function') {{
            await store[{safe_action}]({safe_args});
        }}

        // Read getter if specified
        if ({safe_getter}) {{
            return store[{safe_getter}];
        }}

        // Return entire store state
        return {{$toRaw(store.$state)}};
    }})()
    """
    result = await page.evaluate(js)
    return result


@register("download")
async def step_download(session_id: str, params: Any, data: Any,
                        context: dict, stealth: dict) -> Any:
    """
    Download file to disk via browser fetch.

    Params:
      - url: file URL to download
      - save_dir: directory to save (default: current dir)
      - filename: custom filename (default: from URL)

    Returns: filepath of downloaded file.
    """
    if isinstance(params, str):
        params = {"url": params}

    url = _validate_url(resolve(str(params.get("url", "")), **context))
    save_dir = params.get("save_dir", ".")
    filename = params.get("filename", "")

    page = await _get_handle(session_id)
    safe_url = json.dumps(url)

    # Fetch in browser context (inherits cookies/auth)
    js = f"""
    (() => {{
        return fetch({{url: {safe_url}, credentials: 'include'}})
            .then(r => r.blob())
            .then(blob => {{
                return new Promise((resolve) => {{
                    const reader = new FileReader();
                    reader.onloadend = () => resolve(reader.result);
                    reader.readAsDataURL(blob);
                }});
            }});
    }})()
    """
    data_url = await page.evaluate(js)

    if not data_url or not isinstance(data_url, str):
        raise RuntimeError(f"Download failed for URL: {url}")

    # Decode base64 and save
    header, b64_data = data_url.split(",", 1)
    file_bytes = __import__("base64").b64decode(b64_data)

    if not filename:
        from urllib.parse import urlparse
        filename = urlparse(url).path.rsplit("/", 1)[-1] or "download"

    filepath = os.path.join(save_dir, filename)
    os.makedirs(save_dir, exist_ok=True)
    with open(filepath, "wb") as f:
        f.write(file_bytes)

    logger.info(f"Downloaded: {filepath} ({len(file_bytes)} bytes)")
    return filepath


# ══════════════════════════════════════════════
#  DATA STEPS (no browser needed)
# ══════════════════════════════════════════════


@register("fetch")
async def step_fetch(session_id: str, params: Any, data: Any,
                     context: dict, stealth: dict) -> Any:
    """
    HTTP request (serial, auto-stealth delayed).

    Two modes:
      - browser fetch (credentials: include, keeps cookies)
      - Python aiohttp (public API)

    Security: URL validated for scheme + private IP blocking.
    """
    if isinstance(params, str):
        params = {"url": params}

    url = _validate_url(resolve(str(params.get("url", "")), **context))

    # SSRF protection: block private/internal IP ranges
    from urllib.parse import urlparse
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
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

    method = str(params.get("method", "GET")).upper()
    _ALLOWED_METHODS = ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS")
    if method not in _ALLOWED_METHODS:
        raise ValueError(f"Blocked HTTP method: {method}. Allowed: {_ALLOWED_METHODS}")
    headers = params.get("headers", {})
    body = params.get("body")
    use_browser = params.get("browser", True)

    if use_browser:
        page = await _get_handle(session_id)
        safe_url = json.dumps(url)
        safe_method = json.dumps(method)
        fetch_opts = f"{{method: {safe_method}, credentials: 'include'"
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


@register("select")
async def step_select(session_id: str, params: Any, data: Any,
                      context: dict, stealth: dict) -> Any:
    """Extract sub-field by path from data."""
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
    """Transform array items using template expressions."""
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
    """Filter array by expression or dict criteria."""
    if not isinstance(data, list):
        return data

    if isinstance(params, str):
        expr = params.strip()
        _FILTER_EXPR_RE = re.compile(
            r'^('
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
            const filtered = [];
            for (const item of items) {{
                const fields = {safe_expr}.split(/&&|\\|\\|/);
                let keep = true;
                for (const f of fields) {{
                    const m = f.trim().match(/(item\\.\\w+)\\s*(==|!=)\\s*["']([^"']*)["']/);
                    if (!m) continue;
                    const val = (function() {{ try {{ return eval(m[1]); }} catch(e) {{ return undefined; }} }})();
                    if (m[2] === '==' && String(val) !== m[3]) keep = false;
                    if (m[2] === '!=' && String(val) === m[3]) keep = false;
                }}
                if (keep) filtered.push(item);
            }}
            return filtered;
        }})()
        """
        result = await page.evaluate(js, data)
        return result if isinstance(result, list) else data

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


@register("sort")
async def step_sort(session_id: str, params: Any, data: Any,
                    context: dict, stealth: dict) -> Any:
    """Sort array by field."""
    if not isinstance(data, list):
        return data

    if isinstance(params, str):
        field = resolve(params, **context)
        reverse = False
    elif isinstance(params, dict):
        field = resolve(str(params.get("field", "")), **context)
        reverse = bool(params.get("reverse", False))
    else:
        return data

    if not field:
        return data

    # Use browser's JS engine for sorting (handles mixed types gracefully)
    page = await _get_handle(session_id)
    safe_field = json.dumps(field)
    safe_reverse = json.dumps(reverse)
    js = f"""
    (() => {{
        const items = arguments[0];
        const field = {safe_field};
        const reverse = {safe_reverse};
        return items.slice().sort((a, b) => {{
            const va = a[field]; const vb = b[field];
            if (va == null) return reverse ? -1 : 1;
            if (vb == null) return reverse ? 1 : -1;
            if (typeof va === 'number' && typeof vb === 'number')
                return reverse ? vb - va : va - vb;
            const sa = String(va); const sb = String(vb);
            return reverse ? sb.localeCompare(sa) : sa.localeCompare(sb);
        }});
    }})()
    """
    result = await page.evaluate(js, data)
    return result if isinstance(result, list) else data


@register("limit")
async def step_limit(session_id: str, params: Any, data: Any,
                     context: dict, stealth: dict) -> Any:
    """Truncate array to N items."""
    if isinstance(params, str):
        n = int(resolve(params, **context))
    else:
        n = int(params)

    if isinstance(data, list):
        return data[:n]
    return data
