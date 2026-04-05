"""Cascade 测试 — DOM 级联探索与策略探测"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from skills.agent_browser.explore.cascade import (
    cascade,
    STRATEGY_LEVELS,
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
        with patch("skills.agent_browser.explore.cascade._get_handle") as mock_handle:
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
        with patch("skills.agent_browser.explore.cascade._get_handle") as mock_handle:
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

        with patch("skills.agent_browser.explore.cascade._get_handle") as mock_handle:
            mock_page = AsyncMock()
            mock_handle.return_value = mock_page

            # _try_public() does nested async with:
            #   async with aiohttp.ClientSession() as http:       # level 1
            #     async with http.get(url, timeout=...) as resp:   # level 2
            # Need to mock both levels of async context managers.
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value=[{"title": "test"}])

            mock_get_cm = AsyncMock()
            mock_get_cm.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_get_cm.__aexit__ = AsyncMock(return_value=False)

            mock_session = AsyncMock()
            mock_session.get = AsyncMock(return_value=mock_get_cm)

            mock_session_cm = AsyncMock()
            mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_cm.__aexit__ = AsyncMock(return_value=False)

            with patch("aiohttp.ClientSession", return_value=mock_session_cm):
                result = await cascade("s1", "https://example.com",
                                       endpoints=[ep])

        # Should short-circuit: only 1 result (public succeeded)
        assert len(result) == 1
        assert result[0]["strategy"] == "public"
        assert result[0]["success"] is True


class TestPrivateHelpers:
    """Test internal pure functions via indirect paths."""

    def test_extract_items_from_list(self):
        """List data passes through."""
        from skills.agent_browser.explore.cascade import _extract_items
        data = [{"title": "A"}, {"title": "B"}]
        result = _extract_items(data)
        assert result == data

    def test_extract_items_from_dict_with_data_key(self):
        """Dict with 'data' key unwraps it."""
        from skills.agent_browser.explore.cascade import _extract_items
        data = {"data": [{"x": 1}, {"y": 2}]}
        result = _extract_items(data)
        assert result == [{"x": 1}, {"y": 2}]

    def test_extract_items_none_input(self):
        from skills.agent_browser.explore.cascade import _extract_items
        result = _extract_items(None)
        assert result == []

    def test_infer_fields_maps_keys(self):
        from skills.agent_browser.explore.cascade import _infer_fields
        item = {"job_title": "Engineer", "salary": "100k"}
        fields = _infer_fields(item)
        assert isinstance(fields, dict)
        assert len(fields) > 0

    def test_infer_fields_empty_item(self):
        from skills.agent_browser.explore.cascade import _infer_fields
        fields = _infer_fields({})
        assert isinstance(fields, dict)

    def test_get_test_urls_filters_json(self):
        from skills.agent_browser.explore.cascade import _get_test_urls
        from types import SimpleNamespace
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
        from skills.agent_browser.explore.cascade import _get_test_urls
        assert _get_test_urls([], "https://example.com") == []
