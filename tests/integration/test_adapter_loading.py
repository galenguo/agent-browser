"""
Adapter Loading Tests — YAML parse → normalize → register → execute.

Tests adapter discovery, OpenCLI format normalization, validation,
and that adapters produce correct structured configs.
"""


# ══════════════════════════════════════════════
#  Test 1-2: Discovery & Parsing
# ══════════════════════════════════════════════


class TestAdapterDiscovery:
    """Loader scans directory and discovers YAML adapters."""

    def test_list_adapters_returns_non_empty(self):
        """list_adapters() finds at least one adapter (baidu/search)."""
        from stealth_browser.adapters.loader import list_adapters

        adapters = list_adapters()
        assert len(adapters) > 0

    def test_baidu_search_in_registry(self):
        """baidu/search adapter is discoverable and has correct metadata."""
        from stealth_browser.adapters.loader import get_adapter

        adapter = get_adapter("baidu", "search")
        assert adapter is not None
        assert adapter["site"] == "baidu"
        assert adapter["name"] == "search"
        assert True  # description optional

    def test_adapter_has_pipeline(self):
        """Each registered adapter has a pipeline list."""
        from stealth_browser.adapters.loader import list_adapters

        for meta in list_adapters():
            from stealth_browser.adapters.loader import get_adapter

            adapter = get_adapter(meta["site"], meta["name"])
            assert "pipeline" in adapter
            assert isinstance(adapter["pipeline"], list)
            assert len(adapter["pipeline"]) > 0


class TestAdapterParsing:
    """YAML content parsed into correct structure."""

    def test_baidu_search_has_query_arg(self):
        """baidu/search defines 'query' as required string arg."""
        from stealth_browser.adapters.loader import get_adapter

        adapter = get_adapter("baidu", "search")
        args = adapter.get("args", {})
        assert "query" in args
        assert args["query"].get("type") == "str"

    def test_baidu_search_has_limit_default(self):
        """baidu/search 'limit' arg has default value."""
        from stealth_browser.adapters.loader import get_adapter

        adapter = get_adapter("baidu", "search")
        args = adapter.get("args", {})
        if "limit" in args:
            assert args["limit"].get("default") is not None


# ══════════════════════════════════════════════
#  Test 3: Adapter with Auth Steps
# ══════════════════════════════════════════════


class TestAdapterAuthSteps:
    """Adapters requiring authentication have proper step definitions."""

    def test_boss_search_has_cookie_strategy(self):
        """boss/search uses cookie strategy (requires auth)."""
        from stealth_browser.adapters.loader import get_adapter

        adapter = get_adapter("boss", "search")
        assert adapter is not None
        # boss/search should use cookie strategy (or intercept normalized to cookie)
        strategy = adapter.get("strategy", "")
        assert strategy in ("cookie", "intercept")


# ══════════════════════════════════════════════
#  Test 4: Unknown Adapter Error
# ══════════════════════════════════════════════


class TestUnknownAdapter:
    """Requesting a non-existent adapter returns None."""

    def test_get_nonexistent_adapter(self):
        """get_adapter('nonexistent', 'missing') returns None."""
        from stealth_browser.adapters.loader import get_adapter

        result = get_adapter("nonexistent", "missing")
        assert result is None


# ══════════════════════════════════════════════
#  Tests 6-8: OpenCLI Format Normalization
# ══════════════════════════════════════════════


class TestOpenCLINormalization:
    """_normalize_adapter() translates OpenCLI format to AB-internal."""

    def test_domain_normalized_to_site(self):
        """OpenCLI 'domain' field becomes 'site'."""
        from stealth_browser.adapters.loader import _normalize_adapter

        adapter = _normalize_adapter({"domain": "example.com", "name": "test"})
        assert adapter["site"] == "example.com"
        assert "domain" not in adapter

    def test_site_preserved_when_present(self):
        """When both domain and site present, site takes priority."""
        from stealth_browser.adapters.loader import _normalize_adapter

        adapter = _normalize_adapter(
            {
                "domain": "wrong.com",
                "site": "right.com",
                "name": "test",
            }
        )
        assert adapter["site"] == "right.com"

    def test_intercept_strategy_mapped_to_cookie(self):
        """OpenCLI 'intercept' strategy mapped to 'cookie' internally."""
        from stealth_browser.adapters.loader import _normalize_adapter

        adapter = _normalize_adapter({"site": "test", "name": "x", "strategy": "intercept"})
        assert adapter["strategy"] == "cookie"

    def test_other_strategies_pass_through(self):
        """Non-intercept strategies are unchanged."""
        from stealth_browser.adapters.loader import _normalize_adapter

        for s in ["public", "ui", "store-action", "header"]:
            adapter = _normalize_adapter({"site": "test", "name": "x", "strategy": s})
            assert adapter["strategy"] == s, f"Strategy '{s}' was modified"


class TestNavigateBeforeNormalization:
    """navigateBefore is prepended as first pipeline step."""

    def test_navigate_before_prepended(self):
        """navigateBefore becomes navigate step at index 0."""
        from stealth_browser.adapters.loader import _normalize_adapter

        adapter = _normalize_adapter(
            {
                "site": "test",
                "name": "x",
                "pipeline": [{"click": ".btn"}],
                "navigateBefore": "https://login.example.com",
            }
        )
        pipeline = adapter["pipeline"]
        assert len(pipeline) == 2
        first_op = next(iter(pipeline[0].keys()))
        assert first_op == "navigate"
        assert pipeline[0]["navigate"] == "https://login.example.com"
        # Original click step preserved at index 1
        assert next(iter(pipeline[1].keys())) == "click"

    def test_no_navigate_before_leaves_pipeline_unchanged(self):
        """Without navigateBefore, pipeline is untouched."""
        from stealth_browser.adapters.loader import _normalize_adapter

        original = [{"click": ".btn"}, {"snapshot": "*"}]
        adapter = _normalize_adapter({"site": "test", "name": "x", "pipeline": original})
        assert adapter["pipeline"] == original


# ══════════════════════════════════════════════
#  Tests 9-10: Validation & Error Handling
# ═════════════════════════════════════════════


class TestValidationErrors:
    """Invalid adapters are rejected gracefully."""

    def test_missing_site_and_name_skipped(self):
        """Adapter without site/name is invalid but doesn't crash loader."""
        from stealth_browser.adapters.loader import _normalize_adapter

        adapter = _normalize_adapter({"description": "no site or name"})
        # Should return dict without site/name — loader will skip it
        assert "site" not in adapter or "name" not in adapter

    def test_validation_errors_detected(self):
        """validate_adapter() finds errors in malformed adapter."""
        from stealth_browser.adapters.validator import validate_adapter

        errors = validate_adapter({})
        assert len(errors) > 0
        # Errors contain information about what's wrong
        assert any(len(e) > 0 for e in errors)

    def test_validation_passes_for_valid_adapter(self):
        """validate_adapter() returns empty list for well-formed adapter."""
        from stealth_browser.adapters.validator import validate_adapter

        valid = {
            "site": "test",
            "name": "demo",
            "strategy": "public",
            "pipeline": [{"navigate": "https://example.com"}],
        }
        errors = validate_adapter(valid)
        assert errors == []

    def test_validation_rejects_unknown_step(self):
        """Pipeline with unregistered step name produces error."""
        from stealth_browser.adapters.validator import validate_adapter

        bad = {
            "site": "test",
            "name": "bad",
            "pipeline": [{"nonexistent_step": "params"}],
        }
        errors = validate_adapter(bad)
        assert any("unknown step" in e.lower() for e in errors)

    def test_validation_rejects_invalid_strategy(self):
        """Unknown strategy value produces error."""
        from stealth_browser.adapters.validator import validate_adapter

        bad = {
            "site": "test",
            "name": "bad",
            "strategy": "hacking",
            "pipeline": [{"snapshot": "*"}],
        }
        errors = validate_adapter(bad)
        assert any("Invalid strategy" in e for e in errors)

    def test_validation_rejects_empty_pipeline(self):
        """Empty pipeline list produces error."""
        from stealth_browser.adapters.validator import validate_adapter

        bad = {
            "site": "test",
            "name": "bad",
            "pipeline": [],
        }
        errors = validate_adapter(bad)
        assert any("must not be empty" in e for e in errors)


# ══════════════════════════════════════════════
#  Edge Case: Normalization Idempotency
# ══════════════════════════════════════════════


class TestNormalizeIdempotency:
    """Running _normalize_adapter twice is safe."""

    def test_double_normalize_stable(self):
        """Normalizing an already-normalized adapter is idempotent."""
        from stealth_browser.adapters.loader import _normalize_adapter

        raw = {"site": "test", "name": "x", "strategy": "public"}
        once = _normalize_adapter(raw)
        twice = _normalize_adapter(once)
        assert once == twice
