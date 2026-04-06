# Adapter & Exploration Guide

Site adapters provide zero-LLM-cost deterministic automation for known websites. Instead of running a full ReAct loop, an adapter executes a pre-defined pipeline of steps (navigate, fill, submit, extract).

## Listing Available Adapters

```python
from agent_browser import list_adapters

adapters = await list_adapters()
# Returns: [{"name": "boss", "site": "boss.zhipin.com", "commands": ["search", ...]}, ...]
```

Adapters are YAML files under `adapters/{site}/` directory. Each adapter defines:
- Site URL patterns
- Available commands (search, login, extract, etc.)
- Step templates with CSS selectors
- Error handling rules

## Running an Adapter

```python
from agent_browser import create_session, run_adapter, delete_session

sid = await create_session()

# Boss Zhipin search
results = await run_adapter("boss", "search", query="Python", city="101010100")
# Returns: {"status": "completed", "data": [...], "extracted": [...]}

# Bilibili video search
results = await run_adapter("bilibili", "search", keyword="AI tutorial")

await delete_session(sid)
```

Adapter execution goes through the Pipeline engine v2.3 with full stealth middleware and error recovery.

## Auto-Exploring Unknown Sites

When no adapter exists for a target site, use the exploration module to automatically analyze DOM structure and generate one:

```python
from agent_browser import create_session, explore, synthesize, cascade

sid = await create_session()

# Step 1: Explore -- intercepts network requests, analyzes DOM
artifacts = await explore(
    sid,
    "https://example.com/articles",
    goal="Get article list with titles and links",
)
# Returns: {endpoints: [...], dom_structure: {...}, forms: [...], interactive_elements: [...]}

# Step 2: Cascade -- generate robust CSS selectors from exploration data
strategies = await cascade(
    sid,
    "https://example.com/articles",
    endpoints=artifacts.endpoints,
)
# Returns: [{selector: ".article-item h2 > a", confidence: 0.95, type: "link"}, ...]

# Step 3: Synthesize -- generate YAML adapter from artifacts + strategies
adapter_yaml = synthesize(
    "example",
    artifacts,
    command_name="articles",
)
# Returns: YAML string ready to write to adapters/example/ directory
```

### Exploration Output Fields

| Field | Description |
|-------|-------------|
| `endpoints` | Discovered API endpoints (URLs, methods, params) |
| `dom_structure` | Page layout: headers, nav, content areas, sidebars |
| `forms` | Login/search forms with input names and action URLs |
| `interactive_elements` | Buttons, links, inputs with CSS selectors and visibility |

### Cascade Selector Quality

Cascade generates selectors ranked by confidence:
- **0.9+**: Stable (ID, unique class, data attribute) -- use directly
- **0.7-0.9**: Good (class chain, structural) -- test before using
- **<0.7**: Fragile (positional, nth-child) -- manual review needed

## Adapter Development Workflow

1. **Explore** a target site to understand its structure
2. **Synthesize** an initial adapter YAML from exploration results
3. **Test** the adapter against real pages
4. **Refine** selectors that drift or fail
5. **Commit** the adapter to `adapters/{site}/` for reuse

After synthesis, the adapter file should be placed in the project's `adapters/` directory so it gets shipped with the package and shared with other users.

## Notes

- `explore()` requires LocalCDPBackend (CLI mode). Not available in API/remote mode.
- `synthesize()` returns a YAML string; you must write it to a file manually or via script.
- Adapters are most valuable for sites you automate repeatedly (daily jobs, monitoring, bulk extraction).
- For one-off tasks, ReAct mode (Mode 1) is simpler and more flexible.
