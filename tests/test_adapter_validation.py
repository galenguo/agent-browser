"""Adapter 回归测试 — 所有 YAML adapter 通过验证器 + 结构检查"""
import pytest
from skills.agent_browser.adapters.loader import get_adapter, list_adapters
from skills.agent_browser.adapters.validator import validate_adapter


class TestAllAdaptersLoad:
    """所有现有 adapter 都能被 loader 正确加载"""

    @pytest.mark.parametrize("site,name", [
        ("boss", "search"),
        ("baidu", "search"),
        ("bilibili", "hot"),
        ("zhihu", "hot"),
        # desktop adapters use a different format (app/type/detect), not site/name
    ])
    def test_adapter_loads(self, site, name):
        adapter = get_adapter(site, name)
        assert adapter is not None, f"Adapter {site}/{name} not found"
        assert "site" in adapter
        assert "name" in adapter
        assert "pipeline" in adapter
        assert len(adapter["pipeline"]) > 0


class TestAdapterValidation:
    """所有现有 adapter 通过结构验证"""

    @pytest.mark.parametrize("site,name", [
        ("boss", "search"),
        ("baidu", "search"),
        ("bilibili", "hot"),
        ("zhihu", "hot"),
    ])
    def test_adapter_validates(self, site, name):
        adapter = get_adapter(site, name)
        errors = validate_adapter(adapter)
        assert len(errors) == 0, f"{site}/{name} validation errors: {errors}"

    def test_web_adapters_have_navigate(self):
        """browser:true 的 adapter pipeline 应包含 navigate 步骤"""
        for site, name in [("boss", "search"), ("baidu", "search")]:
            adapter = get_adapter(site, name)
            if adapter and adapter.get("browser") is not False:
                ops = [list(s.keys())[0] for s in adapter["pipeline"]]
                assert "navigate" in ops, f"{site}/{name} missing navigate step"


class TestPipelineErrors:
    """PipelineError 层次和序列化"""

    def test_pipeline_error_to_dict(self):
        from skills.agent_browser.pipeline.errors import PipelineError
        err = PipelineError(
            message="test error",
            step_index=2,
            step_name="click",
            adapter_name="boss/search",
            fix_hint="Check selector",
        )
        d = err.to_dict()
        assert d["step"] == 2
        assert d["step_name"] == "click"
        assert d["adapter"] == "boss/search"
        assert d["fix_hint"] == "Check selector"

    def test_user_message_format(self):
        from skills.agent_browser.pipeline.errors import PipelineError
        err = PipelineError(
            message="element not found",
            step_index=3,
            step_name="select",
            adapter_name="test/test",
            fix_hint="Re-run explore",
        )
        msg = err.user_message
        assert "step 3" in msg
        assert "'select'" in msg
        assert "Re-run explore" in msg
        assert "element not found" in msg

    def test_subclass_hierarchy(self):
        from skills.agent_browser.pipeline.errors import (
            PipelineError, PipelineStepError, SelectorNotFoundError,
        )
        assert issubclass(SelectorNotFoundError, PipelineStepError)
        assert issubclass(PipelineStepError, PipelineError)

    def test_fix_hint_generation(self):
        from skills.agent_browser.pipeline.errors import _generate_fix_hint
        hint = _generate_fix_hint("select", "element not found")
        assert hint  # should always return something
        hint = _generate_fix_hint("unknown_step", "something broke")
        assert hint  # fallback should also return something


class TestValidatorEdgeCases:
    """验证器对故意损坏的 YAML 的检测"""

    def test_empty_dict(self):
        assert len(validate_adapter({})) > 0

    def test_empty_pipeline(self):
        assert len(validate_adapter({"site": "x", "name": "y", "pipeline": []})) > 0

    def test_bad_strategy(self):
        errs = validate_adapter({
            "site": "x", "name": "y",
            "strategy": "bad_strategy",
            "pipeline": [{"navigate": "u"}],
        })
        assert any("Invalid strategy" in e for e in errs)

    def test_bad_arg_type(self):
        errs = validate_adapter({
            "site": "x", "name": "y",
            "args": {"q": {"type": "object"}},
            "pipeline": [{"navigate": "u"}],
        })
        assert any("invalid type" in e for e in errs)

    def test_browser_false_with_navigate(self):
        errs = validate_adapter({
            "site": "x", "name": "y",
            "browser": False,
            "pipeline": [{"navigate": "u"}, {"evaluate": "1"}],
        })
        assert any("contradiction" in e for e in errs)

    def test_unknown_step_in_pipeline(self):
        errs = validate_adapter({
            "site": "x", "name": "y",
            "pipeline": [{"nonexistent_step": "params"}],
        })
        assert any("unknown step" in e for e in errs)

    def test_valid_adapter_passes(self):
        errs = validate_adapter({
            "site": "test", "name": "test",
            "strategy": "cookie",
            "pipeline": [{"navigate": "https://example.com"}],
        })
        assert len(errs) == 0
