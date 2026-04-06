"""Auth Strategy Probe — Progressive detection: PUBLIC → COOKIE → HEADER → INTERCEPT.

Each level tries a different authentication approach until one succeeds.
Stealth is automatically handled by StealthMiddleware (navigation delays,
evaluate passthrough).
"""

import asyncio
import json
import logging
import random
from typing import Any

logger = logging.getLogger(__name__)

STRATEGY_LEVELS = ["public", "cookie", "header", "intercept", "ui"]


async def _get_handle(session_id: str):
    """Get BrowserPageHandle via StealthMiddleware."""
    from agent_browser.main import _ensure_middleware

    mw = await _ensure_middleware()
    return await mw.get_page(session_id)


async def cascade(
    session_id: str,
    url: str,
    endpoints: list[Any] | None = None,
    goal: str = "",
) -> list[dict[str, Any]]:
    """
    Progressive auth strategy detection: PUBLIC → COOKIE → HEADER → INTERCEPT

    Stealth is automatically handled via StealthMiddleware (navigation delays,
    evaluate passthrough).
    """
    handle = await _get_handle(session_id)

    # Navigate to target page (StealthPageHandle.goto auto-injects stealth delays)
    await handle.goto(url, wait_until="domcontentloaded", timeout=20000)
    await asyncio.sleep(random.uniform(1, 3))

    results: list[dict[str, Any]] = []
    test_urls = _get_test_urls(endpoints, url)

    # Level 1: PUBLIC (no cookie, pure API)
    r = await _try_public(test_urls, url)
    results.append(r)
    if r["success"]:
        logger.info(f"Strategy PUBLIC works: {r['endpoint']}")
        return results

    await asyncio.sleep(random.uniform(1, 2))

    # Level 2: COOKIE (browser fetch with credentials)
    r = await _try_cookie(handle, test_urls)
    results.append(r)
    if r["success"]:
        logger.info(f"Strategy COOKIE works: {r['endpoint']}")
        return results

    await asyncio.sleep(random.uniform(1, 2))

    # Level 3: HEADER (specific headers needed)
    r = await _try_header(handle, test_urls, url)
    results.append(r)
    if r["success"]:
        logger.info(f"Strategy HEADER works: {r['endpoint']}")
        return results

    await asyncio.sleep(random.uniform(1, 2))

    # Level 4: INTERCEPT (full browser rendering required)
    results.append(
        {
            "strategy": "intercept",
            "success": True,
            "endpoint": "",
            "sample_size": 0,
            "fields": None,
            "notes": "Requires full browser rendering + network interception",
        }
    )

    return results


def _get_test_urls(endpoints: list[Any] | None, base_url: str) -> list[str]:
    if endpoints:
        return [ep.url for ep in endpoints if ep.is_json][:5]
    return []


async def _try_public(test_urls: list[str], base_url: str) -> dict[str, Any]:
    """Level 1: Public API (no authentication)."""
    if not test_urls:
        return {
            "strategy": "public",
            "success": False,
            "endpoint": "",
            "sample_size": 0,
            "fields": None,
            "notes": "No endpoints to test",
        }

    import aiohttp

    for url in test_urls:
        try:
            async with (
                aiohttp.ClientSession() as http,
                http.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp,
            ):
                if resp.status == 200:
                    data = await resp.json()
                    items = _extract_items(data)
                    if items:
                        return {
                            "strategy": "public",
                            "success": True,
                            "endpoint": url,
                            "sample_size": len(items),
                            "fields": _infer_fields(items[0]) if items else {},
                            "notes": "",
                        }
        except Exception:
            continue

    return {
        "strategy": "public",
        "success": False,
        "endpoint": "",
        "sample_size": 0,
        "fields": None,
        "notes": "All endpoints require auth",
    }


async def _try_cookie(handle, test_urls: list[str]) -> dict[str, Any]:
    """Level 2: Cookie auth (browser-side fetch)."""
    for url in test_urls:
        try:
            js = f"""
            (() => {{
                return fetch('{url}', {{credentials: 'include'}})
                    .then(r => r.json())
                    .then(data => JSON.stringify(data).substring(0, 4096))
                    .catch(() => null);
            }})()
            """
            result = await handle.evaluate(js)
            if result:
                data = json.loads(result)
                items = _extract_items(data)
                if items:
                    return {
                        "strategy": "cookie",
                        "success": True,
                        "endpoint": url,
                        "sample_size": len(items),
                        "fields": _infer_fields(items[0]) if items else {},
                        "notes": "",
                    }
        except Exception:
            continue

    return {
        "strategy": "cookie",
        "success": False,
        "endpoint": "",
        "sample_size": 0,
        "fields": None,
        "notes": "Cookie auth insufficient",
    }


async def _try_header(handle, test_urls: list[str], base_url: str) -> dict[str, Any]:
    """Level 3: Specific Headers needed (Referer, X-Token, etc.)."""
    parsed_base = base_url.split("?")[0]

    for url in test_urls:
        try:
            js = f"""
            (() => {{
                return fetch('{url}', {{
                    credentials: 'include',
                    headers: {{
                        'Referer': '{parsed_base}',
                        'Accept': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest'
                    }}
                }})
                .then(r => r.json())
                .then(data => JSON.stringify(data).substring(0, 4096))
                .catch(() => null);
            }})()
            """
            result = await handle.evaluate(js)
            if result:
                data = json.loads(result)
                items = _extract_items(data)
                if items:
                    return {
                        "strategy": "header",
                        "success": True,
                        "endpoint": url,
                        "sample_size": len(items),
                        "fields": _infer_fields(items[0]) if items else {},
                        "notes": "",
                    }
        except Exception:
            continue

    return {
        "strategy": "header",
        "success": False,
        "endpoint": "",
        "sample_size": 0,
        "fields": None,
        "notes": "Header auth insufficient",
    }


def _extract_items(data: Any) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("data", "result", "items", "list", "results", "records"):
            val = data.get(key)
            if isinstance(val, list):
                return val
            if isinstance(val, dict):
                for k2 in ("items", "list", "records"):
                    inner = val.get(k2)
                    if isinstance(inner, list):
                        return inner
    return []


def _infer_fields(item: dict) -> dict[str, str]:
    fields = {}
    if not isinstance(item, dict):
        return fields
    for key, _value in item.items():
        kl = key.lower()
        if any(t in kl for t in ["title", "name"]):
            fields["title"] = key
        elif any(t in kl for t in ["url", "link"]):
            fields["url"] = key
        elif any(t in kl for t in ["desc", "summary"]):
            fields["description"] = key
        elif any(t in kl for t in ["author", "user"]):
            fields["author"] = key
        elif any(t in kl for t in ["score", "hot", "count"]):
            fields["score"] = key
    return fields
