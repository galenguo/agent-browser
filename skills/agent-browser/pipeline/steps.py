"""Pipeline Step 处理器 — 所有浏览器操作经过隐匿性封装"""
import asyncio
import json
import random
from typing import Any, Callable, Dict

from .template import resolve

# Step 处理器注册表
STEPS: Dict[str, Callable] = {}


def register(name: str):
    """注册 step 处理器装饰器"""
    def decorator(fn: Callable) -> Callable:
        STEPS[name] = fn
        return fn
    return decorator


def _get_page(session_id: str):
    """从全局 SessionManager 获取 page 对象"""
    from ..main import _manager
    session = _manager.get_session(session_id)
    if not session:
        raise ValueError(f"Session {session_id} not found")
    return session.page


async def _stealth_delay(stealth: dict, key: str = "default"):
    """隐匿性延迟"""
    delay_range = stealth.get("request_delay", [0.3, 1.5])
    await asyncio.sleep(random.uniform(delay_range[0], delay_range[1]))


# ─── 浏览器 Steps ─────────────────────────────────────────


@register("navigate")
async def step_navigate(session_id: str, params: Any, data: Any,
                        context: dict, stealth: dict) -> Any:
    """导航到 URL（含隐匿性行为模拟）"""
    url = resolve(str(params), **context)
    page = _get_page(session_id)

    # 隐匿性：导航前随机延迟
    await _stealth_delay(stealth)

    await page.goto(url, wait_until="domcontentloaded", timeout=20000)

    return data


@register("evaluate")
async def step_evaluate(session_id: str, params: Any, data: Any,
                        context: dict, stealth: dict) -> Any:
    """在浏览器中执行 JS"""
    js_code = resolve(str(params), **context)
    page = _get_page(session_id)

    result = await page.evaluate(js_code)
    return result


@register("click")
async def step_click(session_id: str, params: Any, data: Any,
                     context: dict, stealth: dict) -> Any:
    """点击选择器（含隐匿性悬停+延迟）"""
    selector = resolve(str(params), **context)
    page = _get_page(session_id)

    loc = page.locator(selector)
    if await loc.count() > 0:
        await loc.first.hover()
        await asyncio.sleep(random.uniform(0.2, 0.8))
        await loc.first.click()
        await asyncio.sleep(random.uniform(0.3, 1.0))
    else:
        await page.click(selector)
        await asyncio.sleep(random.uniform(0.3, 0.8))

    return data


@register("type")
async def step_type(session_id: str, params: Any, data: Any,
                    context: dict, stealth: dict) -> Any:
    """输入文本（含隐匿性人类打字模拟）"""
    if isinstance(params, dict):
        selector = resolve(str(params.get("selector", "")), **context)
        text = resolve(str(params.get("text", "")), **context)
    else:
        # 简化格式: {"type": {"selector": "...", "text": "..."}}
        raise ValueError("type step requires {selector, text} dict")

    page = _get_page(session_id)

    loc = page.locator(selector)
    await loc.click()
    await page.keyboard.type(text, delay=30)

    return data


@register("wait")
async def step_wait(session_id: str, params: Any, data: Any,
                    context: dict, stealth: dict) -> Any:
    """等待（秒数或文本出现）"""
    page = _get_page(session_id)

    if isinstance(params, (int, float)):
        await asyncio.sleep(float(params))
    elif isinstance(params, str):
        resolved = resolve(params, **context)
        try:
            await asyncio.sleep(float(resolved))
        except ValueError:
            # 当作选择器等待
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
    HTTP 请求（串行 + 随机延迟，禁止并发）。

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

    # 隐匿性：请求间随机延迟
    await _stealth_delay(stealth)

    if use_browser:
        # 浏览器内 fetch（保持 cookie 和 session）
        page = _get_page(session_id)
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
        # Python 原生 HTTP（公共 API 场景）
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
    """选取 JSON 子路径或浏览器 DOM 元素"""
    if isinstance(params, str):
        # 浏览器 DOM 选择器
        js_selector = resolve(params, **context)
        page = _get_page(session_id)

        # 隐匿性延迟
        await _stealth_delay(stealth)

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

    # dict 格式: {path: "data.items"}
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
    """数据映射重塑"""
    if not isinstance(data, list):
        if isinstance(data, dict):
            data = [data]
        else:
            return data

    if not isinstance(params, dict):
        return data

    # 浏览器端 map: 使用 JS 模板在 DOM 元素上提取字段
    # 检查是否有 querySelector 等浏览器操作
    first_val = next(iter(params.values()), "")
    if isinstance(first_val, str) and "querySelector" in first_val:
        # 这是浏览器 DOM 映射，已在 select step 处理
        # 这里做字段映射
        page = _get_page(session_id)
        mapping_js = {}
        for key, tmpl in params.items():
            mapping_js[key] = tmpl

        js = f"""
        (() => {{
            const items = arguments[0];
            const mapping = {json.dumps(mapping_js)};
            return items.map((item, index) => {{
                const result = {{}};
                for (const [key, tmpl] of Object.entries(mapping)) {{
                    // 简单文本替换模板
                    let val = tmpl;
                    val = val.replace(/\\${{\\{{\\s*index\\s*\\}}}}/g, index + 1);
                    val = val.replace(/\\${{\\{{\\s*item\\.([\\w.]+)\\s*\\}}}}/g,
                        (_, path) => path.split('.').reduce((o, k) => o?.[k], item) || '');
                    result[key] = val;
                }}
                return result;
            }});
        }})()
        """
        return await page.evaluate(js, data)

    # 纯数据映射（无浏览器依赖）
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
    """条件过滤"""
    if not isinstance(data, list):
        return data

    if isinstance(params, str):
        # JS 过滤表达式
        page = _get_page(session_id)
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
    """截断到 N 条"""
    if isinstance(params, str):
        n = int(resolve(params, **context))
    else:
        n = int(params)

    if isinstance(data, list):
        return data[:n]
    return data

