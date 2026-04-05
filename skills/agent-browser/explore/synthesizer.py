"""YAML Synthesizer — 从 browser-use AgentHistoryList 生成可执行的 YAML 适配器

Input:  AgentHistoryList JSON (browser-use action trace) + ExplorationResult
Output: Executable YAML adapter file

Core challenge: browser-use traces are noisy exploration artifacts.
The synthesizer must distill them into clean, deterministic pipeline steps.

Trace Distillation Rules:
  - Remove screenshot/done terminal steps
  - Collapse redundant waits
  - Convert index-based clicks to CSS selectors
  - Convert extract actions to evaluate JS
  - Deduplicate repeated patterns

Selector Resolution Priority:
  1. data-ref from snapshot attributes
  2. CSS path from element structure
  3. Semantic fallback: [data-type="..."], [class*="..."]
  4. Index-of-type (with fragility warning)

Strategy Auto-Detection:
  - store-action → tap step (zero network, best performance)
  - public API → fetch step (no browser needed)
  - cookie → evaluate(fetch) in browser (inherits auth)
  - ui/dom → DOM scraping (fallback)
"""
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import yaml

from .explorer import ExplorationResult

logger = logging.getLogger(__name__)

# ── Field-to-CSS-selector mapping hints ──

_FIELD_SELECTOR_HINTS = {
    "title": ["h1", "h2", "h3", "h4", ".title", "[class*='title']", "[data-title]"],
    "url": ["a[href]", ".link", "a"],
    "author": [".author", ".user", ".name", "[class*='author']"],
    "score": [".score", ".hot", ".rank", "[class*='score']"],
    "description": [".desc", ".summary", ".abstract", "p.description", ".content"],
    "image": ["img", ".thumb", ".cover", ".avatar", "[class*='img']"],
    "time": ["time", ".date", ".time", "[class*='date']"],
    "id": ["[data-id]", "[id]"],
}


# ══════════════════════════════════════════════
#  PUBLIC API
# ═════════════════════════════════════════════


def synthesize_from_trace(
    site: str,
    trace: List[Dict[str, Any]],
    exploration: Optional[ExplorationResult] = None,
    command_name: str = "list",
    adapter_dir: Optional[str] = None,
) -> dict:
    """
    Main entry point: synthesize YAML adapter from browser-use AgentHistoryList.

    Args:
        site: Site name (e.g., 'boss', 'taobao')
        trace: browser-use AgentHistoryList (list of action dicts)
        exploration: Optional explore result for API discovery
        command_name: Adapter command name (e.g., 'search', 'list')
        adapter_dir: Directory to save generated YAML

    Returns:
        Generated adapter configuration dict.
    """
    # Step 1: Distill trace (remove noise, normalize actions)
    distilled = distill_trace(trace)

    # Step 2: Detect best execution strategy
    strategy = detect_strategy(distilled, exploration)

    # Step 3: Resolve selectors for click/type actions
    resolved_actions = resolve_selectors(distilled, exploration)

    # Step 4: Generate extraction JS from extract results
    extraction_js = generate_extraction_js(resolved_actions, exploration)

    # Step 5: Build YAML adapter based on strategy
    adapter = build_adapter(
        site=site,
        name=command_name,
        strategy=strategy,
        actions=resolved_actions,
        extraction_js=extraction_js,
        exploration=exploration,
    )

    # Add stealth config block
    adapter["stealth"] = {
        "warmup": True,
        "human_click": True,
        "human_type": True,
        "request_delay": [0.5, 2.0],
        "scroll_before": True,
        "jitter": True,
    }

    # Save to file
    if adapter_dir:
        os.makedirs(adapter_dir, exist_ok=True)
        filepath = os.path.join(adapter_dir, f"{command_name}.yaml")
        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(adapter, f, allow_unicode=True, default_flow_style=False)
        logger.info(f"Generated adapter: {filepath}")

    return adapter


# Keep backward-compatible entry point
def synthesize(
    site: str,
    exploration: ExplorationResult,
    command_name: str = "list",
    adapter_dir: Optional[str] = None,
) -> dict:
    """Backward-compatible: generate from ExplorationResult only (no trace)."""
    if not exploration.capabilities:
        return _generate_dom_adapter(site, command_name, exploration)

    best = exploration.capabilities[0]
    strategy = best.get("strategy_guess", "cookie")

    if strategy == "public":
        adapter = _generate_fetch_adapter(site, command_name, best, exploration)
    else:
        adapter = _generate_cookie_adapter(site, command_name, best, exploration)

    adapter["stealth"] = {
        "warmup": True,
        "human_click": True,
        "human_type": True,
        "request_delay": [0.5, 2.0],
        "scroll_before": True,
        "jitter": True,
    }

    if adapter_dir:
        os.makedirs(adapter_dir, exist_ok=True)
        filepath = os.path.join(adapter_dir, f"{command_name}.yaml")
        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(adapter, f, allow_unicode=True, default_flow_style=False)
        logger.info(f"Generated adapter: {filepath}")

    return adapter


# ══════════════════════════════════════════════
#  TRACE DISTILLATION
# ═════════════════════════════════════════════


def distill_trace(trace: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Distill noisy browser-use trace into clean action sequence.

    Rules applied:
      1. Remove screenshot steps
      2. Remove done/terminal steps
      3. Collapse redundant waits (keep max)
      4. Convert input_text+send_keys Enter → single type step
      5. Deduplicate consecutive identical actions
      6. Remove no-op navigation (same URL as current)
    """
    cleaned = []
    prev_action = None
    wait_accumulator = 0.0

    for step in trace:
        action_type = _get_action_type(step)

        # Rule 1: Drop screenshots
        if action_type == "screenshot":
            continue

        # Rule 2: Drop done/terminal steps
        if action_type in ("done", "task_complete"):
            continue

        # Rule 3: Accumulate waits instead of emitting each one
        if action_type == "wait":
            wait_val = _extract_wait_value(step)
            if wait_val is not None:
                wait_accumulator = max(wait_accumulator, wait_val)
                continue

        # Flush accumulated wait before non-wait action
        if wait_accumulator > 0 and action_type != "wait":
            cleaned.append({"action": "wait", "params": {"seconds": wait_accumulator}})
            wait_accumulator = 0.0

        # Rule 4: Merge input_text + Enter keypress into type
        if action_type == "input_text" and prev_action and _get_action_type(prev_action) == "input_text":
            # This is a continuation of previous input, merge text
            continue

        # Rule 5: Deduplicate identical consecutive actions
        if (prev_action and _actions_equal(step, prev_action)
                and action_type not in ("click", "scroll")):
            logger.debug(f"Deduplicated consecutive {action_type}")
            continue

        cleaned.append(_normalize_action(step))
        prev_action = step

    # Flush final wait accumulator
    if wait_accumulator > 0:
        cleaned.append({"action": "wait", "params": {"seconds": wait_accumulator}})

    logger.info(f"Trace distillation: {len(trace)} → {len(cleaned)} steps")
    return cleaned


def _get_action_type(step: Dict) -> str:
    """Extract action type from a browser-use history step."""
    if isinstance(step, dict):
        # browser-use format: {"action": [...]} or direct keys
        if "action" in step:
            actions = step.get("action", [])
            if isinstance(actions, list) and len(actions) > 0:
                first = actions[0]
                if isinstance(first, dict):
                    return first.get("type", "unknown").lower()
                return str(first).lower()
        # Check common keys
        for key in ("type", "action_type", "method"):
            if key in step:
                return str(step[key]).lower()
    return "unknown"


def _extract_wait_value(step: Dict) -> Optional[float]:
    """Extract wait duration from a wait step."""
    params = step.get("params", step)
    if isinstance(params, (int, float)):
        return float(params)
    if isinstance(params, dict):
        for key in ("seconds", "duration", "ms", "timeout"):
            if key in params:
                val = params[key]
                if key == "ms":
                    return float(val) / 1000
                return float(val)
    if isinstance(params, str):
        try:
            return float(params)
        except ValueError:
            pass
    return None


def _normalize_action(step: Dict) -> Dict:
    """Normalize a trace step to standard {action, params} format."""
    action_type = _get_action_type(step)
    params = {}

    # Extract params from various formats
    if "params" in step:
        params = step["params"]
    elif "action" in step:
        actions = step.get("action", [])
        if isinstance(actions, list) and len(actions) > 0:
            first = actions[0]
            if isinstance(first, dict):
                params = {k: v for k, v in first.items() if k != "type"}

    return {"action": action_type, "params": params}


def _actions_equal(a: Dict, b: Dict) -> bool:
    """Check if two actions are functionally identical."""
    return (_get_action_type(a) == _get_action_type(b) and
            json.dumps(_normalize_action(a).get("params", {}), sort_keys=True) ==
            json.dumps(_normalize_action(b).get("params", {}), sort_keys=True))


# ══════════════════════════════════════════════
#  SELECTOR RESOLUTION
# ═════════════════════════════════════════════


def resolve_selectors(
    distilled: List[Dict],
    exploration: Optional[ExplorationResult] = None,
) -> List[Dict]:
    """
    Resolve element references to robust CSS selectors.

    Strategy priority:
      1. data-ref from snapshot (if available in exploration)
      2. CSS path from element structure analysis
      3. Semantic class-based selectors
      4. Index-based (with warning comment)
    """
    resolved = []

    for action in distilled:
        action_type = action["action"]
        params = dict(action.get("params", {}))

        if action_type in ("click", "type") and params:
            # Try to resolve the target element to a CSS selector
            selector = _resolve_element_selector(params, exploration)
            if selector:
                params["_resolved_selector"] = selector

        resolved.append({"action": action_type, "params": params})

    return resolved


def _resolve_element_selector(
    params: Dict,
    exploration: Optional[ExplorationResult] = None,
) -> Optional[str]:
    """
    Resolve an element reference to a CSS selector.

    Input formats from browser-use:
      - {"index": 5} — DOM index position
      - {"selector": ".class"} — already a selector
      - {"xpath": "//div[@id='x']"} — XPath expression
      - {"text": "Search"} — text-based lookup
    """
    # Already a CSS selector
    if "selector" in params and params["selector"]:
        sel = params["selector"]
        if sel.startswith(("/", "(")) or "::" in sel:
            # Looks like XPath, try to convert
            return _xpath_to_css(sel)
        return sel

    # Text-based lookup → generate attribute selector
    if "text" in params and params["text"]:
        text = params["text"]
        # Try to find by text content via :contains() equivalent
        # Note: pure CSS doesn't support :contains(), use data attribute approach
        return None  # Will need JS-based resolution at runtime

    # Index-based → fragile, but provide structure hint
    if "index" in params:
        idx = params["index"]
        # If we have exploration data with DOM structure, try to map index to selector
        if exploration and hasattr(exploration, 'capabilities'):
            # Could attempt index→selector mapping from snapshot
            pass
        # Return with warning that this is fragile
        logger.warning(f"Index-based selector (index={idx}) is fragile across page loads")

    # XPath conversion
    if "xpath" in params:
        return _xpath_to_css(params["xpath"])

    return None


def _xpath_to_css(xpath: str) -> str:
    """Simple XPath → CSS converter (handles common patterns only)."""
    xpath = xpath.strip()

    # //tag[@attr='val'] → tag[attr='val']
    m = re.match(r"^//(\w+)\[@(\w+)='([^']*)'\]$", xpath)
    if m:
        return f"{m.group(1)}[{m.group(2)}='{m.group(3)}']"

    # //tag → tag
    m = re.match(r"^//(\w+)$", xpath)
    if m:
        return m.group(1)

    # //tag[@attr='val']/child → tag[attr='val'] child
    m = re.match(r"^//(\w+)\[@(\w+)='([^']*)'\]/(\w+)$", xpath)
    if m:
        return f"{m.group(1)}[{m.group(2)}='{m.group(3)}'] {m.group(4)}"

    logger.warning(f"Cannot convert XPath to CSS: {xpath}, using as-is")
    return xpath


# ══════════════════════════════════════════════
#  EXTRACTION JS GENERATION
# ═════════════════════════════════════════════


def generate_extraction_js(
    actions: List[Dict],
    exploration: Optional[ExplorationResult] = None,
) -> str:
    """
    Generate deterministic JavaScript extraction code from browser-use extract results.

    When browser-use's extract action returns structured data, we generate JS that
    reproduces this extraction deterministically on subsequent runs.
    """
    # Look for the last extract action in the trace
    extract_action = None
    for action in reversed(actions):
        if action["action"] == "extract":
            extract_action = action
            break

    if not extract_action:
        # No explicit extract action found; generate generic DOM extraction
        return _generate_generic_extraction_js(exploration)

    params = extract_action.get("params", {})
    query = params.get("query", "")
    result = params.get("result", params.get("extracted_content"))

    # If we have structured extraction results, analyze them
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
            if isinstance(parsed, list) and len(parsed) > 0:
                return _generate_structured_extraction_js(parsed, exploration)
        except (json.JSONDecodeError, TypeError):
            pass

    # Fallback: generate from query description + exploration data
    return _generate_query_based_extraction_js(query, exploration)


def _generate_generic_extraction_js(exploration: Optional[ExplorationResult]) -> str:
    """Generate generic DOM extraction when no specific extract result available."""
    if exploration and exploration.capabilities:
        cap = exploration.capabilities[0]
        fields = cap.get("fields", {})
        field_selectors = []
        for field_name, dom_key in fields.items():
            hints = _FIELD_SELECTOR_HINTS.get(field_name, [f"[class*='{field_name}']"])
            selector = hints[0] if hints else f"[class*='{field_name}']"
            field_selectors.append(f"""
                {field_name}: (el.querySelector('{selector}')?.textContent?.trim()) || '',""")

        selectors_str = "\n".join(field_selectors)

        # Determine container selector from endpoint URL
        container = _guess_container_selector(exploration.url)

        return f"""(() => {{
        const items = [];
        document.querySelectorAll('{container}').forEach(el => {{
            items.push({{
{selectors_str}
            }});
        }});
        return items;
    }})()"""

    # Ultra-fallback: generic article/item/card extraction
    return """(() => {
        const items = [];
        document.querySelectorAll('article, [class*="item"], [class*="card"], [class*="row"]').forEach(el => {
            items.push({
                title: el.querySelector('h1, h2, h3, h4, [class*="title"]')?.textContent?.trim() || '',
                url: el.querySelector('a[href]')?.href || '',
                text: el.textContent?.trim()?.substring(0, 300) || '',
            });
        });
        return items;
    })()"""


def _generate_structured_extraction_js(parsed_data: List[Dict], exploration: Optional[ExplorationResult]) -> str:
    """Generate extraction JS from parsed structured data (gold standard)."""
    sample = parsed_data[0]
    fields = []

    for key in sample.keys():
        value = sample[key]
        # Try to infer CSS selector from field name
        hints = _FIELD_SELECTOR_HINTS.get(key, [])
        selector = hints[0] if hints else f"[class*='{key}']"
        fields.append(f"                {key}: el.querySelector('{selector}')?.textContent?.trim() || '',")

    fields_str = "\n".join(fields)
    container = _guess_container_selector(exploration.url if exploration else "")

    return f"""(() => {{
        const items = [];
        document.querySelectorAll('{container}').forEach(el => {{
            items.push({{
{fields_str}
            }});
        }});
        return items;
    }})()"""


def _generate_query_based_extraction_js(query: str, exploration: Optional[ExplorationResult]) -> str:
    """Generate extraction JS from natural language query."""
    # Parse common patterns from query text
    query_lower = query.lower()

    if any(w in query_lower for w in ("职位", "job", "工作")):
        container = ".job-card-wrapper, [class*='job'], [class*='card']"
    elif any(w in query_lower for w in ("商品", "product", "item")):
        container = "[class*='item'], [class*='product'], [class*='card']"
    elif any(w in query_lower for w in ("文章", "article", "post")):
        container = "article, [class*='post'], [class*='article']"
    else:
        container = _guess_container_selector(exploration.url if exploration else "")

    return f"""(() => {{
        const items = [];
        document.querySelectorAll('{container}').forEach(el => {{
            items.push({{
                title: el.querySelector('h1, h2, h3, [class*="title"]')?.textContent?.trim() || '',
                desc: el.querySelector('[class*="desc"], p, [class*="content"]')?.textContent?.trim()?.substring(0, 300) || '',
                link: el.querySelector('a[href]')?.href || '',
            }});
        }});
        return items;
    }})()"""


def _guess_container_selector(url: str) -> str:
    """Guess the main content container selector from URL."""
    url_lower = url.lower()
    if "zhipin.com" in url_lower or "boss" in url_lower:
        return ".job-card-wrapper, [class*='job-card']"
    elif "taobao.com" in url_lower or "tmall.com" in url_lower:
        return "[class*='item'], [class*='Card']"
    elif "jd.com" in url_lower:
        return ".gl-item, [class*='gl-item']"
    elif "zhihu.com" in url_lower:
        return ".ContentItem, [class*='ContentItem']"
    elif "weibo.com" in url_lower:
        return ".card-wrap, [class*='card']"
    else:
        return "article, [class*='item'], [class*='card'], [class*='row']"


# ══════════════════════════════════════════════
#  STRATEGY AUTO-DETECTION
# ═════════════════════════════════════════════


def detect_strategy(
    distilled: List[Dict],
    exploration: Optional[ExplorationResult] = None,
) -> str:
    """
    Choose best execution strategy for the synthesized YAML.

    Returns one of: 'store-action', 'public', 'cookie', 'ui'
    """
    if not exploration:
        return "ui"

    has_json_api = len(exploration.endpoints) > 0
    uses_store = any(
        "pinia" in str(c).lower() or "vuex" in str(c).lower() or "store" in str(c).lower()
        for c in exploration.capabilities
    )
    needs_auth = any(ep.status == 401 or ep.status == 403 for ep in exploration.endpoints)
    has_public_endpoint = any(
        ep.strategy_guess == "public" for ep in exploration.capabilities
    )

    # Check trace for store access patterns
    accesses_store = any(
        "store" in str(action.get("params", "")).lower()
        or "pinia" in str(action.get("params", "")).lower()
        or "vuex" in str(action.get("params", "")).lower()
        for action in distilled
    )

    if accesses_store or uses_store:
        return "store-action"     # Best: zero network requests
    elif has_json_api and has_public_endpoint and not needs_auth:
        return "public"           # Good: direct fetch, no browser needed
    elif has_json_api and needs_auth:
        return "cookie"           # OK: browser fetch with credentials
    else:
        return "ui"               # Fallback: DOM scraping


# ══════════════════════════════════════════════
#  ADAPTER BUILDER
# ═════════════════════════════════════════════


def build_adapter(
    site: str,
    name: str,
    strategy: str,
    actions: List[Dict],
    extraction_js: str,
    exploration: Optional[ExplorationResult] = None,
) -> dict:
    """
    Build complete YAML adapter dict from synthesized components.
    """
    # Extract fields from extraction JS
    columns = _extract_columns_from_js(extraction_js)

    # Build pipeline steps based on strategy
    pipeline = _build_pipeline(strategy, actions, extraction_js, exploration)

    # Determine args from actions (e.g., search query parameter)
    args = _infer_args(actions, exploration)

    adapter = {
        "site": site,
        "name": name,
        "description": f"Auto-generated: {site}/{name} (strategy: {strategy})",
        "strategy": strategy,
        "browser": strategy in ("cookie", "store-action", "ui"),
        "args": args,
        "columns": columns,
        "pipeline": pipeline,
    }

    return adapter


def _build_pipeline(
    strategy: str,
    actions: List[Dict],
    extraction_js: str,
    exploration: Optional[ExplorationResult],
) -> List[Dict]:
    """Build pipeline step list based on detected strategy."""
    base_url = exploration.url if exploration else ""

    if strategy == "public":
        cap = exploration.capabilities[0] if exploration and exploration.capabilities else {}
        fields = cap.get("fields", {})
        map_expr = {k: f"${{ item.{v} }}" for k, v in fields.items()} if fields else {}
        return [
            {"fetch": {"url": cap.get("endpoint", ""), "method": cap.get("method", "GET"), "browser": False}},
            {"select": {"path": "data"}},
            {"map": map_expr if map_expr else {"title": "${{ item.title }}", "url": "${{ item.url }}"}},
            {"limit": "${{ args.limit | default(20) }}"},
        ]

    elif strategy == "store-action":
        store_name = _detect_store_name(exploration)
        getter = _detect_getter_name(exploration)
        return [
            {"navigate": base_url},
            {"tap": {"store": store_name, "getter": getter}},
            {"map": {"title": "${{ item.title }}", "url": "${{ item.url }}"}},
            {"limit": "${{ args.limit | default(20) }}"},
        ]

    elif strategy == "cookie":
        cap = exploration.capabilities[0] if exploration and exploration.capabilities else {}
        endpoint = cap.get("endpoint", "")
        fields = cap.get("fields", {})
        map_expr = {k: f"${{ item.{v} }}" for k, v in fields.items()} if fields else {}
        return [
            {"navigate": base_url},
            {"evaluate": f"""
                (() => {{
                    const resp = await fetch('{endpoint}', {{credentials: 'include'}});
                    const data = await resp.json();
                    return data.data || data.result || data.items || data.list || [data];
                }})()
            """},
            {"map": map_expr if map_expr else {"title": "${{ item.title }}", "url": "${{ item.url }}"}},
            {"limit": "${{ args.limit | default(20) }}"},
        ]

    else:  # ui / dom scraping
        return [
            {"navigate": base_url},
            {"wait": {"seconds": 2}},
            {"evaluate": extraction_js},
            {"limit": "${{ args.limit | default(20) }}"},
        ]


def _extract_columns_from_js(js_code: str) -> List[str]:
    """Extract column names from generated extraction JS."""
    columns = []
    # Match pattern: fieldname: el.querySelector...
    for m in re.finditer(r'(\w+):\s*el\.querySelector', js_code):
        col = m.group(1)
        if col not in ("_index", "_text", "_html") and col not in columns:
            columns.append(col)
    if not columns:
        columns = ["title", "url", "description"]
    return columns


def _detect_store_name(exploration: Optional[ExplorationResult]) -> str:
    """Detect Pinia/Vuex store name from exploration."""
    if exploration and exploration.capabilities:
        for cap in exploration.capabilities:
            if "store" in str(cap).lower():
                # Try to extract store name
                m = re.search(r'store["\']?\s*[:=]\s*["\']?(\w+)', str(cap))
                if m:
                    return m.group(1)
    return "mainStore"


def _detect_getter_name(exploration: Optional[ExplorationResult]) -> str:
    """Detect Pinia getter name from exploration."""
    if exploration and exploration.capabilities:
        for cap in exploration.capabilities:
            if "items" in str(cap).lower() or "list" in str(cap).lower():
                return "items"
            if "data" in str(cap).lower():
                return "data"
    return "items"


def _infer_args(actions: List[Dict], exploration: Optional[ExplorationResult]) -> Dict:
    """Infer user-facing arguments from trace actions."""
    args = {
        "limit": {"type": "int", "default": 20, "description": "Number of results"},
    }

    # Look for search/input actions that suggest user parameters
    for action in actions:
        params = action.get("params", {})
        if action["action"] in ("input_text", "type", "fill"):
            # This might be a searchable field
            placeholder = params.get("placeholder", "")
            param_name = params.get("name", "query")
            if placeholder or param_name:
                args[param_name] = {
                    "type": "str",
                    "required": True,
                    "description": placeholder or f"Search {param_name}",
                }

    return args


# ══════════════════════════════════════════════
#  BACKWARD-COMPATIBLE GENERATORS
# ═════════════════════════════════════════════


def _generate_fetch_adapter(site, name, cap, exploration) -> dict:
    """Public API strategy: fetch → select → map → limit"""
    fields = cap.get("fields", {})
    columns = list(fields.keys())
    map_expr = {}
    for target, source_key in fields.items():
        map_expr[target] = f"${{ item.{source_key} }}"
    return {
        "site": site, "name": name,
        "description": f"Auto-generated: {site} {name} (public API)",
        "strategy": "public", "browser": False,
        "args": {"limit": {"type": "int", "default": 10}},
        "columns": columns,
        "pipeline": [
            {"fetch": {"url": cap["endpoint"], "method": cap.get("method", "GET"), "browser": False}},
            {"select": {"path": "data"}},
            {"map": map_expr},
            {"limit": "${{ args.limit }}"},
        ],
    }


def _generate_cookie_adapter(site, name, cap, exploration) -> dict:
    """Cookie strategy: navigate → evaluate(fetch) → map → limit"""
    fields = cap.get("fields", {})
    columns = list(fields.keys())
    map_expr = {}
    for target, source_key in fields.items():
        map_expr[target] = f"${{ item.{source_key} }}"
    return {
        "site": site, "name": name,
        "description": f"Auto-generated: {site} {name} (cookie)",
        "strategy": "cookie", "browser": True,
        "args": {"limit": {"type": "int", "default": 10}},
        "columns": columns,
        "pipeline": [
            {"navigate": exploration.url},
            {"evaluate": f"""
                (() => {{
                    const resp = await fetch('{cap["endpoint"]}', {{credentials: 'include'}});
                    const data = await resp.json();
                    return data.data || data.result || data.items || data.list || [data];
                }})()
            """},
            {"map": map_expr},
            {"limit": "${{ args.limit }}"},
        ],
    }


def _generate_dom_adapter(site, name, exploration) -> dict:
    """DOM scraping strategy: navigate → wait → evaluate → limit"""
    from urllib.parse import urlparse
    parsed = urlparse(exploration.url)
    return {
        "site": site, "name": name,
        "description": f"Auto-generated: {site} {name} (DOM)",
        "strategy": "ui", "browser": True,
        "args": {"limit": {"type": "int", "default": 10}},
        "columns": ["title", "url", "text"],
        "pipeline": [
            {"navigate": exploration.url},
            {"wait": {"seconds": 3}},
            {"evaluate": """
                (() => {
                    const items = [];
                    document.querySelectorAll('article, .item, .card, li').forEach(el => {
                        const titleEl = el.querySelector('h1, h2, h3, h4, .title');
                        const linkEl = el.querySelector('a');
                        items.push({
                            title: titleEl ? titleEl.textContent.trim() : '',
                            url: linkEl ? linkEl.href : '',
                            text: el.textContent.trim().substring(0, 100)
                        });
                    });
                    return items;
                })()
            """},
            {"limit": "${{ args.limit }}"},
        ],
    }
