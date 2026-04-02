"""认证策略探测 — 逐级探测: PUBLIC → COOKIE → HEADER → INTERCEPT"""
import asyncio
import json
import logging
import random
from typing import Any, Dict, List, Optional
from dataclasses import dataclass

from .explorer import Endpoint

logger = logging.getLogger(__name__)

# 策略级别（从低到高）
STRATEGY_LEVELS = ["public", "cookie", "header", "intercept", "ui"]


@dataclass
class StrategyResult:
    """策略验证结果"""
    strategy: str
    success: bool
    endpoint: str = ""
    sample_size: int = 0
    fields: Dict = None
    notes: str = ""


async def cascade(
    session_id: str,
    url: str,
    endpoints: Optional[List[Endpoint]] = None,
    goal: str = "",
) -> List[StrategyResult]:
    """
    逐级探测认证策略: PUBLIC → COOKIE → HEADER → INTERCEPT

    隐匿性:
      - 每级探测间延迟 1-3 秒
      - 使用浏览器内 fetch（credentials: include）
      - 不注入任何检测脚本
    """
    from ..main import _manager
    session = _manager.get_session(session_id)
    if not session:
        raise ValueError(f"Session {session_id} not found")
    page = session.page

    # 先导航到目标页面（建立 cookie）
    await page.goto(url, wait_until="domcontentloaded", timeout=20000)
    await asyncio.sleep(random.uniform(1, 3))

    results: List[StrategyResult] = []

    # 如果没有提供端点，尝试发现
    test_urls = _get_test_urls(endpoints, url)

    # Level 1: PUBLIC（无 cookie，纯 API）
    r = await _try_public(test_urls, url)
    results.append(r)
    if r.success:
        logger.info(f"Strategy PUBLIC works: {r.endpoint}")
        return results

    await asyncio.sleep(random.uniform(1, 2))

    # Level 2: COOKIE（浏览器内 fetch with credentials）
    r = await _try_cookie(page, test_urls)
    results.append(r)
    if r.success:
        logger.info(f"Strategy COOKIE works: {r.endpoint}")
        return results

    await asyncio.sleep(random.uniform(1, 2))

    # Level 3: HEADER（需要特定 headers）
    r = await _try_header(page, test_urls, url)
    results.append(r)
    if r.success:
        logger.info(f"Strategy HEADER works: {r.endpoint}")
        return results

    await asyncio.sleep(random.uniform(1, 2))

    # Level 4: INTERCEPT（需要完整浏览器渲染）
    r = StrategyResult(
        strategy="intercept",
        success=True,
        notes="Requires full browser rendering + network interception",
    )
    results.append(r)

    return results


def _get_test_urls(endpoints: Optional[List[Endpoint]], base_url: str) -> List[str]:
    """获取测试 URL 列表"""
    if endpoints:
        return [ep.url for ep in endpoints if ep.is_json][:5]
    return []


async def _try_public(test_urls: List[str], base_url: str) -> StrategyResult:
    """Level 1: 公共 API（无认证）"""
    if not test_urls:
        return StrategyResult(strategy="public", success=False, notes="No endpoints to test")

    import aiohttp
    for url in test_urls:
        try:
            async with aiohttp.ClientSession() as http:
                async with http.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        items = _extract_items(data)
                        if items:
                            return StrategyResult(
                                strategy="public",
                                success=True,
                                endpoint=url,
                                sample_size=len(items),
                                fields=_infer_fields(items[0]) if items else {},
                            )
        except Exception:
            continue

    return StrategyResult(strategy="public", success=False, notes="All endpoints require auth")


async def _try_cookie(page, test_urls: List[str]) -> StrategyResult:
    """Level 2: Cookie 认证（浏览器内 fetch）"""
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
            result = await page.evaluate(js)
            if result:
                data = json.loads(result)
                items = _extract_items(data)
                if items:
                    return StrategyResult(
                        strategy="cookie",
                        success=True,
                        endpoint=url,
                        sample_size=len(items),
                        fields=_infer_fields(items[0]) if items else {},
                    )
        except Exception:
            continue

    return StrategyResult(strategy="cookie", success=False, notes="Cookie auth insufficient")


async def _try_header(page, test_urls: List[str], base_url: str) -> StrategyResult:
    """Level 3: 需要特定 Headers（如 Referer, X-Token 等）"""
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
            result = await page.evaluate(js)
            if result:
                data = json.loads(result)
                items = _extract_items(data)
                if items:
                    return StrategyResult(
                        strategy="header",
                        success=True,
                        endpoint=url,
                        sample_size=len(items),
                        fields=_infer_fields(items[0]) if items else {},
                    )
        except Exception:
            continue

    return StrategyResult(strategy="header", success=False, notes="Header auth insufficient")


def _extract_items(data: Any) -> list:
    """从 JSON 响应中提取数据列表"""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("data", "result", "items", "list", "results", "records"):
            val = data.get(key)
            if isinstance(val, list):
                return val
            if isinstance(val, dict):
                # 嵌套一层
                for k2 in ("items", "list", "records"):
                    inner = val.get(k2)
                    if isinstance(inner, list):
                        return inner
    return []


def _infer_fields(item: dict) -> Dict[str, str]:
    """从数据项推断字段角色"""
    fields = {}
    if not isinstance(item, dict):
        return fields
    for key, value in item.items():
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
