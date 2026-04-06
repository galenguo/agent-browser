"""Exploration Analysis — Pure functions for endpoint/capability analysis.

No browser dependency — all functions are deterministic and testable.

Provides:
  - URL pattern normalization (parameterized → template)
  - Query parameter classification (search, pagination, auth)
  - Auth strategy detection from endpoint characteristics
  - Endpoint scoring (relevance ranking)
  - Capability naming and confidence inference
"""
import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

# ── Dataclasses ──


@dataclass
class DiscoveredStore:
    """A discovered client-side state store (Pinia/Vuex/Redux)."""
    store_type: str           # 'pinia', 'vuex', 'redux', 'unknown'
    id: str                  # Store identifier
    actions: list[str]        # Available action names
    state_keys: list[str]     # Observable state keys


@dataclass
class InferredCapability:
    """An inferred capability (what the user can do via this endpoint)."""
    name: str                        # Human-readable name, e.g., "search_jobs"
    description: str                 # What it does
    strategy: str                    # 'public', 'intercept', 'ui', 'store-action'
    confidence: float                # 0.0-1.0
    endpoint: str | None = None   # Primary endpoint URL
    item_path: str | None = None  # Path to items in response (e.g., "data.list")
    recommended_columns: list[str] = None  # Suggested output columns
    recommended_args: dict[str, str] = None  # Suggested input arguments
    store_hint: str | None = None     # Store info if store-action


# ── URL Normalization ──

# Patterns that look like IDs (numeric or UUID-like)
_ID_PATTERN = re.compile(r'^[0-9a-fA-F]{8,}-[0-9a-fA-F]{4,}|^\d{5,}$')
_NUMERIC_PARAM = re.compile(r'^\d+$')


def url_to_pattern(url: str) -> str:
    """
    Convert a concrete URL to a parameterized pattern.

    Example:
      https://api.example.com/users/12345/posts?w_rid=abc&limit=20
      → https://api.example.com/users/{id}/posts?w_rid={w_rid}&limit={limit}

    Rules:
      - Numeric path segments (>4 digits) → {id}
      - UUID-like segments → {id}
      - Short alphanumeric query params → keep as-is (likely search terms)
      - Numeric query params → {param_name}
    """
    parsed = urlparse(url)
    path_parts = parsed.path.split("/")

    normalized_path = []
    for part in path_parts:
        if _ID_PATTERN.match(part) or _NUMERIC_PARAM.match(part) and len(part) > 2:
            normalized_path.append("{id}")
        else:
            normalized_path.append(part)

    # Normalize query parameters
    params = parse_qs(parsed.query, keep_blank_values=True)
    normalized_params = []
    for key, values in params.items():
        for val in values:
            if _NUMERIC_PARAM.match(val) or len(val) > 20:
                normalized_params.append(f"{key}={{{key}}}")
            else:
                normalized_params.append(f"{key}={val}")  # Keep search terms as-is

    result = "/".join(normalized_path)
    if normalized_params:
        result += "?" + "&".join(normalized_params)

    return result


# ── Parameter Classification ──

# Known pagination parameter names
_PAGINATION_PARAMS = {
    'page', 'pagesize', 'page_size', 'limit', 'offset',
    'cursor', 'after', 'before', 'start', 'count', 'per_page',
}

# Known search/query parameter names
_SEARCH_PARAMS = {
    'q', 'query', 'keyword', 'keywords', 'search', 's', 'term',
    'text', 'filter', 'where', 'match', 'query_string',
}

# Known auth-related parameter names (should NOT be sent as user args)
_AUTH_PARAMS = {
    'token', 'access_token', 'auth', 'key', 'api_key', 'apikey',
    'session', 'sid', 'csrf', '_t', 'signature', 'timestamp',
}


def classify_param(name: str) -> str:
    """Classify a query parameter by its likely purpose."""
    lower = name.lower().strip()
    if lower in _PAGINATION_PARAMS:
        return "pagination"
    if lower in _SEARCH_PARAMS:
        return "search"
    if lower in _AUTH_PARAMS:
        return "auth"
    return "unknown"


def has_pagination(params: dict[str, str]) -> bool:
    """Check if params contain known pagination indicators."""
    return any(classify_param(k) == "pagination" for k in params)


def has_search(params: dict[str, str]) -> bool:
    """Check if params contain known search indicators."""
    return any(classify_param(k) == "search" for k in params)


# ── Auth Detection ──

_AUTH_HEADERS = {
    'authorization', 'x-auth-token', 'x-api-key', 'cookie',
    'x-csrf-token', 'authentication',
}


def detect_auth_indicators(
    url: str,
    status_code: int,
    headers: dict[str, str],
    query_params: dict[str, str],
) -> list[str]:
    """
    Detect authentication indicators from request/response metadata.

    Returns list of detected auth mechanism names.
    """
    indicators = []

    # Header-based auth
    lower_headers = {k.lower(): v for k, v in headers.items()}
    for header in _AUTH_HEADERS:
        if header in lower_headers:
            indicators.append(f"header:{header}")

    # Status code hints
    if status_code in (401, 403):
        indicators.append("status:auth_required")

    # Query param auth tokens
    for param in query_params:
        if classify_param(param) == "auth":
            indicators.append(f"param:{param}")

    # Cookie-based (common for sites like zhipin/boss)
    if 'cookie' in lower_headers or 'set-cookie' in lower_headers:
        indicators.append("cookie")

    return indicators


def infer_strategy(
    endpoints: list[Any],
    url: str,
) -> str:
    """
    Infer the best data access strategy from exploration results.

    Returns one of: 'public', 'intercept', 'ui', 'store-action'

    Priority:
      1. store-action (if Vue/Pinia detected)
      2. public (200 OK, no auth needed)
      3. intercept (needs cookies/auth headers)
      4. ui (fallback DOM scraping)
    """
    has_json = any(getattr(ep, 'is_json', False) for ep in endpoints)
    needs_auth = any(
        getattr(ep, 'status', 0) in (401, 403) or
        any('auth' in str(ind).lower() for ind in getattr(ep, 'auth_indicators', []))
        for ep in endpoints
    )
    has_public = any(
        getattr(ep, 'is_json', False) and getattr(ep, 'status', 0) == 200
        for ep in endpoints
    )

    # Check for framework-detected stores
    has_store = any(
        hasattr(ep, 'framework') and ep.framework.get('type') in ('pinia', 'vuex')
        for ep in endpoints
    )

    if has_store:
        return "store-action"
    if has_json and has_public and not needs_auth:
        return "public"
    if has_json:
        return "intercept"
    return "ui"


# ── Endpoint Scoring ──

def score_endpoint(
    url: str,
    method: str,
    status: int,
    is_json: bool,
    sample: Any,
    content_type: str = "",
) -> float:
    """
    Score an endpoint's usefulness for data extraction (0.0-10.0).

    Scoring factors:
      +3: JSON response with array data
      +2: Status 200
      +1: Contains common data fields (title, name, url, etc.)
      +1: Has pagination params
      +1: Has search params
      -2: Error status (4xx/5xx)
      -1: Non-JSON or HTML
    """
    score = 0.0

    if is_json and isinstance(sample, dict):
        data = sample.get("data") or sample.get("result") or sample.get("items") or sample.get("list")
        if isinstance(data, list) and len(data) > 0:
            score += 3.0  # Array data is most useful
        elif isinstance(sample, dict) and len(sample) > 2:
            score += 1.5  # Object data is somewhat useful

    if status == 200:
        score += 2.0
    elif 400 <= status < 600:
        score -= 2.0

    if not is_json and "html" not in content_type.lower():
        score -= 1.0

    # Check for useful field names in sample
    if isinstance(sample, dict):
        sample_text = str(sample).lower()
        useful_keywords = ['title', 'name', 'url', 'link', 'id', 'image', 'time', 'date']
        score += sum(0.5 for kw in useful_keywords if kw in sample_text)

    # Check URL for pagination/search patterns
    parsed_qs = parse_qs(urlparse(url).query)
    if has_pagination({k: v[0] for k, v in parsed_qs.items() if v}):
        score += 1.0
    if has_search({k: v[0] for k, v in parsed_qs.items() if v}):
        score += 1.0

    return max(0.0, min(10.0, score))


# ── Capability Naming ──

_FIELD_NAME_MAP = [
    # (pattern, canonical_name)
    (r'title|name|headline|subject', 'title'),
    (r'url|link|href|permalink', 'url'),
    (r'author|user|nick|owner|creator', 'author'),
    (r'score|hot|rank|count|view|read', 'score'),
    (r'desc|summary|abstract|excerpt|content|body|text', 'description'),
    (r'img|pic|thumb|cover|avatar|photo|image', 'image'),
    (r'time|date|created|published|updated|pub', 'time'),
    (r'id|key|uid|docid', 'id'),
    (r'price|amount|cost|fee', 'price'),
    (r'location|addr|city|region|area', 'location'),
    (r'tag|category|type|label', 'tag'),
]

_CAPABILITY_TEMPLATES = {
    'search': '{site}_search_{term}',
    'list': '{site}_{resource}_list',
    'detail': '{site}_{resource}_detail',
    'feed': '{site}_{resource}_feed',
    'profile': '{site}_user_profile',
}


def infer_capability_name(
    site: str,
    endpoint_url: str,
    fields: dict[str, str],
    goal: str = "",
) -> tuple[str, str]:
    """
    Infer a human-readable capability name and description.

    Returns (name, description).
    """
    # Determine resource type from fields
    has_title = any(k in fields.values() for k in ('title', 'name'))
    has_url = any(k in fields.values() for k in ('url', 'link'))

    if goal:
        name = f'{site}_{goal}'
        desc = f'Fetch {goal}-related data via {endpoint_url.split("/")[-1]}'
    elif has_title and has_url:
        name = _CAPABILITY_TEMPLATES['list'].format(site=site, resource='content')
        desc = f'Fetch {site} content list with titles, links, and other fields'
    else:
        name = _CAPABILITY_TEMPLATES['list'].format(site=site, resource='data')
        desc = f'Extract structured data from {site}'

    return name, desc


def infer_capabilities_from_endpoints(
    site: str,
    endpoints: list[Any],
    goal: str = "",
    min_score: float = 5.0,
) -> list[InferredCapability]:
    """
    Infer capabilities from scored endpoints.

    Returns list of InferredCapability objects sorted by confidence (desc).
    """
    capabilities = []

    for ep in endpoints:
        if not getattr(ep, 'is_json', False):
            continue
        if getattr(ep, 'score', 0) < min_score:
            continue

        sample = getattr(ep, 'sample', None)
        if not isinstance(sample, dict):
            continue

        # Extract data array
        data = sample.get("data") or sample.get("result") or sample.get("items") or sample.get("list") or [sample]
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list) or not data:
            continue

        sample_item = data[0]
        if not isinstance(sample_item, dict):
            continue

        # Detect fields
        fields = {}
        for key, _value in sample_item.items():
            kl = key.lower()
            for pattern, canonical in _FIELD_NAME_MAP:
                if re.search(pattern, kl):
                    fields[canonical] = key
                    break

        if len(fields) < 2:
            continue

        # Infer capability metadata
        name, desc = infer_capability_name(site, ep.url, fields, goal)
        strategy = infer_strategy([ep], ep.url)
        confidence = min(1.0, getattr(ep, 'score', 0) / 10.0)

        cap = InferredCapability(
            name=name,
            description=desc,
            strategy=strategy,
            confidence=confidence,
            endpoint=ep.url,
            item_path=_detect_item_path(sample),
            recommended_columns=list(fields.keys()),
            store_hint=None,
        )
        capabilities.append(cap)

    # Sort by confidence descending
    capabilities.sort(key=lambda c: c.confidence, reverse=True)
    return capabilities


def _detect_item_path(sample: dict) -> str | None:
    """Detect the path to the items array in a response."""
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


# ── Site Detection ──

_SITE_ALIASES = {
    'zhipin.com': ('boss', 'zhipin'),
    'boss.zhipin.com': ('boss', 'zhipin'),
    'taobao.com': ('taobao',),
    'tmall.com': ('tmall',),
    'jd.com': ('jd',),
    'zhihu.com': ('zhihu',),
    'weibo.com': ('weibo',),
    'xiaohongshu.com': ('xiaohongshu',),
    'douyin.com': ('douyin',),
    'bilibili.com': ('bilibili',),
    'douban.com': ('douban',),
    'google.com': ('google',),
    'github.com': ('github',),
}


def detect_site_name(url: str) -> str:
    """Detect site name from URL. Returns short identifier like 'boss', 'taobao'."""
    try:
        hostname = urlparse(url).hostname or ""
        hostname = hostname.lower()

        # Check exact domain matches first
        for domain, aliases in _SITE_ALIASES.items():
            if hostname == domain or hostname.endswith('.' + domain):
                return aliases[0]

        # Fallback: use domain root
        root = hostname.split('.')[0]
        return root if root else "unknown"
    except Exception:
        return "unknown"
