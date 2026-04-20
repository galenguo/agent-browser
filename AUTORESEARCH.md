# autoresearch -- Stealth Browser Autonomous Optimization

## Setup

After user confirmation:
1. Create branch: `git checkout -b autoresearch/<tag>` (tag based on date, e.g., `apr2`)
2. Read all in-scope files for context
3. Run baseline: record baseline metrics
4. Confirm setup complete before starting experiment loop

## Optimization Goal

**Primary metric: success_rate (higher is better)**

**Secondary metrics**: avg_steps (lower is better), avg_time_seconds (lower is better), passed_tests (higher is better)

**Test scope**: 10 scenario categories, 20+ test cases:
1. Session lifecycle (create/delete/reconnect)
2. Basic navigation (Baidu/Bing/GitHub)
3. Search interaction (Baidu search "ai coding", extract top 5)
4. Data extraction (title/elements/result lists)
5. Multi-step composite (full search + extract + organize)
6. Multi-tab (parallel site operations)
7. Remote CDP connection
8. Error handling (invalid ref/non-existent session/invalid URL)
9. Anti-detection verification (fingerprint check/automation detection)
10. Multi-site coverage (Baidu/Bing/Taobao/Zhihu/GitHub)

## In-Scope Files (Agent may modify)

### Facade API layer (most frequently modified)
- `stealth_browser/main.py` -- Facade API (create_session, snapshot, click, fill)
- `stealth_browser/utils/refs_generator.py` -- Element reference generation
- `stealth_browser/session/session_manager.py` -- Session management

### Agent layer
- `stealth_browser/intelligence/agent_runner.py` -- Agent execution logic, prompt templates, action registration
- `stealth_browser/stealth/actions.py` -- Stealth action overrides

### Behavior simulation
- `stealth_browser/browser/human_behavior.py` -- Human behavior simulation parameters

### DOM processing
- `stealth_browser/explore/analysis.py` -- DOM structure analysis
- Explore module for LLM-friendly DOM serialization

### Agent enhancements
- Loop detection and task planning within intelligence module

## Read-Only Files (do not modify)

- `AUTORESEARCH.md` -- This file (experiment rules)
- `pyproject.toml` -- Project dependencies
- Test files and benchmark scripts
- Core stealth stack (`stealth_browser/browser/stealth_launcher.py`)
- Browser instance pool (`stealth_browser/browser/instance_pool.py`)

## Experiment Loop

Each experiment:
1. Modify one or a few files (atomic changes)
2. `git add` + `git commit -m "experiment: <description>"`
3. Run evaluation
4. Read results
5. Improvement -> keep commit; Regression -> `git reset --hard HEAD~1`
6. Record to results log

## Simplicity Principle

Given equivalent results, simpler code wins:
- Deleting code with same result = **must keep**
- 0.01 success_rate improvement adding 50 lines of complex code = probably not worth it
- Prefer "can I delete X and maintain success_rate" over "can I add Y to improve"

## NEVER STOP

Once the experiment loop starts, **do not pause**. Do not ask "should I continue?". Run autonomously until manually interrupted (Ctrl+C).

If stuck:
- Re-read in-scope files for new inspiration
- Reference browser-use source code for patterns
- Try more aggressive architectural changes (not just parameter tuning)
- Return to baseline, switch experiment direction
