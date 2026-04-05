"""Template 边界情况测试 — 错误输入和异常路径"""
import pytest
from skills.agent_browser.pipeline.template import (
    TemplateContext, resolve, render_template, render_value, apply_filter,
)


class TestTemplateErrorPaths:
    """模板渲染的异常路径不应崩溃"""

    def test_empty_template(self):
        assert render_template("", TemplateContext()) == ""

    def test_bare_variable_not_in_args(self):
        ctx = TemplateContext(args={"q": "test"})
        result = ctx.resolve("nonexistent_var")
        assert result is None

    def test_filter_unknown(self):
        result = apply_filter("hello", "nonexistent_filter")
        assert result == "hello"

    def test_deep_property_null(self):
        result = apply_filter(None, "first.name")
        assert result is None

    def test_empty_pipe_chain(self):
        ctx = TemplateContext(args={})
        result = ctx.resolve("")
        assert result is None or result == ""  # empty expression returns None

    def test_complex_expression_safe(self):
        """复杂但安全的表达式不应抛异常"""
        ctx = TemplateContext(args={"a": 1, "b": 2})
        result = ctx.resolve("a + b * 2")
        assert result == 5

    def test_arithmetic_with_data(self):
        """args 上下文中的算术表达式"""
        ctx = TemplateContext(args={"count": 10})
        result = ctx.resolve("count + 5")
        assert result == 15


class TestPipeFilters:
    """管道过滤器测试"""

    def test_default_none(self):
        assert apply_filter(None, "default(20)") == 20

    def test_default_empty_string(self):
        assert apply_filter("", "default(fallback)") == "fallback"

    def test_default_non_empty(self):
        assert apply_filter("hello", "default(fallback)") == "hello"

    def test_truncate(self):
        assert apply_filter("hello world", "truncate(5)") == "hello..."

    def test_upper_lower(self):
        assert apply_filter("Hello", "upper") == "HELLO"
        assert apply_filter("Hello", "lower") == "hello"

    def test_trim_strip(self):
        assert apply_filter("  hello  ", "trim") == "hello"
        assert apply_filter("  hello  ", "strip") == "hello"

    def test_length(self):
        assert apply_filter([1, 2, 3], "length") == 3
        assert apply_filter(None, "length") == 0

    def test_first_last(self):
        assert apply_filter([1, 2, 3], "first") == 1
        assert apply_filter([1, 2, 3], "last") == 3

    def test_join(self):
        assert apply_filter(["a", "b", "c"], "join(-)") == "a-b-c"

    def test_json_filter(self):
        import json
        result = apply_filter({"key": "value"}, "json")
        parsed = json.loads(result)
        assert parsed["key"] == "value"


class TestTemplateRendering:
    """模板渲染集成测试"""

    def test_simple_variable(self):
        ctx = TemplateContext(args={"keyword": "python"})
        result = render_template("search: ${{ keyword }}", ctx)
        assert result == "search: python"

    def test_multiple_variables(self):
        ctx = TemplateContext(args={"a": "hello", "b": "world"})
        result = render_template("${{ a }} ${{ b }}", ctx)
        assert result == "hello world"

    def test_pipe_in_template(self):
        ctx = TemplateContext(args={"name": "Alice Smith"})
        result = render_template("${{ name | upper }}", ctx)
        assert result == "ALICE SMITH"

    def test_default_in_template(self):
        ctx = TemplateContext(args={})
        result = render_template("${{ missing | default(42) }}", ctx)
        assert result == "42"

    def test_render_value_dict(self):
        ctx = TemplateContext(args={"q": "test"})
        result = render_value({"url": "https://x.com?q=${{ q }}"}, ctx)
        assert result["url"] == "https://x.com?q=test"

    def test_render_value_list(self):
        ctx = TemplateContext(args={"q": "test"})
        result = render_value(["${{ q }}", "static"], ctx)
        assert result == ["test", "static"]
