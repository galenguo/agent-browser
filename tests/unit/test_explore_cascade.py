"""Cascade 测试 — DOM 级联探索与策略探测"""

from unittest.mock import AsyncMock, patch

import pytest

from stealth_browser.explore.cascade import (
    STRATEGY_LEVELS,
    cascade,
)


class TestStrategyLevels:
    def test_has_all_known_strategies(self):
        assert "public" in STRATEGY_LEVELS
        assert "cookie" in STRATEGY_LEVELS
        assert "header" in STRATEGY_LEVELS
        assert "intercept" in STRATEGY_LEVELS
        assert "ui" in STRATEGY_LEVELS

    def test_ordering(self):
        """Strategies should be ordered from least to most privileged."""
        assert STRATEGY_LEVELS.index("public") < STRATEGY_LEVELS.index("cookie")
        assert STRATEGY_LEVELS.index("cookie") < STRATEGY_LEVELS.index("header")
        assert STRATEGY_LEVELS.index("header") < STRATEGY_LEVELS.index("intercept")


class TestCascadeIntegration:
    @pytest.mark.asyncio
    async def test_no_endpoints_returns_failure(self):
        """No endpoints to test → all strategies fail → returns results with success=False."""
        with patch("stealth_browser.explore.cascade._get_handle") as mock_handle:
            mock_page = AsyncMock()
            mock_handle.return_value = mock_page

            # Mock aiohttp for _try_public (even though no endpoints, it still gets imported)
            with patch("aiohttp.ClientSession", return_value=AsyncMock()):
                result = await cascade("s1", "https://example.com", endpoints=[])

        # Should return at least one result (even if all failed)
        assert isinstance(result, list)
        assert len(result) > 0
        if result:
            assert "strategy" in result[0]

    @pytest.mark.asyncio
    async def test_returns_list_of_dicts(self):
        """Result is always a list of dicts with expected keys."""
        with patch("stealth_browser.explore.cascade._get_handle") as mock_handle:
            mock_page = AsyncMock()
            mock_handle.return_value = mock_page

            with patch("aiohttp.ClientSession", return_value=AsyncMock()):
                result = await cascade("s1", "https://example.com")

        if result:
            for r in result:
                assert "strategy" in r
                assert "success" in r
                assert isinstance(r["success"], bool)

    @pytest.mark.asyncio
    async def test_public_success_short_circuits(self):
        """When public strategy succeeds, should not try cookie/header."""
        from types import SimpleNamespace

        ep = SimpleNamespace(is_json=True, url="https://api.example.com/data")

        with patch("stealth_browser.explore.cascade._get_handle") as mock_handle:
            mock_page = AsyncMock()
            mock_handle.return_value = mock_page

            # Patch _try_public directly to return success — avoids complex aiohttp mocking
            public_result = {
                "strategy": "public",
                "success": True,
                "endpoint": "https://api.example.com/data",
                "sample_size": 1,
                "fields": {"title": "title"},
                "notes": "",
            }
            with patch("stealth_browser.explore.cascade._try_public", return_value=public_result):
                result = await cascade("s1", "https://example.com", endpoints=[ep])

        # Should short-circuit: only 1 result (public succeeded)
        assert len(result) == 1
        assert result[0]["strategy"] == "public"
        assert result[0]["success"] is True


class TestPrivateHelpers:
    """Test internal pure functions via indirect paths."""

    def test_extract_items_from_list(self):
        """List data passes through."""
        from stealth_browser.explore.cascade import _extract_items

        data = [{"title": "A"}, {"title": "B"}]
        result = _extract_items(data)
        assert result == data

    def test_extract_items_from_dict_with_data_key(self):
        """Dict with 'data' key unwraps it."""
        from stealth_browser.explore.cascade import _extract_items

        data = {"data": [{"x": 1}, {"y": 2}]}
        result = _extract_items(data)
        assert result == [{"x": 1}, {"y": 2}]

    def test_extract_items_none_input(self):
        from stealth_browser.explore.cascade import _extract_items

        result = _extract_items(None)
        assert result == []

    def test_infer_fields_maps_keys(self):
        from stealth_browser.explore.cascade import _infer_fields

        item = {"job_title": "Engineer", "salary": "100k"}
        fields = _infer_fields(item)
        assert isinstance(fields, dict)
        assert len(fields) > 0

    def test_infer_fields_empty_item(self):
        from stealth_browser.explore.cascade import _infer_fields

        fields = _infer_fields({})
        assert isinstance(fields, dict)

    def test_get_test_urls_filters_json(self):
        from types import SimpleNamespace

        from stealth_browser.explore.cascade import _get_test_urls

        eps = [
            SimpleNamespace(is_json=True, url="https://api.example.com/a"),
            SimpleNamespace(is_json=False, url="https://example.com/page"),  # not JSON
            SimpleNamespace(is_json=True, url="https://api.example.com/b"),
            SimpleNamespace(is_json=True, url="https://api.example.com/c"),
            SimpleNamespace(is_json=True, url="https://api.example.com/d"),
            SimpleNamespace(is_json=True, url="https://api.example.com/e"),  # 6th - should be truncated
        ]
        urls = _get_test_urls(eps, "https://example.com")
        assert len(urls) <= 5  # max 5
        assert all(u.startswith("http") for u in urls)
        # All should be JSON endpoints
        assert all("/page" not in u for u in urls)

    def test_get_test_urls_empty(self):
        from stealth_browser.explore.cascade import _get_test_urls

        assert _get_test_urls([], "https://example.com") == []
