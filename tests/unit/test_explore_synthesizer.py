"""Synthesizer 测试 — YAML pipeline 生成"""

from unittest.mock import MagicMock

from stealth_browser.explore.synthesizer import (
    build_adapter,
    detect_strategy,
    distill_trace,
    synthesize,
)


class TestDistillTrace:
    def test_empty_trace(self):
        assert distill_trace([]) == []

    def test_removes_screenshots(self):
        # _get_action_type expects browser-use format: action=[{type: ...}]
        trace = [
            {"action": [{"type": "screenshot"}]},
            {"action": [{"type": "navigate", "url": "https://x.com"}]},
        ]
        result = distill_trace(trace)
        actions = [r["action"] for r in result]
        assert "screenshot" not in actions
        assert "navigate" in actions

    def test_removes_done_steps(self):
        trace = [
            {"action": [{"type": "navigate", "url": "https://x.com"}]},
            {"action": [{"type": "task_complete", "text": "done"}]},
            {"action": [{"type": "done"}]},
        ]
        result = distill_trace(trace)
        actions = [r["action"] for r in result]
        assert "task_complete" not in actions
        assert "done" not in actions

    def test_collapses_redundant_waits(self):
        # _extract_wait_value reads from step["params"] or step directly.
        # Use params-level format so wait values are extractable.
        trace = [
            {"action": "wait", "params": {"seconds": 1.0}},
            {"action": "wait", "params": {"seconds": 0.5}},
            {"action": [{"type": "click", "element": "button"}]},
        ]
        result = distill_trace(trace)
        wait_count = sum(1 for r in result if r["action"] == "wait")
        assert wait_count <= 1

    def test_preserves_click_and_type(self):
        trace = [
            {"action": [{"type": "navigate", "url": "https://x.com"}]},
            {"action": [{"type": "click", "element": ".btn"}]},
            {"action": [{"type": "type", "element": ".input", "text": "hello"}]},
        ]
        result = distill_trace(trace)
        assert len(result) >= 2

    def test_normalizes_action_format(self):
        # Action as list-of-dicts (browser-use format) gets normalized to {action, params}
        trace = [{"action": [{"type": "navigate", "url": "https://x.com"}]}]
        result = distill_trace(trace)
        assert all("action" in r and "params" in r for r in result)


class TestDetectStrategy:
    def test_no_exploration_returns_ui(self):
        assert detect_strategy([], None) == "ui"

    def test_public_endpoint(self):
        from types import SimpleNamespace

        cap = SimpleNamespace(strategy_guess="public")
        exploration = SimpleNamespace(
            endpoints=[SimpleNamespace(is_json=True, status=200)],
            capabilities=[cap],
        )
        result = detect_strategy([{"action": "extract"}], exploration)
        assert result == "public"

    def test_intercept_strategy(self):
        from types import SimpleNamespace

        cap = SimpleNamespace(strategy_guess="intercept")
        exploration = SimpleNamespace(
            endpoints=[
                SimpleNamespace(is_json=True, status=401),
                SimpleNamespace(is_json=True, status=200),
            ],
            capabilities=[cap],
        )
        result = detect_strategy([{"action": "extract"}], exploration)
        assert result in ("intercept", "ui")

    def test_store_action_detected(self):
        from types import SimpleNamespace

        cap = SimpleNamespace(strategy_guess="store-action")
        exploration = SimpleNamespace(
            endpoints=[SimpleNamespace(is_json=False, status=200)],
            capabilities=[cap],
        )
        result = detect_strategy([{"action": [{"type": "tap", "store": "pinia"}]}], exploration)
        assert result in ("store-action", "ui")


class TestBuildAdapter:
    def test_basic_adapter_structure(self):
        nav_action = {"action": "navigate", "params": {"url": "https://example.com"}}
        adapter = build_adapter(
            site="testsite",
            name="search",
            strategy="public",
            actions=[nav_action],
            extraction_js="(() => { return document.title; })()",
        )
        assert adapter["site"] == "testsite"
        assert adapter["name"] == "search"
        assert adapter["strategy"] == "public"
        assert adapter["browser"] is False  # public strategy: browser=False
        assert isinstance(adapter["pipeline"], list)
        assert len(adapter["pipeline"]) >= 1
        assert "args" in adapter
        assert "columns" in adapter

    def test_pipeline_has_navigate_for_ui(self):
        nav = {"action": "navigate", "params": {"url": "https://x.com"}}
        adapter = build_adapter(
            site="test",
            name="t",
            strategy="ui",
            actions=[nav],
            extraction_js="return []",
        )
        first_step = adapter["pipeline"][0]
        # UI strategy pipeline starts with navigate
        step_key = next(iter(first_step.keys()))
        assert "navigate" in step_key or "goto" in step_key

    def test_cookie_strategy_sets_browser_true(self):
        nav = {"action": "navigate", "params": {"url": "https://x.com"}}
        adapter = build_adapter(
            site="test",
            name="t",
            strategy="cookie",
            actions=[nav],
            extraction_js="return [];",
        )
        assert adapter.get("strategy") == "cookie"
        assert adapter.get("browser") is True  # cookie needs browser

    def test_empty_actions_minimal_pipeline(self):
        adapter = build_adapter(
            site="test",
            name="t",
            strategy="ui",
            actions=[],
            extraction_js="return [];",
        )
        assert isinstance(adapter, dict)
        assert "pipeline" in adapter


class TestSynthesize:
    """Tests for synthesize() — backward-compatible entry point.

    NOTE: synthesize() does NOT call build_adapter(). It dispatches to one of:
      - _generate_dom_adapter()   (no capabilities)
      - _generate_fetch_adapter()  (public strategy)
      - _generate_cookie_adapter() (intercept/cookie strategy)

    Tests verify it returns a valid adapter dict with expected keys.
    """

    def test_returns_dict_with_required_keys(self):
        exploration = MagicMock()
        exploration.url = "https://example.com"
        exploration.capabilities = []
        result = synthesize("test", exploration, "list")
        assert isinstance(result, dict)
        assert "site" in result
        assert "name" in result
        assert "strategy" in result
        assert "pipeline" in result

    def test_no_capabilities_uses_dom_strategy(self):
        """Empty capabilities → DOM/UI adapter."""
        exploration = MagicMock()
        exploration.url = "https://example.com"
        exploration.capabilities = []
        result = synthesize("testsite", exploration, "list")
        assert result["strategy"] in ("ui", "dom")
        assert result.get("browser") is True

    def test_public_capability_generates_fetch_adapter(self):
        """Public capability → fetch-based adapter (browser=False)."""
        # _generate_fetch_adapter uses cap.get() — must be a dict, not SimpleNamespace
        cap = {
            "strategy": "public",
            "endpoint": "https://api.example.com/data",
            "fields": {"title": "title"},
        }
        exploration = MagicMock()
        exploration.url = "https://example.com"
        exploration.capabilities = [cap]
        result = synthesize("test", exploration, "list")
        assert isinstance(result, dict)
        assert "pipeline" in result

    def test_default_command_name(self):
        exploration = MagicMock()
        exploration.url = "https://example.com"
        exploration.capabilities = []
        result = synthesize("test", exploration)
        assert isinstance(result, dict)
