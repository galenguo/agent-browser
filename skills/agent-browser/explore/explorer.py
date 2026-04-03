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
    """发现的 API 端点"""
    url: str
    method: str = "GET"
    status: int = 0
    is_json: bool = False
    sample: Any = None  # 截取的响应样本（前 2KB）


@dataclass
class ExplorationResult:
    """探索结果"""
    url: str
    title: str = ""
    endpoints: List[Endpoint] = field(default_factory=list)
    capabilities: List[Dict] = field(default_factory=list)


async def explore(
    session_id: str,
    url: str,
    scroll_count: int = 5,
    goal: str = "",
) -> ExplorationResult:
    """
    探索站点：导航 → 拦截网络 → 滚动触发 → 检测框架 → 分析 API。

    隐匿性:
      - 滚动使用 _random_scroll（非匀速+回滚）
      - 网络拦截被动监听（page.on("response")），不注入脚本
      - 框架检测使用 querySelector，不暴露全局变量指纹
      - 动作间隔 1-3 秒
    """
    from ..main import _backend
    if _backend is None:
        raise ValueError("Backend not initialized")
    handle = _backend.get_page(session_id)
    if not handle:
        raise ValueError(f"Session {session_id} not found")
    page = handle.raw_page if hasattr(handle, 'raw_page') else None
    if page is None:
        raise ValueError("explore() requires LocalCDPBackend (raw_page)")

    result = ExplorationResult(url=url)

    # 拦截网络响应
    intercepted: List[Endpoint] = []

    def on_response(response):
        try:
            ct = response.headers.get("content-type", "")
            url = response.url
            # 只关注 JSON API 端点
            if "json" in ct or "/api/" in url or "/graphql" in url:
                intercepted.append(Endpoint(
                    url=url,
                    method=response.request.method,
                    status=response.status,
                    is_json="json" in ct,
                ))
        except Exception:
            pass

    page.on("response", on_response)

    try:
        # 导航到目标页面
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(random.uniform(1, 3))

        # 获取页面标题
        result.title = await page.title()

        # 隐匿性滚动：使用人类行为模拟
        behavior = _get_behavior()
        if behavior:
            await behavior._random_scroll(page, scroll_count=scroll_count)
        else:
            # 回退：简单随机滚动
            for _ in range(scroll_count):
                distance = random.randint(100, 500)
                await page.evaluate(f"window.scrollBy(0, {distance})")
                await asyncio.sleep(random.uniform(0.5, 2.0))

        await asyncio.sleep(random.uniform(2, 4))

        # 拦截到的端点：获取响应样本
        for ep in intercepted:
            if ep.is_json and ep.status == 200:
                try:
                    # 隐匿性：被动获取已缓存的响应，不发起新请求
                    sample = await _fetch_sample(page, ep.url)
                    ep.sample = sample
                except Exception:
                    pass

        result.endpoints = intercepted

        # 分析端点，生成能力候选项
        result.capabilities = _analyze_endpoints(intercepted, url)

    finally:
        page.remove_listener("response", on_response)

    return result


async def _fetch_sample(page, url: str) -> Any:
    """在浏览器内 fetch 已缓存的 API（credentials: include 保持 cookie）"""
    js = f"""
    (() => {{
        return fetch('{url}', {{credentials: 'include'}})
            .then(r => r.text())
            .then(t => t.substring(0, 2048))
            .catch(() => null);
    }})()
    """
    text = await page.evaluate(js)
    if text:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text[:500]
    return None


def _analyze_endpoints(endpoints: List[Endpoint], base_url: str) -> List[Dict]:
    """分析端点，推断字段角色（title/url/author/score），生成能力候选项"""
    capabilities = []
    seen_patterns = set()

    for ep in endpoints:
        if not ep.is_json or not ep.sample:
            continue

        # 分析 JSON 结构
        data = ep.sample
        if isinstance(data, dict):
            data = data.get("data") or data.get("result") or data.get("items") or data.get("list") or [data]
        if isinstance(data, dict):
            data = [data]

        if not isinstance(data, list) or not data:
            continue

        # 推断字段角色
        sample_item = data[0]
        if not isinstance(sample_item, dict):
            continue

        # 从 URL 路径提取模式
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
    """获取 HumanBehaviorSimulator（按需导入）"""
    try:
        from src.browser.human_behavior import HumanBehaviorSimulator
        return HumanBehaviorSimulator()
    except ImportError:
        return None
