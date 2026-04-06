"""Pipeline Step Handlers — 16 built-in steps, all browser operations wrapped by StealthMiddleware.

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
import logging
import os
import re
from collections.abc import Callable
from typing import Any

from .template import resolve

logger = logging.getLogger(__name__)

STEPS: dict[str, Callable] = {}

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
    """Validate URL safety (prevent SSRF and dangerous schemes)

    Blocks:
      - Non-http(s) schemes (javascript:, data:, file:, etc.)
      - Private/internal IP ranges (10.x, 172.16-31.x, 192.168.x, 127.x, 169.254.x)
      - IPv6 loopback/link-local
    """
    import re

    url = url.strip()
    if not url:
        raise ValueError("Empty URL is not allowed")
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"URL must use http(s) scheme, got: {url[:20]}...")
    lower = url.lower()
    for blocked in ("javascript:", "data:", "file:", "vbscript:", "blob:"):
        if lower.startswith(blocked):
            raise ValueError(f"Blocked URL scheme: {blocked}")

    # SSRF: block private IP ranges in hostname
    hostname_match = re.match(r"^https?://([^/:]+)", url)
    if hostname_match:
        hostname = hostname_match.group(1).lower()
        _PRIVATE_HOSTS = (
            "localhost",
            "localhost.localdomain",
            # IPv4 private ranges
            "0.0.0.0",
        )
        if hostname in _PRIVATE_HOSTS:
            raise ValueError(f"Blocked hostname (private): {hostname}")
        # Check for numeric IP
        ip_pattern = r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$"
        ip_match = re.match(ip_pattern, hostname)
        if ip_match:
            parts = [int(g) for g in ip_match.groups()]
            if (
                parts[0] == 10
                or (parts[0] == 172 and 16 <= parts[1] <= 31)
                or (parts[0] == 192 and parts[1] == 168)
                or (parts[0] == 127)
                or (parts[0] == 169 and 254 <= parts[1] <= 255)
            ):
                raise ValueError(f"Blocked IP address (private network): {hostname}")

    return url


async def _get_handle(session_id: str):
    """Get BrowserPageHandle via StealthMiddleware (auto stealth wrapping)"""
    from agent_browser.main import _ensure_middleware

    mw = await _ensure_middleware()
    return await mw.get_page(session_id)


# ══════════════════════════════════════════════
#  INPUT ADAPTERS (normalize various param formats)
#  Each _adapt_*() normalizes input to internal format.
# ══════════════════════════════════════════════


def _adapt_wait(params: Any) -> Any:
    """
    Normalize wait step params.

    Formats accepted:
      3                          → {seconds: 3}
      {time: 3}                  → {seconds: 3}
      {text: "...", timeout: N}  → {_wait_text: "...", selector: null, timeout: N}

    Internal format (passthrough):
      {seconds: N}               → unchanged
      {selector: S, timeout: N}  → unchanged
    """
    if isinstance(params, (int, float)):
        return {"seconds": float(params)}
    if isinstance(params, str):
        # Could be a number-as-string or a CSS selector
        try:
            return {"seconds": float(params)}
        except ValueError:
            return {"selector": params}
    if isinstance(params, dict):
        # Alias: {time: N} → {seconds: N}
        if "time" in params:
            params = dict(params)
            params["seconds"] = params.pop("time")
        # Text-wait: poll for text appearance
        if "text" in params and "selector" not in params:
            params = dict(params)
            params["_wait_text"] = params.pop("text")
        return params
    return params


def _adapt_select(params: Any) -> Any:
    """
    Normalize select step params.

    Format accepted:
      "data.data.list"            → {path: "data.data.list"}  (dot-path over data)

    Internal format (passthrough):
      {path: "data"}              → unchanged

    Heuristic: string param containing . or [ is a dot-path;
    string without those is a CSS selector (legacy behavior).
    """
    if isinstance(params, str):
        # Heuristic: contains dot-path indicators → data path; else → CSS selector
        if any(c in params for c in (".", "[")):
            return {"path": params}
        # Legacy behavior: string = CSS selector (pass through for JS eval)
        return params
    return params


def _adapt_fetch(params: Any) -> Any:
    """
    Normalize fetch step params.

    Formats accepted:
      {url}                       → {url: ..., method: "GET", browser: true}
      {url, params: {...}}        → {url: ..., method: "GET", browser: true, _query_params: {...}}

    Internal format (passthrough):
      {url, method, headers, browser} → unchanged
    """
    if isinstance(params, str):
        return {"url": params}
    if isinstance(params, dict):
        params = dict(params)
        # params → query string (extracted by handler)
        if "params" in params and "_query_params" not in params:
            params["_query_params"] = params.pop("params")
        # Ensure defaults
        params.setdefault("method", "GET")
        params.setdefault("browser", True)
        return params
    return params


def _adapt_type(params: Any) -> Any:
    """
    Normalize type step params.

    Formats accepted:
      {ref: "@e1", text: "..."}   → {selector: "@e1", text: "..."}
      {ref: "@e1", text: "...", submit: true} → {selector: "@e1", text: "...", _submit: true}

    Internal format (passthrough):
      {selector: S, text: T}       → unchanged
    """
    if isinstance(params, dict):
        params = dict(params)
        # Uses 'ref' instead of 'selector'
        if "ref" in params and "selector" not in params:
            params["selector"] = params.pop("ref")
        # Optional 'submit' flag (presses Enter after typing)
        if "submit" in params:
            params["_submit"] = params.pop("submit")
        return params
    return params


def _adapt_tap(params: Any) -> Any:
    """
    Normalize tap step params (full shape + simple shape).

    Full shape (6+ fields):
      {store, action, capture, select, timeout, framework, args}

    Simple shape (2-3 fields):
      {store, getter} or {store, action, args}

    All fields pass through; handler consumes what it needs.
    """
    if isinstance(params, str):
        return {"getter": params}
    return params


def _adapt_navigate(params: Any) -> Any:
    """
    Normalize navigate step params.

    Formats accepted:
      "url"                       → string URL (passthrough)
      {url, waitUntil, settleMs}  → extract extra options

    Internal format (passthrough):
      "url" or {url, ...}         → unchanged
    """
    if isinstance(params, str):
        return {"url": params}  # Wrap string so step_navigate can .get() options
    if isinstance(params, dict):
        params = dict(params)
        # waitUntil → _wait_until
        if "waitUntil" in params:
            params["_wait_until"] = params.pop("waitUntil")
        # settleMs → _settle_ms
        if "settleMs" in params:
            params["_settle_ms"] = params.pop("settleMs")
        return params
    return params


# ══════════════════════════════════════════════
#  BROWSER STEPS (need page handle)
# ══════════════════════════════════════════════


@register("navigate")
async def step_navigate(session_id: str, params: Any, data: Any, context: dict, stealth: dict) -> Any:
    """Navigate to URL. Returns data unchanged."""
    params = _adapt_navigate(params)
    # Extract URL: handle both string and dict formats from _adapt_navigate
    raw_url = params.get("url", params) if isinstance(params, dict) else params
    url = _validate_url(resolve(str(raw_url), **context))
    page = await _get_handle(session_id)

    wait_until = params.get("_wait_until", "domcontentloaded")
    await page.goto(url, wait_until=wait_until, timeout=20000)

    # Extra delay after navigation
    settle_ms = params.get("_settle_ms")
    if settle_ms:
        await asyncio.sleep(float(settle_ms) / 1000.0)

    return data


@register("click")
async def step_click(session_id: str, params: Any, data: Any, context: dict, stealth: dict) -> Any:
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
async def step_type(session_id: str, params: Any, data: Any, context: dict, stealth: dict) -> Any:
    """Type text into element. Returns data unchanged."""
    params = _adapt_type(params)

    if isinstance(params, dict):
        selector = _escape_selector(resolve(str(params.get("selector", "")), **context))
        text = resolve(str(params.get("text", "")), **context)
        submit = params.get("_submit", False)
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
    # Optionally press Enter after typing
    if submit:
        await page.keyboard_press("Enter")

    return data


@register("wait")
async def step_wait(session_id: str, params: Any, data: Any, context: dict, stealth: dict) -> Any:
    """Wait seconds / for text / for selector. Returns data unchanged."""
    page = await _get_handle(session_id)
    params = _adapt_wait(params)

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
        # Text-wait: poll for text appearance
        if "_wait_text" in params:
            wait_text = resolve(str(params["_wait_text"]), **context)
            timeout = int(params.get("timeout", 10000))
            # Polling wait for text content
            js = f"""
            (() => {{
                const target = {json.dumps(wait_text)};
                return document.body.innerText.includes(target);
            }})()
            """
            deadline = __import__("asyncio").get_event_loop().time() + timeout / 1000.0
            while __import__("asyncio").get_event_loop().time() < deadline:
                found = await page.evaluate(js)
                if found:
                    return data
                await asyncio.sleep(0.3)
            logger.warning(f"Text wait timed out after {timeout}ms for: {wait_text[:50]}")
        elif "seconds" in params:
            await asyncio.sleep(float(resolve(str(params["seconds"]), **context)))
        elif "selector" in params:
            sel = _escape_selector(resolve(str(params["selector"]), **context))
            timeout = int(params.get("timeout", 10000))
            await page.wait_for_selector(sel, timeout=timeout)

    return data


@register("press")
async def step_press(session_id: str, params: Any, data: Any, context: dict, stealth: dict) -> Any:
    """Press keyboard key. Returns data unchanged."""
    key = resolve(str(params), **context)
    page = await _get_handle(session_id)
    await page.keyboard_press(key)
    return data


@register("snapshot")
async def step_snapshot(session_id: str, params: Any, data: Any, context: dict, stealth: dict) -> Any:
    """
    Extract DOM tree as structured data.

    Params:
      - string: CSS selector to extract elements from
      - dict: {selector, fields} for field-specific extraction

    Returns: list of dicts (DOM elements as data)
    """
    from agent_browser.main import _ensure_middleware

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
        return await page.evaluate(js)

    if isinstance(params, dict):
        selector = params.get("selector", "*")
        params.get("fields", [])
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
        return await page.evaluate(js)

    # No params: full page snapshot via middleware
    return await mw.snapshot(session_id, interactive_only=False)


@register("evaluate")
async def step_evaluate(session_id: str, params: Any, data: Any, context: dict, stealth: dict) -> Any:
    """Execute JavaScript in page context (sandboxed). Returns JS result as data."""
    js_code = resolve(str(params), **context)

    # Pipeline JS security check (consistent with API endpoint)
    _dangerous_js = (
        "fetch(",
        "XMLHttpRequest",
        "WebSocket",
        "eval(",
        "Function(",
        "document.write",
        "document.cookie",
        "localStorage",
        "sessionStorage",
        "indexedDB",
        ".src=",
        "location.assign",
        "location.replace",
        "window.open",
        "<script",
        "import(",
        "require(",
    )
    lowered = js_code.lower()
    for pat in _dangerous_js:
        if pat.lower() in lowered:
            raise ValueError(f"Blocked JavaScript in evaluate: {pat!r}")

    page = await _get_handle(session_id)

    # JS execution timeout (prevent infinite loops / hanging scripts)
    eval_timeout = 5.0  # seconds
    if isinstance(params, dict) and params.get("_timeout"):
        eval_timeout = float(params["_timeout"])

    try:
        result = await asyncio.wait_for(
            page.evaluate(js_code),
            timeout=eval_timeout,
        )
    except TimeoutError:
        raise ValueError(
            f"JavaScript execution timed out after {eval_timeout}s. Use _timeout param to increase limit."
        ) from None

    return result


@register("intercept")
async def step_intercept(session_id: str, params: Any, data: Any, context: dict, stealth: dict) -> Any:
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
async def step_tap(session_id: str, params: Any, data: Any, context: dict, stealth: dict) -> Any:
    """
    Store Action Bridge — call Vue/Pinia/Vuex store action + intercept network response.

    Supports both simple shape and full interceptor shape.

    Full shape (enables network interception):
      {store, action, capture, select, timeout, framework, args}

    Simple shape (direct store read):
      {store, action, getter, args}

    When `capture` is specified, installs a temporary fetch/XHR interceptor,
    calls the store action, waits for matching network response, then restores
    originals. This is the "store-action" strategy that zero-cost captures API
    data that would normally require cookie-based fetch interception.
    """
    params = _adapt_tap(params)

    if isinstance(params, str):
        params = {"getter": params}

    store_name = params.get("store", "")
    action_name = params.get("action", "")
    getter_name = params.get("getter", "")
    capture_pattern = params.get("capture", "")
    select_path = params.get("select")
    tap_timeout = int(params.get("timeout", 5))
    framework = params.get("framework")
    raw_args = params.get("args", [])

    # Validate required fields
    if not store_name or not action_name:
        raise ValueError(f"tap: 'store' and 'action' are required. Got: store={store_name!r}, action={action_name!r}")

    page = await _get_handle(session_id)

    # Render template values in params
    store_name = resolve(str(store_name), **context)
    action_name = resolve(str(action_name), **context)
    if capture_pattern:
        capture_pattern = resolve(str(capture_pattern), **context)
    if select_path:
        select_path = resolve(str(select_path), **context)

    # Build select chain for captured response sub-selection
    if select_path:
        select_parts = select_path.split(".")
        select_chain = "".join(f"?.[{json.dumps(p)}]" for p in select_parts)
    else:
        select_chain = ""

    # Serialize action arguments (render templates in each)
    if isinstance(raw_args, list):
        rendered_args = [json.dumps(resolve(str(a), **context)) for a in raw_args]
        args_js = ", ".join(rendered_args) if rendered_args else ""
    elif isinstance(raw_args, dict):
        args_js = json.dumps(raw_args)
    else:
        args_js = ""

    # Build action call JS
    safe_store = json.dumps(store_name)
    safe_action = json.dumps(action_name)
    action_call = f"store[{safe_action}]({args_js})" if args_js else f"store[{safe_action}]()"

    # Generate tap interceptor
    if capture_pattern:
        safe_capture = json.dumps(capture_pattern)
        js = f"""
        async () => {{
            // 1. Setup capture proxy (fetch + XHR dual interception)
            let captured = null;
            let captureResolve;
            const capturePromise = new Promise(r => {{ captureResolve = r; }});
            const pattern = {safe_capture};

            function __disguise(fn, name) {{
                const s = 'function ' + name + '() {{ [native code] }}';
                Object.defineProperty(fn, 'toString', {{ value: function() {{ return s; }}, writable: true, configurable: true, enumerable: false }});
                try {{ Object.defineProperty(fn, 'name', {{ value: name, configurable: true }}); }} catch {{}}
                return fn;
            }}

            // Patch fetch
            const origFetch = window.fetch;
            window.fetch = __disguise(async function(...fetchArgs) {{
                const resp = await origFetch.apply(this, fetchArgs);
                try {{
                    const url = typeof fetchArgs[0] === 'string' ? fetchArgs[0]
                        : fetchArgs[0] instanceof Request ? fetchArgs[0].url : String(fetchArgs[0]);
                    if (pattern && url.includes(pattern) && !captured) {{
                        try {{ captured = await resp.clone().json(); captureResolve(); }} catch {{}}
                    }}
                }} catch {{}}
                return resp;
            }}, 'fetch');

            // Patch XHR
            const origXhrOpen = XMLHttpRequest.prototype.open;
            const origXhrSend = XMLHttpRequest.prototype.send;
            XMLHttpRequest.prototype.open = __disguise(function(method, url) {{
                Object.defineProperty(this, '__iurl', {{ value: String(url), writable: true, enumerable: false, configurable: true }});
                return origXhrOpen.apply(this, arguments);
            }}, 'open');
            XMLHttpRequest.prototype.send = __disguise(function(body) {{
                if (pattern && this.__iurl?.includes(pattern)) {{
                    this.addEventListener('load', function() {{
                        if (!captured) {{
                            try {{ captured = JSON.parse(this.responseText); captureResolve(); }} catch {{}}
                        }}
                    }});
                }}
                return origXhrSend.apply(this, arguments);
            }}, 'send');

            try {{
                // 2. Find store (Pinia or Vuex)
                let store = null;
                const fw = {json.dumps(framework)};
                const app = document.querySelector('#app');

                if (!fw || fw === 'pinia') {{
                    try {{
                        const pinia = app?.__vue_app__?.config?.globalProperties?.$pinia;
                        if (pinia?._s) store = pinia._s.get({safe_store});
                    }} catch (e) {{ /* noop */ }}
                }}
                if (!store && (!fw || fw === 'vuex')) {{
                    try {{
                        const vuexStore = app?.__vue_app__?.config?.globalProperties?.$store
                            ?? app?.__vue__?.$store;
                        if (vuexStore) {{
                            store = {{ [{safe_store}]: (...a) => vuexStore.dispatch({safe_store} + '/' + {safe_action}, ...a) }};
                        }}
                    }} catch (e) {{ /* noop */ }}
                }}

                if (!store) return {{ error: 'Store not found: ' + {safe_store},
                    hint: 'Page may not be fully loaded or store name may be incorrect' }};
                if (typeof store[{safe_action}] !== 'function') {{
                    const available = Object.keys(store).filter(k =>
                        typeof store[k] === 'function' && !k.startsWith('$') && !k.startsWith('_')
                    );
                    return {{ error: 'Action not found: ' + {safe_action} + ' on store ' + {safe_store},
                        hint: 'Available: ' + available.join(', ') }};
                }}

                // 3. Call store action
                await {action_call};

                // 4. Wait for network response
                if (!captured) {{
                    const timeoutPromise = new Promise(r => setTimeout(r, {tap_timeout} * 1000));
                    await Promise.race([capturePromise, timeoutPromise]);
                }}
            }} finally {{
                // 5. Always restore originals
                window.fetch = origFetch;
                XMLHttpRequest.prototype.open = origXhrOpen;
                XMLHttpRequest.prototype.send = origXhrSend;
            }}

            if (!captured) return {{ error: 'No matching response captured for pattern: ' + pattern }};
            return captured{select_chain} ?? captured;
        }}
        """
    else:
        # Simple mode (no interception) — direct store read + Vuex support
        safe_getter = json.dumps(getter_name)
        safe_args = json.dumps(raw_args if not isinstance(raw_args, list) else {})
        js = f"""
        (() => {{
            let store = null;
            const app = document.querySelector('#app');

            // Try Pinia first
            try {{
                const pinia = app?.__vue_app__?.config?.globalProperties?.$pinia;
                if (pinia?._s) store = pinia._s.get({safe_store});
            }} catch (e) {{}}

            // Fallback to Vuex
            if (!store) {{
                try {{
                    const vuexStore = app?.__vue_app__?.config?.globalProperties?.$store
                        ?? app?.__vue__?.$store;
                    if (vuexStore) store = vuexStore;
                }} catch (e) {{}}
            }}

            if (!store) return {{ error: 'Store not found: ' + {safe_store},
                hint: 'No Vue/Pinia/Vuex instance found on this page' }};

            // Call action if specified
            if ({safe_action}) {{
                const fn = store[{safe_action}] || (store.dispatch ? store.dispatch.bind(store, {safe_store}/{safe_action}) : null);
                if (typeof fn === 'function') {{
                    const args = {safe_args};
                    await (Array.isArray(args) ? fn(...args) : fn(args));
                }}
            }}

            // Read getter if specified (simple shape)
            if ({safe_getter}) {{
                const val = store[{safe_getter}] ?? (store.state?.[{safe_getter}]) ?? (store.$state?.[{safe_getter}]);
                return val;
            }}

            // Return state snapshot
            if (store.$state) return {{$toRaw(store.$state)}};
            if (store.state) return store.state;
            return store;
        }})()
        """

    return await page.evaluate(js)


@register("download")
async def step_download(session_id: str, params: Any, data: Any, context: dict, stealth: dict) -> Any:
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
    _header, b64_data = data_url.split(",", 1)
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
async def step_fetch(session_id: str, params: Any, data: Any, context: dict, stealth: dict) -> Any:
    """
    HTTP request (serial, auto-stealth delayed).

    Two modes:
      - browser fetch (credentials: include, keeps cookies)
      - Python aiohttp (public API)

    Security: URL validated for scheme + private IP blocking.
    """
    params = _adapt_fetch(params)

    url = _validate_url(resolve(str(params.get("url", "")), **context))

    # Append query params from _query_params to URL
    query_params = params.get("_query_params")
    if query_params:
        from urllib.parse import parse_qs, urlencode, urlparse

        parsed = urlparse(url)
        existing = parse_qs(parsed.query)
        if isinstance(query_params, dict):
            existing.update(dict(query_params.items()))
        new_query = urlencode(existing, doseq=True)
        url = parsed._replace(query=new_query).geturl()

    # SSRF protection: block private/internal IP ranges
    from urllib.parse import urlparse

    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    blocked_prefixes = (
        "127.",
        "0.",
        "169.254.",
        "10.",
        "192.168.",
        "fc00:",
        "fe80:",
        "::1",
        "::ffff",
        "[::",
        "localhost",
        "metadata.google.internal",
    )
    for prefix in blocked_prefixes:
        if hostname == prefix or hostname.startswith(prefix):
            raise ValueError(f"SSRF blocked: cannot fetch internal/private address: {hostname}")

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

        async with aiohttp.ClientSession() as http, http.request(method, url, headers=headers) as resp:
            text = await resp.text()
            try:
                result = json.loads(text)
            except json.JSONDecodeError:
                result = text

    return result


@register("select")
async def step_select(session_id: str, params: Any, data: Any, context: dict, stealth: dict) -> Any:
    """Extract sub-field by path from data."""
    params = _adapt_select(params)

    if isinstance(params, str):
        # Legacy behavior: CSS selector → evaluate in browser
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
        # Dict format: dot-path extraction from data
        path = params.get("path", "")
        # Also support _select_path alias (from tap capture sub-selection)
        select_path = params.get("_select_path") or path
        parts = select_path.split(".")
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
async def step_map(session_id: str, params: Any, data: Any, context: dict, stealth: dict) -> Any:
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
async def step_filter(session_id: str, params: Any, data: Any, context: dict, stealth: dict) -> Any:
    """Filter array by expression or dict criteria."""
    if not isinstance(data, list):
        return data

    if isinstance(params, str):
        expr = params.strip()
        _FILTER_EXPR_RE = re.compile(
            r"^("
            r'(?:item\.[a-zA-Z_]\w*(?:\.\w+)*\s*(?:==|!=)\s*["\'][^"\']*["\'])'
            r"(?:\s*(?:&&|\|\|)\s*"
            r'(?:item\.[a-zA-Z_]\w*(?:\.\w+)*\s*(?:==|!=)\s*["\'][^"\']*["\']))*'
            r")$"
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
async def step_sort(session_id: str, params: Any, data: Any, context: dict, stealth: dict) -> Any:
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
async def step_limit(session_id: str, params: Any, data: Any, context: dict, stealth: dict) -> Any:
    """Truncate array to N items."""
    n = int(resolve(params, **context)) if isinstance(params, str) else int(params)

    if isinstance(data, list):
        return data[:n]
    return data
