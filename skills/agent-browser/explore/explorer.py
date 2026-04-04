"""站点探索器 — 网络拦截 + API 发现 + 框架检测"""
import asyncio
import json
import logging
import random
from typing import Any, Dict, List
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class Endpoint:
    url: str
    method: str = "GET"
    status: int = 0
    is_json: bool = False
    sample: Any = None


@dataclass
class ExplorationResult:
    url: str
    title: str = ""
    endpoints: List[Endpoint] = field(default_factory=list)
    capabilities: List[Dict] = field(default_factory=list)


async def _get_handle(session_id: str):
    """通过 StealthMiddleware 获取 BrowserPageHandle"""
    from ..main import _ensure_middleware
    mw = await _ensure_middleware()
    return await mw.get_page(session_id)


async def explore(
    session_id: str,
    url: str,
    scroll_count: int = 5,
    goal: str = "",
) -> ExplorationResult:
    """
    探索站点：导航 → 拦截网络 → 滚动触发 → 检测框架 → 分析 API。

    所有浏览器操作通过 StealthMiddleware 自动隐匿。
    """
    handle = await _get_handle(session_id)

    result = ExplorationResult(url=url)
    intercepted: List[Endpoint] = []

    def on_response(response):
        try:
            ct = response.headers.get("content-type", "")
            resp_url = response.url
            if "json" in ct or "/api/" in resp_url or "/graphql" in resp_url:
                intercepted.append(Endpoint(
                    url=resp_url,
                    method=response.request.method,
                    status=response.status,
                    is_json="json" in ct,
                ))
        except Exception:
            pass

    # StealthPageHandle.on() 委托给底层 Playwright Page
    handle.on("response", on_response)

    try:
        # 导航（StealthPageHandle.goto 自动注入隐匿延迟）
        await handle.goto(url, wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(random.uniform(1, 3))

        result.title = await handle.title()

        # 隐匿性滚动
        raw_page = getattr(handle, 'raw_page', None)
        behavior = _get_behavior()
        if behavior and raw_page:
            await behavior._random_scroll(raw_page, scroll_count=scroll_count)
        else:
            for _ in range(scroll_count):
                distance = random.randint(100, 500)
                await handle.evaluate(f"window.scrollBy(0, {distance})")
                await asyncio.sleep(random.uniform(0.5, 2.0))

        await asyncio.sleep(random.uniform(2, 4))

        # 获取响应样本
        for ep in intercepted:
            if ep.is_json and ep.status == 200:
                try:
                    ep.sample = await _fetch_sample(handle, ep.url)
                except Exception:
                    pass

        result.endpoints = intercepted
        result.capabilities = _analyze_endpoints(intercepted, url)

    finally:
        handle.remove_listener("response", on_response)

    return result


async def _fetch_sample(handle, url: str) -> Any:
    """通过 BrowserPageHandle.evaluate 执行浏览器内 fetch"""
    js = f"""
    (() => {{
        return fetch('{url}', {{credentials: 'include'}})
            .then(r => r.text())
            .then(t => t.substring(0, 2048))
            .catch(() => null);
    }})()
    """
    text = await handle.evaluate(js)
    if text:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text[:500]
    return None


def _analyze_endpoints(endpoints: List[Endpoint], base_url: str) -> List[Dict]:
    capabilities = []
    seen_patterns = set()

    for ep in endpoints:
        if not ep.is_json or not ep.sample:
            continue

        data = ep.sample
        if isinstance(data, dict):
            data = data.get("data") or data.get("result") or data.get("items") or data.get("list") or [data]
        if isinstance(data, dict):
            data = [data]

        if not isinstance(data, list) or not data:
            continue

        sample_item = data[0]
        if not isinstance(sample_item, dict):
            continue

        from urllib.parse import urlparse
        path = urlparse(ep.url).path
        pattern_key = f"{path}:{ep.method}"
        if pattern_key in seen_patterns:
            continue
        seen_patterns.add(pattern_key)

        fields = {}
        for key, value in sample_item.items():
            kl = key.lower()
            if any(t in kl for t in ["title", "name", "headline"]):
                fields["title"] = key
            elif any(t in kl for t in ["url", "link", "href"]):
                fields["url"] = key
            elif any(t in kl for t in ["author", "user", "nick"]):
                fields["author"] = key
            elif any(t in kl for t in ["score", "hot", "rank", "count", "view"]):
                fields["score"] = key
            elif any(t in kl for t in ["desc", "summary", "abstract", "excerpt"]):
                fields["description"] = key
            elif any(t in kl for t in ["img", "pic", "thumb", "cover", "avatar"]):
                fields["image"] = key
            elif any(t in kl for t in ["time", "date", "created", "pub"]):
                fields["time"] = key
            elif any(t in kl for t in ["id", "key"]):
                fields["id"] = key

        if len(fields) >= 2:
            capabilities.append({
                "endpoint": ep.url,
                "method": ep.method,
                "fields": fields,
                "sample_count": len(data),
                "strategy_guess": "public" if ep.status == 200 else "cookie",
            })

    return capabilities


def _get_behavior():
    try:
        from src.browser.human_behavior import HumanBehaviorSimulator
        return HumanBehaviorSimulator()
    except ImportError:
        return None
