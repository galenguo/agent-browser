# Adapter Guide

Site adapters provide zero-LLM-cost deterministic automation for known websites. Instead of running a full ReAct loop, an adapter executes a pre-defined pipeline of steps (navigate, fill, submit, extract).

Adapters are YAML files deployed on the server under `adapters/{site}/`. Each adapter defines:
- Site URL patterns
- Available commands (search, login, extract, etc.)
- Step templates with CSS selectors and JavaScript extraction
- Error handling rules

As a SkillBrowser client, you do not load or execute adapters directly. Instead, you submit a natural language task via `sb.run_task()` and the server routes it through the appropriate adapter or agent pipeline.

## Running Adapter-Powered Tasks

```python
from agent_browser.skill.scripts.browser_cli import SkillBrowser

sb = SkillBrowser()
sid = await sb.create_session()

# Boss Zhipin search -- the server recognizes the intent and uses the boss/search adapter
result = await sb.run_task(sid, "Search for Python jobs in Beijing on Boss Zhipin")

# Bilibili hot videos
result = await sb.run_task(sid, "Get the top 10 hot videos on Bilibili")

# Zhihu trending
result = await sb.run_task(sid, "Show me the Zhihu hot list")

await sb.delete_session(sid)
```

The server-side adapter system handles:
- Matching the task to the correct adapter (boss, bilibili, zhihu, etc.)
- Executing the YAML pipeline with stealth middleware and error recovery
- Returning structured results

## Adapter YAML Format

Adapters live on the server in the `adapters/{site}/` directory. Here is what they look like so you can understand server logs or create new ones for deployment.

### Structure

```yaml
site: <site-name>             # e.g. "boss", "zhihu", "bilibili"
name: <command-name>          # e.g. "search", "hot"
description: <human-readable> # e.g. "Boss Zhipin job search"
strategy: cookie              # Authentication strategy
browser: true                 # Requires a browser session

args:                         # Input parameters
  <arg-name>:
    type: str | int
    required: true | false
    default: <value>
    description: <purpose>

columns: [col1, col2, ...]    # Output column names

pipeline:                     # Ordered list of steps
  - navigate: "<url>"
  - wait:
      selector: "<css>"
      timeout: <ms>
  - evaluate: |
      <JavaScript extraction>
  - limit: "${{ args.limit }}"
```

### Step Types

| Step | Purpose | Key Fields |
|------|---------|------------|
| `navigate` | Open a URL | URL string (supports `${{ args.x }}` template vars) |
| `wait` | Wait for element | `selector`, `timeout` (ms) |
| `evaluate` | Run JS, return data | JavaScript expression (IIFE recommended) |
| `limit` | Truncate results | Number or template expression |
| `fill` | Type into input | `selector`, `text` |
| `click` | Click element | `selector` |
| `scroll` | Scroll page | `direction`, `amount` |

### Template Variables

Inside pipeline steps, use `${{ args.<name> }}` to reference input arguments. Filters are also available:

```
${{ args.query | urlencode }}   # URL-encode the value
${{ args.limit | int }}         # Cast to integer
```

## Existing Adapters

These adapters are deployed on the server and available for use via `sb.run_task()`.

### Boss Zhipin (boss/search)

Searches jobs on zhipin.com with anti-detection stealth configuration.

```yaml
site: boss
name: search
description: Boss Zhipin job search
strategy: cookie
browser: true

stealth:
  warmup: true
  human_click: true
  human_type: true
  request_delay: [1.0, 3.0]
  scroll_before: true
  jitter: true

args:
  query:
    type: str
    required: true
    description: Search keyword
  city:
    type: str
    default: ""
    description: City code (e.g. 101010100 for Beijing)
  limit:
    type: int
    default: 10
    description: Number of results

columns: [title, salary, company, location, experience, education]

pipeline:
  - navigate: "https://www.zhipin.com/web/geek/job?query=${{ args.query | urlencode }}&city=${{ args.city }}"
  - wait:
      selector: ".job-list-box li, .search-job-result li"
      timeout: 10000
  - evaluate: |
      (() => {
        const items = [];
        document.querySelectorAll('.job-list-box li, .search-job-result .job-card-wrapper').forEach((el) => {
          const titleEl = el.querySelector('.job-name a, .job-title');
          const salaryEl = el.querySelector('.salary, .job-salary');
          const companyEl = el.querySelector('.company-name a, .company-name');
          const locationEl = el.querySelector('.job-area, .job-area');
          const tagEls = el.querySelectorAll('.tag-list li, .job-info .tag-list li');
          const tags = Array.from(tagEls).map(t => t.textContent.trim());
          items.push({
            title: titleEl ? titleEl.textContent.trim() : '',
            salary: salaryEl ? salaryEl.textContent.trim() : '',
            company: companyEl ? companyEl.textContent.trim() : '',
            location: locationEl ? locationEl.textContent.trim() : '',
            experience: tags[0] || '',
            education: tags[1] || ''
          });
        });
        return items;
      })()
  - limit: "${{ args.limit }}"
```

### Zhihu Hot List (zhihu/hot)

Extracts the Zhihu trending topics list.

```yaml
site: zhihu
name: hot
description: Zhihu hot list
strategy: cookie
browser: true

args:
  limit:
    type: int
    default: 10
    description: Number of results

columns: [rank, title, url, hot_score, excerpt]

pipeline:
  - navigate: "https://www.zhihu.com/hot"
  - wait:
      selector: ".HotItem"
      timeout: 10000
  - evaluate: |
      (() => {
        const items = [];
        document.querySelectorAll('.HotItem').forEach((el, i) => {
          const titleEl = el.querySelector('.HotItem-title');
          const excerptEl = el.querySelector('.HotItem-excerpt');
          const linkEl = el.querySelector('.HotItem-content a');
          const metricsEl = el.querySelector('.HotItem-metrics');
          items.push({
            rank: i + 1,
            title: titleEl ? titleEl.textContent.trim() : '',
            url: linkEl ? linkEl.href : '',
            hot_score: metricsEl ? metricsEl.textContent.trim() : '',
            excerpt: excerptEl ? excerptEl.textContent.trim().substring(0, 100) : ''
          });
        });
        return items;
      })()
  - limit: "${{ args.limit }}"
```

### Bilibili Hot Videos (bilibili/hot)

Extracts the Bilibili popular video ranking.

```yaml
site: bilibili
name: hot
description: Bilibili hot video ranking
strategy: cookie
browser: true

args:
  limit:
    type: int
    default: 10
    description: Number of results

columns: [rank, title, url, play_count, danmaku, author]

pipeline:
  - navigate: "https://www.bilibili.com/v/popular/rank/all"
  - wait:
      selector: ".rank-item"
      timeout: 10000
  - evaluate: |
      (() => {
        const items = [];
        document.querySelectorAll('.rank-item').forEach((el, i) => {
          const titleEl = el.querySelector('.title, a.title');
          const authorEl = el.querySelector('.author, .up-name');
          const playEl = el.querySelectorAll('.data-box')[0];
          const danmakuEl = el.querySelectorAll('.data-box')[1];
          items.push({
            rank: i + 1,
            title: titleEl ? titleEl.textContent.trim() : '',
            url: titleEl ? titleEl.href : '',
            play_count: playEl ? playEl.textContent.trim() : '',
            danmaku: danmakuEl ? danmakuEl.textContent.trim() : '',
            author: authorEl ? authorEl.textContent.trim() : ''
          });
        });
        return items;
      })()
  - limit: "${{ args.limit }}"
```

## Adding a New Adapter

New adapters are created and deployed on the server side. The SkillBrowser client does not create adapters; it only uses them via `sb.run_task()`.

To add a new adapter:

1. Create a YAML file under `adapters/{site}/` on the server (e.g., `adapters/taobao/search.yaml`)
2. Define the `site`, `name`, `description`, `args`, `columns`, and `pipeline` fields
3. Write the CSS selectors and JavaScript extraction logic in the pipeline steps
4. Deploy the updated adapter directory to the server
5. Test by submitting a task: `result = await sb.run_task(sid, "Search for shoes on Taobao")`

Adapters are most valuable for sites you automate repeatedly (daily jobs, monitoring, bulk extraction). For one-off tasks, `sb.run_task()` in ReAct mode is simpler and more flexible since the agent figures out the page structure on the fly.
