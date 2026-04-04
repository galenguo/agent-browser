"""Pipeline Step 处理器 — 所有浏览器操作经过 StealthMiddleware 隐匿封装"""
import json
from typing import Any, Callable, Dict

from .template import resolve

STEPS: Dict[str, Callable] = {}


def register(name: str):
    """注册 step 处理器装饰器"""
    def decorator(fn: Callable) -> Callable:
        STEPS[name] = fn
        return fn
    return decorator


async def _get_handle(session_id: str):
    """通过 StealthMiddleware 获取 BrowserPageHandle（自动隐匿包装）"""
    from ..main import _ensure_middleware
    mw = await _ensure_middleware()
    return await mw.get_page(session_id)


# ─── 浏览器 Steps ─────────────────────────────────────────


@register("navigate")
async def step_navigate(session_id: str, params: Any, data: Any,
                        context: dict, stealth: dict) -> Any:
    url = resolve(str(params), **context)
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
    selector = resolve(str(params), **context)
    page = await _get_handle(session_id)

    result = await page.evaluate(
        f"""(() => {{
            const el = document.querySelector('{selector}');
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
        selector = resolve(str(params.get("selector", "")), **context)
        text = resolve(str(params.get("text", "")), **context)
    else:
        raise ValueError("type step requires {selector, text} dict")

    page = await _get_handle(session_id)
    escaped = json.dumps(text)
    await page.evaluate(
        f"""(() => {{
            const el = document.querySelector('{selector}');
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
        import asyncio
        await asyncio.sleep(float(params))
    elif isinstance(params, str):
        resolved = resolve(params, **context)
        try:
            import asyncio
            await asyncio.sleep(float(resolved))
        except ValueError:
            await page.wait_for_selector(resolved, timeout=10000)
    elif isinstance(params, dict):
        if "seconds" in params:
            import asyncio
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
    """
    if isinstance(params, str):
        params = {"url": params}

    url = resolve(str(params.get("url", "")), **context)
    method = params.get("method", "GET")
    headers = params.get("headers", {})
    body = params.get("body")
    use_browser = params.get("browser", True)

    if use_browser:
        page = await _get_handle(session_id)
        fetch_opts = f"{{method: '{method}', credentials: 'include'"
        if headers:
            fetch_opts += f", headers: {json.dumps(headers)}"
        if body:
            resolved_body = resolve(str(body), **context)
            fetch_opts += f", body: JSON.stringify({json.dumps(resolved_body)})"
        fetch_opts += "}"

        js = f"""
        (() => {{
            return fetch('{url}', {fetch_opts})
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
        page = await _get_handle(session_id)
        js = f"""
        (() => {{
            const items = arguments[0];
            return items.filter(item => {{
                const text = typeof item === 'string' ? item : JSON.stringify(item);
                return {params};
            }});
        }})()
        """
        return await page.evaluate(js, data)

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
