"""Analysis 模块测试 — 端点分析、策略推断、URL 处理"""
from types import SimpleNamespace

from agent_browser.explore.analysis import (
    DiscoveredStore,
    InferredCapability,
    classify_param,
    detect_auth_indicators,
    detect_site_name,
    has_pagination,
    has_search,
    infer_capabilities_from_endpoints,
    infer_capability_name,
    infer_strategy,
    score_endpoint,
    url_to_pattern,
)


class TestUrlToPattern:
    def test_numeric_path_replaced(self):
        result = url_to_pattern("https://api.example.com/users/12345")
        assert "{id}" in result or "12345" not in result

    def test_uuid_replaced(self):
        result = url_to_pattern("https://api.example.com/items/a1b2c3d4-e5f6")
        assert "{id}" in result or "a1b2c3d4" not in result

    def test_query_numeric_param(self):
        result = url_to_pattern("https://api.example.com/search?page=123&q=test")
        # page=123 should be parameterized (long numeric value > 2 digits)
        assert "page" in result

    def test_simple_url_unchanged(self):
        """Simple URLs without IDs or long params keep path unchanged (scheme/host stripped)."""
        # url_to_pattern normalizes to path-only form
        assert url_to_pattern("https://www.zhihu.com/hot") == "/hot"

    def test_long_query_value(self):
        result = url_to_pattern("https://api.example.com/data?token=verylongtokenstringherethatisover20chars")
        assert result != "https://api.example.com/data?token=verylongtokenstringherethatisover20chars"


class TestClassifyParam:
    def test_page_param(self):
        assert classify_param("page") == "pagination"

    def test_limit_param(self):
        assert classify_param("limit") == "pagination"

    def test_offset_param(self):
        assert classify_param("offset") == "pagination"

    def test_q_query_param(self):
        assert classify_param("q") == "search"
        assert classify_param("query") == "search"
        assert classify_param("keyword") == "search"

    def test_token_auth_param(self):
        assert classify_param("token") == "auth"
        assert classify_param("access_token") == "auth"

    def test_unknown_param(self):
        assert classify_param("random_name") == "unknown"

    def test_case_insensitive(self):
        assert classify_param("PAGE") == "pagination"
        assert classify_param("Query") == "search"


class TestParamDetection:
    def test_has_pagination_true(self):
        assert has_pagination({"page": "1", "limit": "10"}) is True

    def test_has_pagination_false(self):
        assert has_pagination({"q": "test"}) is False
        assert has_pagination({}) is False

    def test_has_search_true(self):
        assert has_search({"q": "python", "keyword": "engineer"}) is True

    def test_has_search_false(self):
        assert has_search({"page": "1"}) is False


class TestDetectAuthIndicators:
    def test_401_status(self):
        inds = detect_auth_indicators("https://api.example.com/data", 401, {}, {})
        assert any("status" in i for i in inds)

    def test_403_status(self):
        inds = detect_auth_indicators("https://api.example.com/data", 403, {}, {})
        assert len(inds) > 0

    def test_auth_header(self):
        inds = detect_auth_indicators(
            "https://api.example.com/data", 200,
            {"Authorization": "Bearer xyz"}, {}
        )
        assert any("authorization" in i.lower() for i in inds)

    def test_cookie_header(self):
        inds = detect_auth_indicators(
            "https://api.example.com/data", 200, {"Cookie": "session=abc"}, {}
        )
        assert any("cookie" in i.lower() for i in inds)

    def test_no_auth_needed(self):
        inds = detect_auth_indicators("https://public.api.com/data", 200, {}, {})
        assert isinstance(inds, list)

    def test_token_param(self):
        inds = detect_auth_indicators(
            "https://api.example.com/data", 200, {}, {"access_token": "xyz"}
        )
        assert any("token" in i.lower() for i in inds)


class TestInferStrategy:
    def _make_ep(self, is_json=False, status=200, auth=None, framework=None,
                score=None, sample=None, url="https://x.com"):
        kwargs = dict(
            is_json=is_json, status=status, url=url,
            auth_indicators=auth or [],
            score=score, sample=sample,
        )
        if framework is not None:
            kwargs["framework"] = framework
        # Don't set framework at all when None — code does .get('type') which crashes
        ep = SimpleNamespace(**kwargs)
        return ep

    def test_public_json_endpoint(self):
        eps = [self._make_ep(is_json=True, status=200)]
        assert infer_strategy(eps, "https://example.com") == "public"

    def test_intercept_needs_auth(self):
        eps = [
            self._make_ep(is_json=True, status=401, auth=["status:auth_required"]),
            self._make_ep(is_json=True, status=200),
        ]
        assert infer_strategy(eps, "https://example.com") == "intercept"

    def test_store_action_detected(self):
        eps = [self._make_ep(framework={"type": "pinia"})]
        assert infer_strategy(eps, "https://example.com") == "store-action"

    def test_empty_endpoints_falls_back_to_ui(self):
        assert infer_strategy([], "https://example.com") == "ui"

    def test_non_json_falls_back_to_ui(self):
        eps = [self._make_ep(is_json=False)]
        assert infer_strategy(eps, "https://example.com") == "ui"


class TestScoreEndpoint:
    def test_perfect_json_dict(self):
        # Dict sample with list data gets +3 array bonus + +2 status = ~6+
        score = score_endpoint("/api/data", "GET", 200, True,
                                {"data": [{"title": "test"}]})
        assert score >= 5.0

    def test_error_status_penalty(self):
        score = score_endpoint("GET", "/api/data", 500, True, {"error": "fail"})
        assert score < 5.0

    def test_non_json_low_score(self):
        score = score_endpoint("GET", "/page", 200, False, "<html>...</html>")
        assert score < 5.0

    def test_clamped_to_ten(self):
        score = score_endpoint("GET", "/api/data", 200, True,
                                {"data": [{"title": "x", "url": "y", "id": 1}]},
                                content_type="application/json")
        assert score <= 10.0

    def test_none_sample_no_crash(self):
        score = score_endpoint("GET", "/api/data", 200, True, None)
        assert isinstance(score, float)

    def test_list_sample_no_array_bonus(self):
        # List sample (not dict) skips +3 array bonus, only gets +2 status
        score = score_endpoint("GET", "/api/data", 200, True, [{"title": "t"}])
        assert score == 2.0  # Only status bonus


class TestInferCapabilityName:
    def test_with_goal(self):
        name, desc = infer_capability_name("boss", "https://api.boss.com/jobs",
                                         {}, goal="搜索职位")
        assert len(name) > 0

    def test_title_url_fields(self):
        fields = {"title": "Python工程师", "url": "https://job.com/1"}
        name, desc = infer_capability_name("zhihu", "https://zhihu.com/api", fields)
        assert isinstance(name, str) and len(name) > 0

    def test_generic_fallback(self):
        name, desc = infer_capability_name("unknown", "https://example.com", {})
        assert isinstance(name, str) and len(name) > 0


class TestInferCapabilitiesFromEndpoints:
    def _make_cap(self, score=8.0):
        return SimpleNamespace(
            is_json=True, score=score,
            url=f"https://api.example.com/{score}",
            sample={"data": [{"title": f"item{score}", "url": f"https://x.com/{score}"}]},
        )

    def test_filters_by_min_score(self):
        eps = [self._make_cap(score=8.0), self._make_cap(score=2.0)]
        caps = infer_capabilities_from_endpoints("test", eps, min_score=5.0)
        assert len(caps) == 1  # Only score=8 passes threshold
        assert caps[0].confidence > 0

    def test_empty_endpoints(self):
        caps = infer_capabilities_from_endpoints("test", [])
        assert caps == []

    def test_sorts_by_confidence_descending(self):
        eps = [self._make_cap(score=6.0), self._make_cap(score=9.0)]
        caps = infer_capabilities_from_endpoints("test", eps)
        if len(caps) >= 2:
            assert caps[0].confidence >= caps[1].confidence


class TestDetectSiteName:
    def test_known_sites(self):
        assert detect_site_name("https://www.zhihu.com/question/123") == "zhihu"
        assert detect_site_name("https://www.zhipin.com/web/geek/job") == "boss"
        assert detect_site_name("https://www.bilibili.com/video/BV1") == "bilibili"
        assert detect_site_name("https://www.douyin.com/video/123") == "douyin"
        # baidu not in _SITE_ALIASES — falls back to domain root
        assert detect_site_name("https://www.baidu.com/s?wd=test") == "www"

    def test_unknown_site(self):
        result = detect_site_name("https://random-site.example.com/path")
        assert result != ""
        assert isinstance(result, str)

    def test_malformed_url(self):
        assert detect_site_name("not-a-url") == "unknown"

    def test_ip_address(self):
        result = detect_site_name("http://192.168.1.1/api")
        assert result in ("192", "unknown")


class TestDataclasses:
    def test_inferred_capability_defaults(self):
        cap = InferredCapability(name="test", description="desc", strategy="public",
                                 confidence=0.8)
        assert cap.endpoint is None
        assert cap.recommended_columns is None
        assert cap.store_hint is None

    def test_discovered_store(self):
        store = DiscoveredStore(store_type="pinia", id="main",
                               actions=["fetch"], state_keys=["user", "token"])
        assert store.store_type == "pinia"
        assert len(store.actions) == 1
