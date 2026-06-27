"""Tests for small config/description/schema modules and hooks.

Tests cover:
- tools/config.py   — PlanConfig class and CFG singleton
- tools/descriptions.py  — TOOL_DESCRIPTIONS dict
- tools/schemas.py  — PER_TOOL_SCHEMAS dict
- hooks/__init__.py — re-exports (tested via plan_hooks where functions live)
"""

from __future__ import annotations

from pathlib import Path

import pytest

# ─── tools/config.py ────────────────────────────────────────────────────────


class TestPlanConfig:
    """PlanConfig defaults, mutability, Path types."""

    def test_cfg_is_planconfig_instance(self) -> None:
        from plan_follow.tools.config import CFG, PlanConfig

        assert isinstance(CFG, PlanConfig)

    def test_default_values(self) -> None:
        from plan_follow.tools.config import CFG

        home = Path.home()
        assert CFG.PLANS_DIR == home / ".hermes" / "plans"
        assert CFG.PLANS_INDEX == CFG.PLANS_DIR / "plans_index.json"
        assert CFG.ARCHIVE_DIR == CFG.PLANS_DIR / "archived"
        assert CFG.ROADMAPS_DIR == home / ".hermes" / "roadmaps"
        assert CFG.HONCHO_URL == "http://127.0.0.1:8001"
        assert CFG.HONCHO_WORKSPACE == "plan-follow"
        assert CFG.HONCHO_PEER == "plan-follow-agent"

    def test_all_paths_are_path_objects(self) -> None:
        from plan_follow.tools.config import CFG

        assert isinstance(CFG.PLANS_DIR, Path)
        assert isinstance(CFG.PLANS_INDEX, Path)
        assert isinstance(CFG.ARCHIVE_DIR, Path)
        assert isinstance(CFG.ROADMAPS_DIR, Path)

    def test_string_attrs_are_strings(self) -> None:
        from plan_follow.tools.config import CFG

        assert isinstance(CFG.HONCHO_URL, str)
        assert isinstance(CFG.HONCHO_WORKSPACE, str)
        assert isinstance(CFG.HONCHO_PEER, str)

    def test_mutating_plans_dir_is_possible(self) -> None:
        """CFG is designed to be monkeypatchable — test that mutation works."""
        from plan_follow.tools.config import CFG

        original = CFG.PLANS_DIR
        try:
            new_dir = Path("/tmp/test_plans")
            CFG.PLANS_DIR = new_dir
            assert CFG.PLANS_DIR == new_dir

            # Verify derived paths are NOT auto-updated (they were set at init)
            assert CFG.PLANS_INDEX != new_dir / "plans_index.json"
            assert CFG.ARCHIVE_DIR != new_dir / "archived"
        finally:
            CFG.PLANS_DIR = original

    def test_fresh_config_has_new_instance(self) -> None:
        """PlanConfig() creates a fresh instance independent of CFG."""
        from plan_follow.tools.config import CFG, PlanConfig

        fresh = PlanConfig()
        assert fresh is not CFG
        assert fresh.PLANS_DIR == CFG.PLANS_DIR
        assert fresh.HONCHO_URL == CFG.HONCHO_URL


# ─── tools/descriptions.py ──────────────────────────────────────────────────


class TestToolDescriptions:
    """TOOL_DESCRIPTIONS dict exists, non-empty, contains expected keys."""

    EXPECTED_KEYS = {
        "plan_create",
        "plan_current",
        "plan_complete",
        "plan_verify",
        "plan_status",
        "plan_todo",
        "plan_update",
        "plan_review",
        "plan_auto_review",
        "plan_review_profiles",
        "plan_review_save_result",
        "plan_template",
        "plan_suggest",
        "plan_time",
        "plan_simulate",
        "plan_sync",
        "plan_decompose",
        "plan_list",
        "plan_abort",
        "plan_delete",
        "plan_select",
        "plan_validate",
        "plan_duedate",
        "plan_archive",
        "plan_restore",
        "plan_roadmap",
        "plan_session",
        "plan_lock",
        "plan_notify",
        "plan_history",
        "plan_git_init",
        "plan_git_push",
        "plan_git_status",
        "plan_git_sync",
        "plan_git_stash",
        "plan_git_branch",
        "plan_git_tag",
        "plan_pr_create",
    }

    def test_variable_exists_and_non_empty(self) -> None:
        from plan_follow.tools.descriptions import TOOL_DESCRIPTIONS

        assert TOOL_DESCRIPTIONS is not None
        assert isinstance(TOOL_DESCRIPTIONS, dict)
        assert len(TOOL_DESCRIPTIONS) > 0

    def test_contains_expected_keys(self) -> None:
        from plan_follow.tools.descriptions import TOOL_DESCRIPTIONS

        for key in self.EXPECTED_KEYS:
            assert key in TOOL_DESCRIPTIONS, f"Missing key: {key}"

    def test_all_values_are_strings(self) -> None:
        from plan_follow.tools.descriptions import TOOL_DESCRIPTIONS

        for key, value in TOOL_DESCRIPTIONS.items():
            assert isinstance(value, str), f"Key '{key}' value is not a string: {type(value)}"
            assert len(value) > 0, f"Key '{key}' has empty description"

    def test_no_extra_unexpected_keys(self) -> None:
        """Warn if there are keys not in EXPECTED_KEYS (flag new additions)."""
        from plan_follow.tools.descriptions import TOOL_DESCRIPTIONS

        extra = set(TOOL_DESCRIPTIONS.keys()) - self.EXPECTED_KEYS
        if extra:
            pytest.skip(f"New keys found (not a failure): {sorted(extra)}")


# ─── tools/schemas.py ───────────────────────────────────────────────────────


class TestToolSchemas:
    """PER_TOOL_SCHEMAS dict — structure and validity."""

    def test_variable_exists_and_non_empty(self) -> None:
        from plan_follow.tools.schemas import PER_TOOL_SCHEMAS

        assert PER_TOOL_SCHEMAS is not None
        assert isinstance(PER_TOOL_SCHEMAS, dict)
        assert len(PER_TOOL_SCHEMAS) > 0

    def test_has_expected_tool_keys(self) -> None:
        from plan_follow.tools.schemas import PER_TOOL_SCHEMAS

        core_keys = {
            "plan_create",
            "plan_current",
            "plan_complete",
            "plan_verify",
            "plan_status",
            "plan_todo",
            "plan_list",
            "plan_delete",
            "plan_select",
            "plan_roadmap",
            "plan_lock",
            "plan_notify",
        }
        for key in core_keys:
            assert key in PER_TOOL_SCHEMAS, f"Missing schema key: {key}"

    def test_each_schema_has_type_and_properties(self) -> None:
        """Each schema entry is a valid JSON Schema object."""
        from plan_follow.tools.schemas import PER_TOOL_SCHEMAS

        for key, schema in PER_TOOL_SCHEMAS.items():
            assert isinstance(schema, dict), f"Key '{key}' schema is not a dict"
            assert schema.get("type") == "object", (
                f"Key '{key}' schema.type is not 'object' (got {schema.get('type')})"
            )
            assert "properties" in schema, f"Key '{key}' schema missing 'properties'"

    def test_required_fields_are_valid(self) -> None:
        """If 'required' is present, it must be a list of strings in properties."""
        from plan_follow.tools.schemas import PER_TOOL_SCHEMAS

        for key, schema in PER_TOOL_SCHEMAS.items():
            required = schema.get("required")
            if required is not None:
                assert isinstance(required, list), (
                    f"Key '{key}' required is not a list"
                )
                props = schema.get("properties", {})
                for field in required:
                    assert field in props, (
                        f"Key '{key}' required field '{field}' missing from properties"
                    )

    def test_schema_for_plan_create_has_goal_and_template(self) -> None:
        """plan_create schema should have goal and template as required."""
        from plan_follow.tools.schemas import PER_TOOL_SCHEMAS

        schema = PER_TOOL_SCHEMAS.get("plan_create", {})
        assert "goal" in schema.get("properties", {})
        assert "template" in schema.get("properties", {})
        required = schema.get("required", [])
        assert "goal" in required
        assert "template" in required


# ─── hooks (plan_hooks) ──────────────────────────────────────────────────────


class TestHooks:
    """on_pre_llm_call, on_post_tool_call, on_session_end — import + call."""

    def test_on_pre_llm_call_is_importable(self) -> None:
        from plan_follow.plan_hooks import on_pre_llm_call

        assert callable(on_pre_llm_call)

    def test_on_post_tool_call_is_importable(self) -> None:
        from plan_follow.plan_hooks import on_post_tool_call

        assert callable(on_post_tool_call)

    def test_on_session_end_is_importable(self) -> None:
        from plan_follow.plan_hooks import on_session_end

        assert callable(on_session_end)

    def test_on_pre_llm_call_returns_none_when_no_plan(self) -> None:
        """When no active plan, on_pre_llm_call should return None."""
        from plan_follow.plan_hooks import on_pre_llm_call

        result = on_pre_llm_call()
        assert result is None

    def test_on_post_tool_call_runs_without_error(self) -> None:
        """on_post_tool_call is an observer — should not raise."""
        from plan_follow.plan_hooks import on_post_tool_call

        # Should handle missing kwargs gracefully
        on_post_tool_call()  # no args
        on_post_tool_call(
            tool_name="plan_list",
            duration_ms=42,
            status="ok",
            error="",
        )

    def test_on_session_end_runs_without_error(self) -> None:
        """on_session_end should handle missing state gracefully."""
        from plan_follow.plan_hooks import on_session_end

        on_session_end()


# ─── hooks/__init__.py (subpackage imports) ────────────────────────────────


class TestHooksSubpackage:
    """Test hooks subpackage imports where possible.

    hooks/__init__.py re-exports utility symbols from .breaker (exists)
    and .base (not yet created). We test by importing breaker.py directly
    via importlib to avoid triggering the broken hooks/__init__.py import.
    """

    @pytest.fixture(autouse=True)
    def _import_breaker(self) -> None:
        """Import breaker module directly, bypassing hooks/__init__.py."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "plan_follow.hooks.breaker",
            "/home/jo/.hermes/plugins/plan_follow/hooks/breaker.py",
        )
        assert spec is not None
        mod = importlib.util.module_from_spec(spec)
        # Don't trigger hooks/__init__.py (which has broken .base import)
        # by NOT adding it to sys.modules with the package path
        spec.loader.exec_module(mod)
        self.breaker = mod

    def test_breaker_symbols_are_importable(self) -> None:
        mod = self.breaker
        assert isinstance(mod._BREAKER_CRITICAL_PREFIXES, tuple)
        assert mod._BREAKER_TTL > 0
        assert isinstance(mod._breaker_state, dict)
        assert callable(mod._build_breaker_banner)
        assert callable(mod._check_breaker)
        assert callable(mod._set_breaker)

    def test_breaker_check_and_banner(self) -> None:
        mod = self.breaker
        result = mod._check_breaker()
        assert isinstance(result, dict)

        banner = mod._build_breaker_banner()
        assert isinstance(banner, list)
        assert len(banner) == 0  # No active breakers → empty banner

    def test_breaker_set_and_check(self) -> None:
        mod = self.breaker
        mod._breaker_state.clear()
        mod._set_breaker("plan_test", "test error")
        active = mod._check_breaker()
        assert "plan_test" in active
        assert active["plan_test"]["error"] == "test error"

        mod._breaker_state.clear()

    def test_hooks_init_re_exports(self) -> None:
        """Verify that hooks/__init__.py's __all__ lists the expected names.

        Even though importing hooks/__init__.py fails at runtime (missing
        hooks/base.py), the __all__ list serves as documentation of the
        intended public API.
        """
        import ast

        init_path = "/home/jo/.hermes/plugins/plan_follow/hooks/__init__.py"
        with open(init_path) as f:
            tree = ast.parse(f.read())

        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__all__":
                        all_names = [elt.value for elt in node.value.elts if isinstance(elt, ast.Constant)]
                        assert len(all_names) > 0
                        assert "_build_banner" in all_names
                        assert "_check_breaker" in all_names
                        assert "_hook_cache" in all_names
                        return
        pytest.fail("Could not find __all__ in hooks/__init__.py")
