"""Classifier 测试 — 错误分类逻辑"""

from stealth_browser.pipeline.classifier import (
    ErrorCategory,
    _extract_status_code,
    category_description,
    classify,
)
from stealth_browser.pipeline.errors import (
    PipelineStepError,
    SelectorNotFoundError,
    StepTimeoutError,
    URLError,
)


class TestStatusExtraction:
    def test_extract_401(self):
        assert _extract_status_code("got 401") == 401

    def test_extract_403(self):
        assert _extract_status_code("403 forbidden") == 403

    def test_extract_no_status(self):
        assert _extract_status_code("no status here") is None

    def test_extract_500(self):
        assert _extract_status_code("error 500 internal") == 500


class TestClassifyByType:
    """按异常类型分类（最精确的路径）"""

    def test_selector_not_found(self):
        err = SelectorNotFoundError(
            message="element .job-card not found",
            step_index=2,
            step_name="select",
            adapter_name="boss/search",
        )
        cat, meta = classify(err)
        assert cat == ErrorCategory.SELECTOR_DRIFT
        assert meta["hint"] == "element_not_found"

    def test_timeout_error(self):
        err = StepTimeoutError(
            message="timed out after 30s",
            step_index=1,
            step_name="wait",
            session_id="s1",
        )
        cat, meta = classify(err)
        assert cat == ErrorCategory.TIMEOUT
        assert meta["duration_hint"] == "increase_timeout"

    def test_url_error(self):
        err = URLError(
            message="connection refused to https://example.com",
            step_index=0,
            step_name="navigate",
        )
        cat, _meta = classify(err)
        assert cat == ErrorCategory.NAVIGATION_ERROR


class TestClassifyByMessage:
    """按消息内容启发式分类（PipelineStepError 路径）"""

    def test_auth_keywords(self):
        err = PipelineStepError(
            message="401 unauthorized - cookie expired",
            step_index=3,
            step_name="fetch",
        )
        cat, meta = classify(err)
        assert cat == ErrorCategory.AUTH_FAILURE
        assert meta["status_code"] == 401

    def test_forbidden_keyword(self):
        err = PipelineStepError(
            message="403 forbidden: need login",
            step_index=0,
            step_name="navigate",
        )
        cat, _ = classify(err)
        assert cat == ErrorCategory.AUTH_FAILURE

    def test_timeout_in_message(self):
        err = PipelineStepError(
            message="operation timed out waiting for element",
            step_index=4,
            step_name="click",
        )
        cat, _ = classify(err)
        assert cat == ErrorCategory.TIMEOUT

    def test_selector_in_message(self):
        err = PipelineStepError(
            message="selector #ref-5 not found in page",
            step_index=1,
            step_name="click",
        )
        cat, _ = classify(err)
        assert cat == ErrorCategory.SELECTOR_DRIFT

    def test_navigation_in_message(self):
        err = PipelineStepError(
            message="dns resolution failed for target.com",
            step_index=0,
            step_name="navigate",
        )
        cat, _ = classify(err)
        assert cat == ErrorCategory.NAVIGATION_ERROR

    def test_data_quality_in_message(self):
        err = PipelineStepError(
            message="key error 'title' on empty data",
            step_index=5,
            step_name="map",
        )
        cat, _ = classify(err)
        assert cat == ErrorCategory.DATA_QUALITY

    def test_unknown_falls_back(self):
        err = PipelineStepError(
            message="something completely unexpected",
            step_index=2,
            step_name="evaluate",
        )
        cat, _ = classify(err)
        assert cat == ErrorCategory.UNKNOWN


class TestCategoryDescription:
    def test_all_categories_have_description(self):
        for cat in ErrorCategory:
            desc = category_description(cat)
            assert desc  # no category should return empty string
            assert len(desc) > 5  # meaningful description


class TestClassifierIntegration:
    """分类器与错误层次的一致性"""

    def test_subclass_hierarchy_maps_to_category(self):
        """每个 PipelineError 子类都应映射到某个非-UNKNOWN 类别"""
        test_cases = [
            (SelectorNotFoundError, ErrorCategory.SELECTOR_DRIFT),
            (StepTimeoutError, ErrorCategory.TIMEOUT),
            (URLError, ErrorCategory.NAVIGATION_ERROR),
        ]
        for error_cls, expected_cat in test_cases:
            err = error_cls("test", step_index=0)
            cat, _ = classify(err)
            assert cat == expected_cat, f"{error_cls.__name__} -> {cat}"
