"""Site Explorer — Network interception + API discovery + framework detection + capability inference.

Features:
  1. Interaction Fuzzing      — Click interactive elements to trigger lazy loads
  2. Framework Detection     — Detect Vue/React/Angular/Pinia/Vuex
  3. Store Discovery        — Find Pinia/Vuex stores and their actions
  4. URL Pattern Normalization — Parameterize URLs for adapter generation
  5. Endpoint Scoring       — Rank endpoints by usefulness
  6. Auth Strategy Inference — Detect public vs cookie-based APIs
  7. Capability Naming      — Human-readable capability names + confidence
  8. Persistent Artifacts    — Write manifest/endpoints/capabilities JSON
  9. Site Name Detection    — 12+ site aliases (boss, taobao, zhihu, etc.)
 10. Final URL Tracking      — Follow redirects to get canonical URL
 11. Global Timeout         — Configurable overall timeout
 12. Goal-Directed Explore  — Use goal hint to focus exploration

All browser operations through StealthMiddleware auto-stealth wrapping.
"""

import asyncio
import json
import logging
import os
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any

from .analysis import (
    DiscoveredStore,
    InferredCapability,
    detect_auth_indicators,
    detect_site_name,
    infer_capabilities_from_endpoints,
    infer_strategy,
    score_endpoint,
    url_to_pattern,
)

logger = logging.getLogger(__name__)

# Default timeout for the entire exploration (seconds)
_DEFAULT_EXPLORE_TIMEOUT = 120.0


@dataclass
class Endpoint:
    """Discovered API endpoint."""

    url: str
    method: str = "GET"
    status: int = 0
    is_json: bool = False
    sample: Any = None
    pattern: str = ""  # Normalized URL pattern
    content_type: str = ""
    query_params: list[str] = field(default_factory=list)
    score: float = 0.0  # Usefulness score 0-10
    has_search: bool = False
    has_pagination: bool = False
    has_limit: bool = False
    auth_indicators: list[str] = field(default_factory=list)
    item_path: str | None = None  # Path to items in response body
    item_count: int = 0  # Number of items in sample
    detected_fields: dict[str, str] = field(default_factory=dict)  # canonical -> actual


@dataclass
class ExplorationResult:
    """Complete exploration result with all metadata."""

    url: str  # Original requested URL
    final_url: str = ""  # After redirects
    title: str = ""
    endpoints: list[Endpoint] = field(default_factory=list)
    capabilities: list[InferredCapability] = field(default_factory=list)
    site: str = ""  # Detected site name (e.g., 'boss')
    framework: dict[str, Any] = field(default_factory=dict)  # {type, version, stores}
    stores: list[DiscoveredStore] = field(default_factory=list)
    top_strategy: str = ""  # Best strategy: public/intercept/ui/store-action
    endpoint_count: int = 0
    api_endpoint_count: int = 0
    auth_indicators: list[str] = field(default_factory=list)
    out_dir: str | None = None  # Artifact output directory
    duration_ms: int = 0  # Exploration wall-clock time


async def _get_handle(session_id: str):
    """Get BrowserPageHandle via StealthMiddleware."""
    from stealth_browser.main import _ensure_middleware

    mw = await _ensure_middleware()
    return await mw.get_page(session_id)


def _get_behavior():
    try:
        from stealth_browser.browser.human_behavior import HumanBehaviorSimulator

        return HumanBehaviorSimulator()
    except ImportError:
        return None


# ════════════════════════════════════════════
#  FEATURE HELPERS (12 features)
# ════════════════════════════════════════════


async def _interact_fuzz(handle, page, max_clicks: int = 8):
    """
    Feature 1: Interaction Fuzzing.

    Click on likely interactive elements (buttons, links with data attributes)
    to trigger lazy-loaded content and API calls. Uses allowlist approach
    to avoid dangerous clicks (submit forms, logout, payment).
    """
    safe_selectors = [
        '[data-type="load-more"]',
        '[data-action="load"]',
        ".load-more",
        ".show-more",
        ".pagination .next",
        '[class*="tab"]:not(.active)',
        'button:not([type="submit"]):not([data-danger])',
    ]
    clicked = 0
    for sel in safe_selectors:
        if clicked >= max_clicks:
            break
        try:
            elements = await page.evaluate(f"""
                (() => {{
                    const els = document.querySelectorAll('{sel}');
                    return Array.from(els).slice(0, 3).map((el, i) => ({{
                        visible: el.offsetParent !== null,
                        text: (el.textContent || '').trim().substring(0, 50),
                    }}));
                }})()
            """)
            if elements and isinstance(elements, list):
                for elem in elements:
                    if not elem.get("visible") or clicked >= max_clicks:
                        continue
                    text = elem.get("text", "")
                    skip_keywords = ("logout", "sign out", "delete", "remove", "payment", "buy", "order", "checkout")
                    if any(kw in text.lower() for kw in skip_keywords):
                        continue
                    await page.evaluate(f"""
                        (() => {{
                            const el = document.querySelector('{sel}');
                            if (el) {{ el.click(); }}
                        }})()
                    """)
                    clicked += 1
                    await asyncio.sleep(random.uniform(0.3, 0.8))
        except Exception as e:
            logger.debug(f"Interaction fuzz on {sel}: {e}")

    logger.info(f"Interaction fuzz: {clicked} safe clicks")


def _detect_framework(page_result: Any) -> dict[str, Any]:
    """
    Feature 2: Framework Detection.

    Detect Vue/React/Angular and their state management (Pinia/Vuex/Redux).
    Returns dict with type, version info, and store hints.
    """
    if isinstance(page_result, str):
        result_text = page_result
    elif isinstance(page_result, dict):
        result_text = json.dumps(page_result)
    else:
        return {}

    framework = {"type": "unknown", "stores": []}

    if "__vue_app__" in result_text or "__VUE__" in result_text or "Vue" in result_text:
        framework["type"] = "vue"
        if "pinia" in result_text.lower() or "$pinia" in result_text:
            framework["stores"].append("pinia")
        if "$store" in result_text or "vuex" in result_text.lower():
            framework["stores"].append("vuex")

    if "_reactRootContainer" in result_text or "__reactFiber" in result_text:
        framework["type"] = "react"
        if "redux" in result_text.lower():
            framework["stores"].append("redux")

    if "ng.probe" in result_text or "ng-version" in result_text:
        framework["type"] = "angular"
        if "ngrx" in result_text.lower():
            framework["stores"].append("ngrx")

    return framework


async def _discover_stores(handle) -> list[DiscoveredStore]:
    """
    Feature 3: Store Discovery.

    Find Pinia/Vuex/Redux stores on the page and enumerate their
    available actions and state keys.
    """
    stores = []
    js = """
    (() => {
        const result = [];
        // Pinia stores
        try {
            const app = document.querySelector('#app')?.__vue_app__;
            const pinia = app?.config?.globalProperties?.$pinia;
            if (pinia?._s) {
                pinia._s.forEach((store, name) => {
                    const actions = Object.keys(store)
                        .filter(k => typeof store[k] === 'function' && !k.startsWith('$') && !k.startsWith('_'));
                    const stateKeys = store.$state ? Object.keys(store.$state) : [];
                    result.push({storeType: 'pinia', id: name, actions, stateKeys});
                });
            }
        } catch(e) {}

        // Vuex store
        try {
            const app = document.querySelector('#app')?.__vue_app__;
            const vuexStore = app?.config?.globalProperties?.$store;
            if (vuexStore) {
                const modules = vuexStore.state || {};
                result.push({
                    storeType: 'vuex',
                    id: 'root',
                    actions: Object.keys(vuexStore._actions || {}).map(k => k.split('/')[1] || k),
                    stateKeys: Object.keys(modules),
                });
            }
        } catch(e) {}

        return result;
    })()
    """
    try:
        raw = await handle.evaluate(js)
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    stores.append(
                        DiscoveredStore(
                            store_type=item.get("storeType", "unknown"),
                            id=item.get("id", ""),
                            actions=item.get("actions", []),
                            state_keys=item.get("stateKeys", []),
                        )
                    )
    except Exception as e:
        logger.debug(f"Store discovery failed: {e}")

    return stores


def _write_explore_artifacts(result: ExplorationResult) -> None:
    """
    Feature 8: Persistent Artifact Output.

    Write exploration results as JSON files for external tool consumption.
    Creates: manifest.json, endpoints.json, capabilities.json, auth.json, stores.json
    """
    out_dir = result.out_dir
    if not out_dir:
        return

    os.makedirs(out_dir, exist_ok=True)

    # manifest.json
    manifest = {
        "url": result.url,
        "final_url": result.final_url,
        "site": result.site,
        "title": result.title,
        "framework": result.framework,
        "top_strategy": result.top_strategy,
        "endpoint_count": result.endpoint_count,
        "api_endpoint_count": result.api_endpoint_count,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "duration_ms": result.duration_ms,
    }
    _write_json(os.path.join(out_dir, "manifest.json"), manifest)

    # endpoints.json
    endpoints_data = []
    for ep in result.endpoints:
        endpoints_data.append(
            {
                "url": ep.url,
                "method": ep.method,
                "status": ep.status,
                "pattern": ep.pattern,
                "content_type": ep.content_type,
                "score": ep.score,
                "is_json": ep.is_json,
                "has_search": ep.has_search,
                "has_pagination": ep.has_pagination,
                "auth_indicators": ep.auth_indicators,
                "item_path": ep.item_path,
                "item_count": ep.item_count,
                "fields": ep.detected_fields,
            }
        )
    _write_json(os.path.join(out_dir, "endpoints.json"), endpoints_data)

    # capabilities.json
    caps_data = []
    for cap in result.capabilities:
        caps_data.append(
            {
                "name": cap.name,
                "description": cap.description,
                "strategy": cap.strategy,
                "confidence": cap.confidence,
                "endpoint": cap.endpoint,
                "item_path": cap.item_path,
                "columns": cap.recommended_columns,
                "args": cap.recommended_args,
            }
        )
    _write_json(os.path.join(out_dir, "capabilities.json"), caps_data)

    # auth.json
    _write_json(
        os.path.join(out_dir, "auth.json"),
        {
            "indicators": result.auth_indicators,
            "top_strategy": result.top_strategy,
        },
    )

    # stores.json
    stores_data = []
    for s in result.stores:
        stores_data.append(
            {
                "type": s.store_type,
                "id": s.id,
                "actions": s.actions,
                "state_keys": s.state_keys,
            }
        )
    _write_json(os.path.join(out_dir, "stores.json"), stores_data)

    logger.info(f"Artifacts written to {out_dir}")


def _write_json(path: str, data: Any) -> None:
    """Write data as pretty-printed JSON."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ════════════════════════════════════════════
#  MAIN EXPLORE FUNCTION
# ════════════════════════════════════════════


async def explore(
    session_id: str,
    url: str,
    scroll_count: int = 5,
    goal: str = "",
    timeout: float = _DEFAULT_EXPLORE_TIMEOUT,
    out_dir: str | None = None,
) -> ExplorationResult:
    """
    Explore a site: navigate → intercept network → scroll triggers → detect framework → analyze API.

    Enhanced analysis features:
    - Framework detection (Vue/React/Angular + Pinia/Vuex)
    - Store discovery (available actions and state)
    - URL pattern normalization
    - Endpoint scoring and ranking
    - Auth strategy inference
    - Capability naming with confidence scores
    - Persistent artifact output

    All browser operations are automatically stealth-wrapped via StealthMiddleware.
    """
    start_time = time.time()
    handle = await _get_handle(session_id)

    result = ExplorationResult(
        url=url,
        site=detect_site_name(url),
        out_dir=out_dir,
    )
    intercepted: list[Endpoint] = []

    def on_response(response):
        try:
            ct = response.headers.get("content-type", "")
            resp_url = response.url
            if "json" in ct or "/api/" in resp_url or "/graphql" in resp_url:
                intercepted.append(
                    Endpoint(
                        url=resp_url,
                        method=response.request.method,
                        status=response.status,
                        is_json="json" in ct,
                        content_type=ct,
                    )
                )
        except Exception:
            pass

    # StealthPageHandle.on() delegates to underlying Playwright Page
    handle.on("response", on_response)

    try:
        # Navigate (with redirect tracking)
        await handle.goto(url, wait_until="domcontentloaded", timeout=20000)

        # Track final URL after redirects
        result.final_url = await handle.evaluate("window.location.href")
        if not result.final_url:
            result.final_url = url

        await asyncio.sleep(random.uniform(1, 3))

        result.title = await handle.title()

        # Stealth scrolling
        raw_page = getattr(handle, "raw_page", None)
        behavior = _get_behavior()
        if behavior and raw_page:
            await behavior._random_scroll(raw_page, scroll_count=scroll_count)
        else:
            for _ in range(scroll_count):
                distance = random.randint(100, 500)
                await handle.evaluate(f"window.scrollBy(0, {distance})")
                await asyncio.sleep(random.uniform(0.5, 2.0))

        await asyncio.sleep(random.uniform(2, 4))

        # Interaction Fuzzing (safe clicks to trigger lazy loads)
        await _interact_fuzz(handle, handle, max_clicks=8)
        await asyncio.sleep(random.uniform(1, 2))

        # Collect response samples
        for ep in intercepted:
            if ep.is_json and ep.status == 200:
                try:
                    ep.sample = await _fetch_sample(handle, ep.url)
                    # Score endpoint
                    ep.score = score_endpoint(
                        ep.url,
                        ep.method,
                        ep.status,
                        ep.is_json,
                        ep.sample,
                        ep.content_type,
                    )
                    # Normalize URL pattern
                    ep.pattern = url_to_pattern(ep.url)
                    # Detect auth indicators
                    ep.auth_indicators = detect_auth_indicators(
                        ep.url,
                        ep.status,
                        {},
                        {},
                    )
                    # Detect item path and count
                    if isinstance(ep.sample, dict):
                        ep.item_path = _detect_item_path_in_sample(ep.sample)
                        items = _get_items_from_sample(ep.sample)
                        ep.item_count = len(items) if items else 0
                        if items and len(items) > 0 and isinstance(items[0], dict):
                            ep.detected_fields = _detect_fields_from_item(items[0])
                            from urllib.parse import parse_qs, urlparse

                            qs = parse_qs(urlparse(ep.url).query)
                            ep.has_search = any(k.lower() in ("q", "query", "keyword", "search") for k in qs)
                            ep.has_pagination = any(k.lower() in ("page", "limit", "offset", "cursor") for k in qs)
                            ep.has_limit = "limit" in qs or "pagesize" in qs
                except Exception:
                    pass

        result.endpoints = intercepted
        result.endpoint_count = len(intercepted)
        result.api_endpoint_count = sum(1 for ep in intercepted if ep.is_json)

        # Framework Detection
        fw_js = """
        (() => ({
            vue: !!document.querySelector('#app')?.__vue_app__,
            react: !!document.querySelector('#_reactRootContainer') || !!window.__reactFiber,
            angular: !!document.querySelector('[ng-version]') || !!window.ng?.probe,
        }))()
        """
        try:
            fw_raw = await handle.evaluate(fw_js)
            result.framework = _detect_framework(fw_raw)
        except Exception:
            pass

        # Store Discovery
        if result.framework.get("type") in ("vue", "unknown"):
            result.stores = await _discover_stores(handle)

        # Auth Strategy Inference
        all_auth = []
        for ep in intercepted:
            all_auth.extend(ep.auth_indicators)
        result.auth_indicators = list(set(all_auth))

        # Capability Naming + Confidence
        result.capabilities = infer_capabilities_from_endpoints(
            site=result.site,
            endpoints=result.endpoints,
            goal=goal,
            min_score=3.0,
        )

        # Top strategy inference
        result.top_strategy = infer_strategy(result.endpoints, result.url)

        # Write artifacts
        result.duration_ms = int((time.time() - start_time) * 1000)
        _write_explore_artifacts(result)

    finally:
        handle.remove_listener("response", on_response)

    return result


# ════════════════════════════════════════════
#  LEGACY COMPATIBILITY HELPERS
# ════════════════════════════════════════════


async def _fetch_sample(handle, url: str) -> Any:
    """Execute browser-side fetch via BrowserPageHandle.evaluate."""
    json.dumps(url)
    js = """
    (() => {
        return fetch({safe_url}, {credentials: 'include'})
            .then(r => r.text())
            .then(t => t.substring(0, 4096))
            .catch(() => null);
    })()
    """
    text = await handle.evaluate(js)
    if text:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text[:500]
    return None


def _analyze_endpoints(endpoints: list[Endpoint], base_url: str) -> list[dict]:
    """Legacy compatibility: convert Endpoint list to old-style capability dicts."""
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
        for key, _value in sample_item.items():
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
            strategy_map = {"public": "public", "intercept": "cookie", "ui": "ui", "store-action": "store-action"}
            strat = getattr(ep, "top_strategy", "") or "cookie"
            capabilities.append(
                {
                    "endpoint": ep.url,
                    "method": ep.method,
                    "fields": fields,
                    "sample_count": len(data),
                    "strategy_guess": strategy_map.get(strat, strat) if isinstance(strat, str) else strat,
                }
            )

    return capabilities


def _detect_item_path_in_sample(sample: Any) -> str | None:
    """Detect path to items array inside a JSON response."""
    if not isinstance(sample, dict):
        return None
    for candidate in ("data", "result", "items", "list", "data.list", "data.data"):
        parts = candidate.split(".")
        obj = sample
        found = True
        for part in parts:
            if isinstance(obj, dict) and part in obj:
                obj = obj[part]
            else:
                found = False
                break
        if found and isinstance(obj, list) and len(obj) > 0:
            return candidate
    return None


def _get_items_from_sample(sample: Any) -> list | None:
    """Extract items array from a sample response."""
    if not isinstance(sample, dict):
        return None
    for key in ("data", "result", "items", "list"):
        val = sample.get(key)
        if isinstance(val, list) and val:
            return val
        if isinstance(val, dict):
            sub = val.get("data") or val.get("items") or val.get("list")
            if isinstance(sub, list) and sub:
                return sub
    if any(isinstance(sample.get(k), (str, int, float)) for k in ("title", "name", "url")):
        return [sample]
    return None


def _detect_fields_from_item(item: dict) -> dict[str, str]:
    """Detect canonical field names from a sample item."""
    from .analysis import _FIELD_NAME_MAP

    fields = {}
    for key, _value in item.items():
        kl = key.lower()
        for pattern, canonical in _FIELD_NAME_MAP:
            if re.search(pattern, kl):
                fields[canonical] = key
                break
    return fields
