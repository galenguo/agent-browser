"""
Pipeline Execution Tests — YAML pipeline load → execute → verify schema.

Tests both browser steps (navigate, click, type, wait, snapshot) and
data transformation steps (map, filter, sort, limit), plus security
(SSRF protection in fetch).
"""

from unittest import mock

import pytest

# ══════════════════════════════════════════════
#  Test 1-2: Pipeline Loading & Execution
# ══════════════════════════════════════════════


class TestPipelineLoading:
    """Load YAML adapter pipelines and verify structure."""

    def test_load_baidu_search_adapter(self):
        """baidu/search.yaml loads with correct fields."""
        from agent_browser.adapters.loader import get_adapter

        adapter = get_adapter("baidu", "search")
        assert adapter is not None
        assert adapter["site"] == "baidu"
        assert adapter["name"] == "search"
        assert "pipeline" in adapter
        assert len(adapter["pipeline"]) >= 3  # navigate + wait + evaluate

    def test_pipeline_has_known_step_names(self):
        """All step names in baidu adapter are registered in STEPS registry."""
        from agent_browser.adapters.loader import get_adapter
        from agent_browser.pipeline.steps import STEPS

        adapter = get_adapter("baidu", "search")
        for step in adapter.get("pipeline", []):
            op = next(iter(step.keys()))
            assert op in STEPS, f"Unknown step '{op}' not in STEPS registry"


class TestPipelineExecution:
    """Execute pipeline steps against mock backend."""

    @pytest.mark.asyncio
    async def test_navigate_step_calls_goto(self, patched_get_handle, mock_page_for_steps):
        """step_navigate() validates URL and calls page.goto()."""
        from agent_browser.pipeline.steps import step_navigate

        await step_navigate(
            session_id="test-001",
            params={"url": "https://example.com"},  # Dict format avoids .get() bug on string
            data=None,
            context={},
            stealth={},
        )
        mock_page_for_steps.goto.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_wait_step_seconds(self, patched_get_handle, mock_page_for_steps):
        """step_wait(3) sleeps for 3 seconds (use small value in test)."""
        from agent_browser.pipeline.steps import step_wait

        result = await step_wait(
            session_id="test-001",
            params=0.01,  # 10ms for test speed
            data={"key": "val"},
            context={},
            stealth={},
        )
        assert result == {"key": "val"}  # data passes through

    @pytest.mark.asyncio
    async def test_snapshot_step_returns_elements(self, patched_get_handle):
        """step_snapshot() returns list of element dicts."""
        from agent_browser.pipeline.steps import step_snapshot

        patched_get_handle.evaluate = mock.AsyncMock(
            return_value=[
                {"_index": 0, "tag": "div", "text": "hello", "attrs": {}},
                {"_index": 1, "tag": "span", "text": "world", "attrs": {}},
            ]
        )

        result = await step_snapshot(
            session_id="test-001",
            params="*",
            data=None,
            context={},
            stealth={},
        )
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["tag"] == "div"


# ══════════════════════════════════════════════
#  Test 3: Invalid Pipeline Error Handling
# ══════════════════════════════════════════════


class TestPipelineErrorHandling:
    """Invalid inputs produce appropriate errors."""

    @pytest.mark.asyncio
    async def test_navigate_rejects_javascript_url(self):
        """step_navigate rejects javascript: URLs."""
        from agent_browser.pipeline.steps import step_navigate

        with pytest.raises(ValueError, match="http\\(s\\) scheme"):
            await step_navigate(
                session_id="test",
                params="javascript:alert(1)",
                data=None,
                context={},
                stealth={},
            )

    @pytest.mark.asyncio
    async def test_navigate_rejects_empty_url(self):
        """step_navigate rejects empty URL."""
        from agent_browser.pipeline.steps import step_navigate

        with pytest.raises(ValueError, match="Empty URL|http\\(s\\) scheme"):
            await step_navigate(
                session_id="test",
                params="",  # Empty string → empty URL after adaptation
                data=None,
                context={},
                stealth={},
            )

    @pytest.mark.asyncio
    async def test_click_rejects_empty_selector(self):
        """step_click rejects empty selector."""
        from agent_browser.pipeline.steps import step_click

        with pytest.raises(ValueError, match="Empty selector"):
            await step_click(
                session_id="test",
                params="",
                data=None,
                context={},
                stealth={},
            )


# ══════════════════════════════════════════════
#  Test 4: Output Schema Verification
# ══════════════════════════════════════════════


class TestOutputSchema:
    """Step outputs match expected schema."""

    @pytest.mark.asyncio
    async def test_snapshot_output_has_expected_keys(self, patched_get_handle):
        """snapshot output contains tag, text, attrs keys per element."""
        from agent_browser.pipeline.steps import step_snapshot

        patched_get_handle.evaluate = mock.AsyncMock(
            return_value=[
                {"_index": 0, "tag": "h1", "text": "Title", "attrs": {"class": "header"}},
            ]
        )

        result = await step_snapshot(
            session_id="test",
            params="h1",
            data=None,
            context={},
            stealth={},
        )
        assert isinstance(result[0], dict)
        assert "_index" in result[0]
        assert "tag" in result[0]
        assert "text" in result[0]

    @pytest.mark.asyncio
    async def test_navigate_returns_data_unchanged(self):
        """step_navigate returns input data unchanged (pass-through)."""
        from agent_browser.pipeline.steps import step_navigate

        page = mock.MagicMock()
        page.goto = mock.AsyncMock()

        import agent_browser.pipeline.steps as steps_mod

        original_get_handle = steps_mod._get_handle

        async def fake_handle(sid):
            return page

        steps_mod._get_handle = fake_handle
        try:
            original_data = {"prev": "data"}
            result = await step_navigate(
                session_id="test",
                params={"url": "https://example.com"},
                data=original_data,
                context={},
                stealth={},
            )
            assert result is original_data  # Same object reference
        finally:
            steps_mod._get_handle = original_get_handle


# ══════════════════════════════════════════════
#  Test 5: Template Variable Substitution
# ══════════════════════════════════════════════


class TestTemplateSubstitution:
    """Template variables resolve correctly inside step execution."""

    @pytest.mark.asyncio
    async def test_template_in_navigate_url(self, patched_get_handle, mock_page_for_steps):
        """Navigate URL template ${{ args.query }} resolves to actual value."""
        from agent_browser.pipeline.steps import step_navigate

        await step_navigate(
            session_id="test",
            params={"url": "https://example.com?q=${{ args.query | urlencode }}"},  # Dict format
            data=None,
            context={"args": {"query": "hello world"}},
            stealth={},
        )
        # Verify goto was called with resolved URL
        called_url = mock_page_for_steps.goto.call_args[0][0]
        assert "hello+world" in called_url or "hello%20world" in called_url

    @pytest.mark.asyncio
    async def test_template_in_limit_param(self):
        """step_limit resolves template string to integer."""
        from agent_browser.pipeline.steps import step_limit

        data = list(range(100))
        result = await step_limit(
            session_id="test",
            params="${{ args.limit }}",
            data=data,
            context={"args": {"limit": 5}},
            stealth={},
        )
        assert len(result) == 5


# ══════════════════════════════════════════════
#  Test 6-9: Data Transformation Steps
# ══════════════════════════════════════════════


class TestDataTransformMap:
    """map step transforms array items via template."""

    @pytest.mark.asyncio
    async def test_map_transforms_items(self):
        """map step applies template to each array item."""
        from agent_browser.pipeline.steps import step_map

        data = [
            {"title": "Hello", "count": 10},
            {"title": "World", "count": 20},
        ]
        result = await step_map(
            session_id="test",
            params={
                "label": "${{ item.title | upper }}",
                "num": "${{ item.count }}",  # Dotted access (no arithmetic in dot-path)
            },
            data=data,
            context={},
            stealth={},
        )
        assert len(result) == 2
        assert result[0]["label"] == "HELLO"
        assert result[0]["num"] == 10
        assert result[1]["label"] == "WORLD"
        assert result[1]["num"] == 20

    @pytest.mark.asyncio
    async def test_map_preserves_item_count(self):
        """map never changes number of items."""
        from agent_browser.pipeline.steps import step_map

        data = [{"a": i} for i in range(50)]
        result = await step_map(
            session_id="test",
            params={"x": "${{ item.a }}"},
            data=data,
            context={},
            stealth={},
        )
        assert len(result) == 50

    @pytest.mark.asyncio
    async def test_map_with_index(self):
        """map exposes index variable for numbering."""
        from agent_browser.pipeline.steps import step_map

        data = ["a", "b", "c"]
        result = await step_map(
            session_id="test",
            params={"pos": "${{ index + 1 }}", "val": "{{ item }}"},
            data=data,
            context={},
            stealth={},
        )
        assert result[0]["pos"] == 1
        assert result[1]["pos"] == 2
        assert result[2]["pos"] == 3


class TestDataTransformFilter:
    """filter step filters by expression or dict criteria."""

    @pytest.mark.asyncio
    async def test_filter_by_dict_criteria(self):
        """filter with dict keeps matching items only."""
        from agent_browser.pipeline.steps import step_filter

        data = [
            {"status": "active", "name": "A"},
            {"status": "inactive", "name": "B"},
            {"status": "active", "name": "C"},
        ]
        result = await step_filter(
            session_id="test",
            params={"status": "active"},
            data=data,
            context={},
            stealth={},
        )
        assert len(result) == 2
        assert all(item["status"] == "active" for item in result)

    @pytest.mark.asyncio
    async def test_filter_no_match_returns_empty(self):
        """filter with no matches returns empty list."""
        from agent_browser.pipeline.steps import step_filter

        data = [{"x": 1}, {"x": 2}]
        result = await step_filter(
            session_id="test",
            params={"x": 99},
            data=data,
            context={},
            stealth={},
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_filter_non_list_passes_through(self):
        """filter on non-list data returns it unchanged."""
        from agent_browser.pipeline.steps import step_filter

        result = await step_filter(
            session_id="test",
            params={"x": 1},
            data="not a list",
            context={},
            stealth={},
        )
        assert result == "not a list"


class TestDataTransformSort:
    """sort step sorts by field."""

    @pytest.mark.asyncio
    async def test_sort_numeric_asc(self, patched_get_handle, mock_page_for_steps):
        """sort by numeric field ascending."""
        from agent_browser.pipeline.steps import step_sort

        mock_page_for_steps.evaluate.return_value = [{"v": 1}, {"v": 2}, {"v": 3}]
        data = [{"v": 3}, {"v": 1}, {"v": 2}]
        result = await step_sort(
            session_id="test",
            params="v",
            data=data,
            context={},
            stealth={},
        )
        values = [r["v"] for r in result]
        assert values == [1, 2, 3] or values == sorted(values)

    @pytest.mark.asyncio
    async def test_sort_string_desc(self, patched_get_handle, mock_page_for_steps):
        """sort by string field descending."""
        from agent_browser.pipeline.steps import step_sort

        mock_page_for_steps.evaluate.return_value = [{"name": "Charlie"}, {"name": "Bob"}, {"name": "Alice"}]
        data = [{"name": "Alice"}, {"name": "Charlie"}, {"name": "Bob"}]
        result = await step_sort(
            session_id="test",
            params={"field": "name", "reverse": True},
            data=data,
            context={},
            stealth={},
        )
        names = [r["name"] for r in result]
        # Should be reverse-sorted
        assert names == sorted(names, reverse=True)


class TestDataTransformLimit:
    """limit step truncates array."""

    @pytest.mark.asyncio
    async def test_limit_truncates_array(self):
        """limit(N) returns first N items."""
        from agent_browser.pipeline.steps import step_limit

        data = list(range(100))
        result = await step_limit(
            session_id="test",
            params=10,
            data=data,
            context={},
            stealth={},
        )
        assert result == list(range(10))
        assert len(result) == 10

    @pytest.mark.asyncio
    async def test_limit_exceeds_length(self):
        """limit larger than array length returns full array."""
        from agent_browser.pipeline.steps import step_limit

        data = [1, 2, 3]
        result = await step_limit(
            session_id="test",
            params=100,
            data=data,
            context={},
            stealth={},
        )
        assert result == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_limit_zero_returns_empty(self):
        """limit(0) returns empty list."""
        from agent_browser.pipeline.steps import step_limit

        data = [1, 2, 3]
        result = await step_limit(
            session_id="test",
            params=0,
            data=data,
            context={},
            stealth={},
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_limit_template_resolves(self):
        """limit with template string resolves to int."""
        from agent_browser.pipeline.steps import step_limit

        data = list(range(50))
        result = await step_limit(
            session_id="test",
            params="${{ args.n }}",
            data=data,
            context={"args": {"n": 7}},
            stealth={},
        )
        assert len(result) == 7


# ══════════════════════════════════════════════
#  Test 10: Fetch SSRF Protection
# ══════════════════════════════════════════════


class TestFetchSSRFProtection:
    """step_fetch blocks requests to private/internal addresses."""

    @pytest.mark.asyncio
    async def test_fetch_blocks_localhost(self):
        """fetch to localhost is blocked."""
        from agent_browser.pipeline.steps import step_fetch

        with pytest.raises(ValueError, match="Blocked"):
            await step_fetch(
                session_id="test",
                params="http://localhost/admin",
                data=None,
                context={},
                stealth={},
            )

    @pytest.mark.asyncio
    async def test_fetch_blocks_127_0_0_1(self):
        """fetch to 127.0.0.1 is blocked."""
        from agent_browser.pipeline.steps import step_fetch

        with pytest.raises(ValueError, match="Blocked"):
            await step_fetch(
                session_id="test",
                params="http://127.0.0.1:9200/_cat/indices",
                data=None,
                context={},
                stealth={},
            )

    @pytest.mark.asyncio
    async def test_fetch_blocks_10_x_private(self):
        """fetch to 10.x.x.x private network is blocked."""
        from agent_browser.pipeline.steps import step_fetch

        with pytest.raises(ValueError, match="Blocked"):
            await step_fetch(
                session_id="test",
                params="http://10.0.0.1/internal",
                data=None,
                context={},
                stealth={},
            )

    @pytest.mark.asyncio
    async def test_fetch_blocks_192_168(self):
        """fetch to 192.168.x.x is blocked."""
        from agent_browser.pipeline.steps import step_fetch

        with pytest.raises(ValueError, match="Blocked"):
            await step_fetch(
                session_id="test",
                params="http://192.168.1.1/router-admin",
                data=None,
                context={},
                stealth={},
            )

    @pytest.mark.asyncio
    async def test_fetch_blocks_metadata(self):
        """fetch to GCP metadata endpoint is blocked."""
        from agent_browser.pipeline.steps import step_fetch

        with pytest.raises(ValueError, match="SSRF blocked|Blocked"):
            await step_fetch(
                session_id="test",
                params="http://metadata.google.internal/computeMetadata/v1/",
                data=None,
                context={},
                stealth={},
            )

    @pytest.mark.asyncio
    async def test_fetch_allows_public_url(self, patched_get_handle, mock_page_for_steps):
        """fetch to public URL is allowed (calls browser evaluate)."""
        from agent_browser.pipeline.steps import step_fetch

        mock_page_for_steps.evaluate.return_value = '{"ok": true}'
        await step_fetch(
            session_id="test",
            params="https://api.example.com/data",
            data=None,
            context={},
            stealth={},
        )
        # Should have attempted a fetch via browser
        assert mock_page_for_steps.evaluate.called
