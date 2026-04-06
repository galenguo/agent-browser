# Site Adapter Contribution Guide

Adapters are **YAML-based, zero-LLM-cost automation pipelines** that define how to extract structured data from a target website. Each adapter is a self-contained file that specifies navigation, interaction, and data extraction steps -- all executed deterministically by the Pipeline Engine (v2.3) with built-in stealth, error recovery, and telemetry.

## Table of Contents

- [What are adapters?](#what-are-adapters)
- [Adapter file location](#adapter-file-location)
- [YAML schema reference](#yaml-schema-reference)
- [Step types reference](#step-types-reference)
- [Template variables](#template-variables)
- [Validation rules](#validation-rules)
- [Example: minimal adapter](#example-minimal-adapter)
- [Example: public API adapter](#example-public-api-adapter)
- [Example: full DOM scraping adapter](#example-full-dom-scraping-adapter)
- [Testing your adapter](#testing-your-adapter)
- [Contributing workflow](#contributing-workflow)

---

## What are adapters?

An adapter is a YAML file that describes **how to get data from a website** without using an LLM. It defines:

1. **Metadata** -- site name, description, strategy, parameters
2. **Parameters** (`args`) -- user-configurable inputs like search queries or city codes
3. **Pipeline** (`pipeline`) -- an ordered list of steps (navigate, click, wait, evaluate, etc.)

When executed, the runner creates a browser session (if needed), runs each step in sequence through the StealthMiddleware (anti-detection layer), and returns structured data.

**Key benefits over LLM-driven automation:**
- Zero token cost per run
- Deterministic and reproducible
- Fast execution (no model inference latency)
- Easy to debug and version-control

---

## Adapter file location

Adapters live under the `adapters/` directory at the project root, organized by site:

```
adapters/
  _shared/            # Shared utilities (skipped by loader)
  baidu/
    search.yaml       # adapters/baidu/search.yaml
  bilibili/
    hot.yaml
  boss/
    search.yaml
  zhihu/
    hot.yaml
  desktop/
    chatgpt.yaml
    cursor.yaml
    notion.yaml
  xiaohongshu/        # (empty -- placeholder for future adapters)
  <your-site>/
    <command>.yaml    # <-- put your new adapter here
```

**Naming convention:** `adapters/{site_name}/{command_name}.yaml`

The loader registers each file as a unique `(site, name)` key. For example, `adapters/baidu/search.yaml` becomes the adapter key `("baidu", "search")`.

**File requirements:**
- Extension must be `.yaml` or `.yml`
- Files inside any directory named `_shared` are skipped
- Each file must contain valid YAML with `site`, `name`, and `pipeline` fields

---

## YAML schema reference

### Top-level fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `site` | string | **yes** | -- | Site identifier (e.g., `"baidu"`, `"boss"`). Also accepts alias `domain`. |
| `name` | string | **yes** | -- | Command name within the site (e.g., `"search"`, `"hot"`). |
| `description` | string | no | `""` | Human-readable description of what this adapter does. |
| `strategy` | enum | no | `"public"` | Automation strategy (see below). |
| `browser` | bool | no | `true` | Whether a browser session is needed. Must be `true` if pipeline contains `navigate` steps. |
| `stealth` | dict | no | `{}` | StealthMiddleware configuration (see below). |
| `args` | dict | no | `{}` | Parameter definitions keyed by name (see below). |
| `columns` | list[str] | no | `[]` | Expected output column names (documentation only). |
| `pipeline` | list | **yes** | -- | Ordered list of step dicts to execute. |

### Strategy enum

| Value | Description | Browser needed? |
|-------|-------------|-----------------|
| `public` | Public API / HTTP fetch only | No (set `browser: false`) |
| `ui` / `dom` | DOM-based scraping via browser | Yes |
| `cookie` | Cookie-authenticated requests via browser | Yes |
| `intercept` | Network request interception (alias for `cookie`) | Yes |
| `header` | Custom header-based API calls | No (set `browser: false`) |
| `store-action` | Vue/Pinia store action tapping (SPA sites) | Yes |

### Stealth configuration (`stealth`)

```yaml
stealth:
  warmup: true              # Pre-navigation warmup delay
  human_click: true         # Bezier-curve mouse movement before clicks
  human_type: true          # Human-like typing (50-250ms/char, random typos)
  request_delay: [1.0, 3.0] # Random delay range between actions (seconds)
  scroll_before: true       # Scroll element into view before interaction
  jitter: true              # Add timing noise to all operations
```

### Args definition

Each arg is a dict with these keys:

```yaml
args:
  query:
    type: str               # One of: str, int, float, bool
    required: true          # If true, caller must provide this value
    default: ""             # Used when not provided (optional)
    description: "Search keyword"  # Human-readable docs
```

Valid types: `str`, `int`, `float`, `bool`.

---

## Step types reference

The pipeline is a list of step dicts. Each step has exactly one key (the operation name) mapping to its parameters. There are **16 built-in steps** in two categories:

### Browser steps (require a page handle)

#### `navigate` -- Go to a URL

```yaml
- navigate: "https://example.com"
- navigate: "https://example.com?q=${{ args.query | urlencode }}"
```

Also accepts a dict with options:

```yaml
- navigate:
    url: "https://example.com"
    waitUntil: "networkidle"   # domcontentloaded (default) | load | networkidle
    settleMs: 2000             # Extra settle time after navigation (ms)
```

URL safety: Only `http://` and `https://` schemes allowed. Private IP ranges (10.x, 172.16-31.x, 192.168.x, 127.x) are blocked to prevent SSRF.

#### `click` -- Click an element by CSS selector

```yaml
- click: ".search-button"
- click: "${{ args.selector }}"
```

Automatically scrolls the element into view before clicking. Raises an error if the element is not found.

#### `type` -- Type text into an input element

```yaml
- type:
    selector: "#search-input"
    text: "${{ args.query }}"
    submit: true              # Press Enter after typing (optional)
```

Uses `ref` as an alias for `selector`:

```yaml
- type:
    ref: "@e1"
    text: "hello world"
```

#### `wait` -- Wait for time, text, or selector

Multiple formats accepted:

```yaml
# Fixed delay (seconds)
- wait: 2
- wait: 1.5

# Wait for CSS selector to appear
- wait:
    selector: ".results-list"
    timeout: 10000           # ms (default: 10000)

# Wait for text to appear in page body
- wait:
    text: "Results found"
    timeout: 8000
```

Alias: `{time: N}` is equivalent to `{seconds: N}`.

#### `press` -- Press a keyboard key

```yaml
- press: "Enter"
- press: "Tab"
- press: "Escape"
```

#### `snapshot` -- Extract DOM tree as structured data

```yaml
# Extract elements matching a CSS selector
- snapshot: ".result-item"

# Full-page snapshot (no params)
- snapshot: null

# Field-specific extraction
- snapshot:
    selector: ".card"
    fields: [title, price, url]
```

Returns a list of dicts with `_index`, `tag`, `text`, and `attrs` keys.

#### `evaluate` -- Execute JavaScript in the page context

This is the primary data extraction step. The JS code runs in the browser page context and its return value becomes the pipeline data.

```yaml
- evaluate: |
    (() => {
      const items = [];
      document.querySelectorAll('.item').forEach((el, i) => {
        items.push({
          rank: i + 1,
          title: el.querySelector('.title')?.textContent?.trim() || '',
          url: el.querySelector('a')?.href || ''
        });
      });
      return items;
    })()
```

**Security restrictions:** The following patterns are blocked in evaluate code: `fetch(`, `XMLHttpRequest`, `WebSocket`, `eval(`, `Function(`, `document.write`, `document.cookie`, `localStorage`, `sessionStorage`, `indexedDB`, `.src=`, `location.assign`, `location.replace`, `window.open`, `<script`, `import(`, `require(`.

**Timeout:** Default 5 seconds. Override with a dict param:

```yaml
- evaluate:
    code: "(() => { ... })()"
    _timeout: 10              # seconds
```

#### `intercept` -- Capture XHR/Fetch network responses

Installs temporary network interceptors to capture API responses that SPA sites use internally:

```yaml
- intercept:
    url_pattern: "/api/search"   # Substring match on request URLs
    method: "POST"               # Optional: filter by method
    max_results: 50              # Max responses to capture (default: 50)
```

Also accepts a simple string (url_pattern only):

```yaml
- intercept: "/api/data"
```

Auto-cleans up interceptors after 30 seconds. Returns a list of captured response objects with `url`, `method`, `status`, and `body` fields.

#### `tap` -- Call Vue/Pinia/Vuex store action (SPA sites)

For Single Page Applications that expose state via Vue stores:

```yaml
# Simple shape: direct store read
- tap:
    store: "useSearchStore"
    action: "search"
    getter: "results"

# Full shape: with network interception
- tap:
    store: "useFeedStore"
    action: "fetchFeed"
    capture: "/api/feed"          # URL pattern to intercept
    select: "data.list"           # Dot-path sub-selection from response
    framework: "pinia"            # pinia (default) | vuex
    timeout: 5                    # Seconds to wait for capture
    args: ["${{ args.category }}"]
```

#### `download` -- Download a file to disk

```yaml
- download:
    url: "https://example.com/report.csv"
    save_dir: "./downloads"
    filename: "report.csv"        # Optional; inferred from URL if omitted
```

Uses browser `fetch()` with `credentials: include` to inherit cookies/auth. Returns the local file path.

### Data steps (pure transformation, no browser needed)

These steps operate on the data passed between pipeline steps. They do not require a page handle.

#### `fetch` -- Make an HTTP request

```yaml
# Simple GET
- fetch: "https://api.example.com/data"

# With parameters
- fetch:
    url: "https://api.example.com/search"
    method: "GET"                # GET | POST | PUT | DELETE | PATCH | HEAD | OPTIONS
    params:                      # Query parameters (merged into URL)
      q: "${{ args.query }}"
      limit: 20
    headers:                     # Custom headers
      Authorization: "Bearer xxx"
    body:                        # Request body (for POST/PUT/PATCH)
      key: "value"
    browser: true                # Use browser fetch (inherits cookies) vs Python aiohttp
```

SSRF protection applies: private IP ranges are blocked.

#### `select` -- Extract a sub-field by dot-path

```yaml
- select: "data.items"          # Navigate nested data structure
- select: "data.list[0].title"  # Array indexing supported
```

#### `map` -- Transform array items with template expressions

```yaml
- map:
    title: "${{ item.name }}"
    url: "${{ item.link }}"
    rank: "${{ index + 1 }}"
    display: "${{ item.title | upper }}"
```

Inside `map`, you have access to `item` (current array element) and `index` (zero-based position).

#### `filter` -- Filter array items

String expression format (safe subset):

```yaml
- filter: "item.category == 'technology' && item.score > 50"
```

Dict format (exact match):

```yaml
- filter:
    status: "active"
    type: "premium"
```

Only `item.field == 'value'` / `item.field != 'value'` patterns combined with `&&` or `||` are allowed in expression mode.

#### `sort` -- Sort array by field

```yaml
- sort: "price"                 # Ascending by field
- sort:
    field: "date"
    reverse: true               # Descending
```

#### `limit` -- Truncate array to N items

```yaml
- limit: 10
- limit: "${{ args.limit }}"    # Template expression
```

---

## Template variables

All string values in step parameters support `${{ }}` template expressions resolved by the Template Engine (19 built-in filters).

### Syntax

```
${{ expression }}
```

### Available variables

| Variable | Scope | Description |
|----------|-------|-------------|
| `args.xxx` | Always | User-provided argument value |
| `data` | Always | Output from the previous step |
| `item.xxx` | Inside `map`/`filter` | Current array item field |
| `index` | Inside `map`/`filter` | Current zero-based index |

### Common usage examples

```yaml
# URL encoding for query parameters
- navigate: "https://www.baidu.com/s?wd=${{ args.query | urlencode }}"

# Arithmetic
- limit: "${{ args.limit * 2 }}"

# Fallback defaults
- map:
    label: "${{ item.displayName | default(item.name) }}"

# String transformations
- map:
    slug: "${{ item.title | slugify }}"
    short: "${{ item.description | truncate(80) }}"
    upper_title: "${{ item.title | upper }}"

# Logical OR (coalesce)
- map:
    name: "${{ item.fullName || item.username | trim }}"

# Complex expressions
- sort: "${{ Math.min(args.limit, 50) }}"
```

### Pipe filters reference (19 total)

| Filter | Args | Example | Description |
|--------|------|---------|-------------|
| `default(value)` | 1 | `\| default("N/A")` | Fallback when value is null/empty |
| `truncate(n)` | 1 | `\| truncate(100)` | Truncate string, append "..." |
| `replace(old, new)` | 2 | `\| replace(" ", "-")` | String replacement |
| `join(sep)` | 1 | `\| join(", ")` | Join array elements |
| `upper` | 0 | `\| upper` | Uppercase |
| `lower` | 0 | `\| lower` | Lowercase |
| `trim` / `strip` | 0 | `\| trim` | Whitespace trim |
| `keys` | 0 | `\| keys` | Dict keys as list |
| `length` | 0 | `\| length` | Length of string/list |
| `first` | 0 | `\| first` | First array element |
| `last` | 0 | `\| last` | Last array element |
| `json` | 0 | `\| json` | JSON serialize |
| `slugify` | 0 | `\| slugify` | URL-friendly slug |
| `sanitize` | 0 | `\| sanitize` | Replace unsafe filename chars |
| `ext` | 0 | `\| ext` | File extension from path |
| `basename` | 0 | `\| basename` | Basename from path/URL |
| `urlencode` | 0 | `\| urlencode` | Percent-encode for URLs |
| `urldecode` | 0 | `\| urldecode` | URL-decode |
| `int` | 0 | `\| int` | Convert to integer |
| `float` | 0 | `\| float` | Convert to float |

**Security:** Template evaluation is sandboxed via AST parsing with length limits, forbidden pattern blocklists, and context sanitization (JSON round-trip to sever prototype chains).

---

## Validation rules

The validator (`validator.py`) checks every adapter at load time. Adapters that fail validation are **not registered** and a warning is logged. The checks are:

### 1. Required fields
`site`, `name`, and `pipeline` must be present.

### 2. Pipeline structure
- `pipeline` must be a non-empty list
- Each step must be a dict with exactly one key-value pair
- The step key must be a registered step name (one of: `navigate`, `click`, `type`, `wait`, `press`, `snapshot`, `evaluate`, `intercept`, `tap`, `download`, `fetch`, `select`, `map`, `filter`, `sort`, `limit`)

### 3. Strategy validation
Must be one of: `public`, `ui`, `dom`, `cookie`, `intercept`, `header`, `store-action`.

### 4. Args type validation
Every `args.*.type` must be one of: `str`, `int`, `float`, `bool`.

### 5. Browser consistency
If `browser: false`, the pipeline must not contain `navigate` steps (contradiction).

### Additional runtime validations
- **URL safety**: All URLs in `navigate` and `fetch` steps are validated for scheme (http/https only), blocked schemes (`javascript:`, `data:`, `file:`, etc.), and private IP ranges (SSRF protection).
- **CSS selector safety**: Selectors in `click`, `wait`, `snapshot` are validated against an allowlist of characters.
- **JS safety**: Code in `evaluate` steps is scanned for dangerous patterns (`fetch(`, `eval(`, `document.cookie`, etc.).

---

## Example: minimal adapter

A minimal working adapter that navigates to a page and extracts data:

```yaml
# adapters/example/hello.yaml
site: example
name: hello
description: Fetch example.com heading text
strategy: public
browser: true

pipeline:
  - navigate: "https://example.com"
  - evaluate: |
      (() => {
        const h1 = document.querySelector('h1');
        return h1 ? h1.textContent.trim() : 'No heading found';
      })()
```

Run it:

```python
from agent_browser.adapters.runner import run_adapter
result = await run_adapter(site="example", command="hello")
# result: ["Example Domain"]
```

---

## Example: public API adapter

An adapter that uses `fetch` with `browser: false` -- no browser session needed:

```yaml
# adapters/github/trending.yaml
site: github
name: trending
description: Fetch GitHub trending repositories (public API)
strategy: public
browser: false

args:
  language:
    type: str
    default: ""
    description: Programming language filter (e.g., "python", "")
  since:
    type: str
    default: "daily"
    description: Time range: daily, weekly, monthly

columns: [author, name, url, description, stars, forks, today_stars]

pipeline:
  - fetch:
      url: "https://api.github.com/search/repositories"
      method: "GET"
      params:
        q: "stars:>100 language:${{ args.language }} created:>${{ args.since == 'weekly' && 'now-7d' || args.since == 'monthly' && 'now-30d' || 'now-1d' }}"
        sort: "stars"
        order: "desc"
        per_page: "10"
      headers:
        Accept: "application/vnd.github.v3+json"
  - select: "items"
  - map:
      author: "${{ item.owner.login }}"
      name: "${{ item.name }}"
      url: "${{ item.html_url }}"
      description: "${{ item.description | truncate(120) }}"
      stars: "${{ item.stargazers_count }}"
      forks: "${{ item.forks_count }}"
      today_stars: "${{ 0 }}"  # GitHub API doesn't provide daily delta
  - limit: 10
```

---

## Example: full DOM scraping adapter

A complete real-world adapter based on the existing Baidu search adapter:

```yaml
# adapters/baidu/search.yaml
site: baidu
name: search
description: Baidu search and extract results
strategy: cookie
browser: true

stealth:
  warmup: true
  human_click: true
  human_type: true
  request_delay: [0.5, 2.0]
  scroll_before: true
  jitter: true

args:
  query:
    type: str
    required: true
    description: Search keyword
  limit:
    type: int
    default: 5
    description: Number of results to return

columns: [rank, title, url, description]

pipeline:
  - navigate: "https://www.baidu.com/s?wd=${{ args.query | urlencode }}"
  - wait:
      selector: ".result"
      timeout: 8000
  - evaluate: |
      (() => {
        const results = [];
        document.querySelectorAll('.result.c-container, .c-container').forEach((el, i) => {
          const h3 = el.querySelector('h3 a, h3');
          const abstract = el.querySelector('.c-abstract, .c-span-last, .content-right_8Zs40');
          results.push({
            rank: i + 1,
            title: h3 ? h3.textContent.trim() : '',
            url: h3 && h3.tagName === 'A' ? h3.href : (h3 ? h3.querySelector('a')?.href || '' : ''),
            description: abstract ? abstract.textContent.trim().substring(0, 200) : ''
          });
        });
        return results;
      })()
  - limit: "${{ args.limit }}"
```

Key patterns demonstrated:
- **`${{ args.query | urlencode }}`** -- safely encode user input in URL query parameter
- **`wait` with selector** -- ensure dynamic content has loaded before extraction
- **`evaluate` with IIFE** -- run JS that queries the DOM and returns structured data
- **`limit` with template** -- respect user-specified result count

---

## Testing your adapter

### 1. Validate offline (no browser needed)

```python
import yaml
from agent_browser.adapters.validator import validate_adapter

with open("adapters/mysite/mycmd.yaml") as f:
    adapter = yaml.safe_load(f)

errors = validate_adapter(adapter)
if errors:
    print("Validation FAILED:")
    for e in errors:
        print(f"  - {e}")
else:
    print("Validation PASSED")
```

### 2. Validate all loaded adapters

```python
from agent_browser.adapters.validator import validate_all_adapters

results = validate_all_adapters()
for key, errs in results.items():
    status = "OK" if not errs else f"FAIL: {errs}"
    print(f"  {key}: {status}")
```

### 3. Run the adapter end-to-end

```python
import asyncio
from agent_browser.adapters.runner import run_adapter

async def test():
    result = await run_adapter(
        site="baidu",
        command="search",
        query="agent browser",
        limit=3,
    )
    for row in result:
        print(row)

asyncio.run(test())
```

### 4. Test individual pipeline steps

```python
import asyncio
from agent_browser.pipeline.executor import execute_pipeline
from agent_browser.main import create_session, delete_session

async def test_pipeline():
    session_id = await create_session()
    try:
        pipeline = [
            {"navigate": "https://www.baidu.com/s?wd=test"},
            {"wait": {"selector": ".result", "timeout": 8000}},
            {"evaluate": "(() => document.title)()"},
        ]
        result = await execute_pipeline(
            steps=pipeline,
            session_id=session_id,
            args={},
        )
        print(f"Result: {result}")
    finally:
        await delete_session(session_id)

asyncio.run(test_pipeline())
```

---

## Contributing workflow

1. **Fork** the repository and clone your fork

2. **Create the adapter YAML file** in the correct location:
   ```
   adapters/<site-name>/<command-name>.yaml
   ```

3. **Validate locally** using `validate_adapter()` (see Testing section above)

4. **Test execution** using `run_adapter()` with realistic inputs

5. **Verify stealth settings** -- if targeting a protected site, set appropriate `stealth` config (at minimum `warmup: true` and `human_click: true`)

6. **Commit** your changes with a clear message:
   ```
   feat(adapter): add <site>/<command> adapter for <purpose>
   ```

7. **Push** and open a pull request

### PR checklist

- [ ] Adapter passes `validate_adapter()` with zero errors
- [ ] Adapter has been tested end-to-end with `run_adapter()`
- [ ] `site` and `name` are lowercase snake_case
- [ ] All `args` have `type`, `description`, and sensible `default` values
- [ ] `evaluate` JS code does not use blocked patterns (no `fetch(`, `eval(`, etc.)
- [ ] URLs use `https://` scheme and avoid private IP addresses
- [ ] If `browser: false`, pipeline contains no `navigate` steps
- [ ] `columns` field documents expected output shape
- [ ] `description` field explains what the adapter does

### Tips for writing robust adapters

- **Always use `wait` after `navigate`** -- pages load asynchronously; give selectors time to appear
- **Use defensive JS in `evaluate`** -- check for `null` with optional chaining (`?.`) and fallback values
- **Prefer CSS classes over complex selectors** -- class names tend to be more stable than nested structural selectors
- **Set reasonable timeouts** -- `wait` defaults to 10s; increase for slow sites but keep under 30s
- **Use `limit` as the last step** -- caps output size regardless of how many items the page returns
- **Encode URL parameters** -- always use `${{ args.value | urlencode }}` in query strings
- **Test with multiple inputs** -- verify the adapter handles edge cases (empty results, special characters, very long content)
