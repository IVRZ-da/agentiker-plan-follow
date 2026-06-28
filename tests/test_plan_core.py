"""Coverage tests for plan_core.py — __getattr__/__setattr__ backward compat."""
import pytest


class TestPlanCoreGetattr:
    """Lines 155-198: __getattr__ lazy import resolution."""

    def test_submodule_attr_task(self):
        """plan_core.create_plan resolves to tools.task."""
        from plan_follow import plan_core
        assert callable(plan_core.create_plan)

    def test_submodule_attr_status(self):
        """plan_core.list_plans resolves to tools.status."""
        from plan_follow import plan_core
        assert callable(plan_core.list_plans)

    def test_submodule_attr_plan_mgmt(self):
        """plan_core.archive_plan resolves to tools.plan_mgmt."""
        from plan_follow import plan_core
        assert callable(plan_core.archive_plan)

    def test_submodule_attr_coordination(self):
        """plan_core._save_plan_state_to_honcho resolves to tools.coordination."""
        from plan_follow import plan_core
        assert callable(plan_core._save_plan_state_to_honcho)

    def test_submodule_attr_auto(self):
        """plan_core.auto_verify_task resolves to tools.auto."""
        from plan_follow import plan_core
        assert callable(plan_core.auto_verify_task)

    def test_submodule_attr_review(self):
        """plan_core.save_review_result resolves to tools.review."""
        from plan_follow import plan_core
        assert callable(plan_core.save_review_result)

    def test_submodule_attr_health(self):
        """plan_core.health_check resolves to tools.health."""
        from plan_follow import plan_core
        assert callable(plan_core.health_check)

    def test_submodule_attr_validation(self):
        """plan_core.validate_plan resolves to tools.validation."""
        from plan_follow import plan_core
        assert callable(plan_core.validate_plan)

    def test_submodule_attr_roadmap(self):
        """Line 174: plan_core._list_roadmaps resolves to tools.roadmap_data."""
        from plan_follow import plan_core
        assert callable(plan_core._list_roadmaps)

    def test_unknown_attr_raises(self):
        """Line 194: unknown attr → AttributeError."""
        from plan_follow import plan_core
        with pytest.raises(AttributeError):
            _ = plan_core.nonexistent_attr

    def test_honcho_defaults(self):
        """Line 197: HONCHO_URL default."""
        from plan_follow import plan_core
        assert plan_core.HONCHO_URL == "http://127.0.0.1:8001"


class TestPlanCoreSetattr:
    """Lines 201-212: __setattr__ proxy to STATE."""

    def test_set_active_plan(self):
        """Line 208: sets STATE.active_plan."""
        from plan_follow import plan_core
        from plan_follow.tools.state import STATE
        STATE.active_plan = None
        STATE.active_plan_id = None
        # Directly invoke __setattr__ (bypass potential __dict__ collision)
        plan_core.__setattr__("_active_plan", {"test": "value"})
        assert STATE.active_plan == {"test": "value"}

    def test_set_active_plan_id(self):
        """Line 210: sets STATE.active_plan_id."""
        from plan_follow import plan_core
        from plan_follow.tools.state import STATE
        STATE.active_plan = None
        STATE.active_plan_id = None
        plan_core.__setattr__("_active_plan_id", "test-id")
        assert STATE.active_plan_id == "test-id"

    def test_set_unknown_attr(self):
        """Line 212: monkeypatch-safe fallback."""
        from plan_follow import plan_core
        plan_core._some_unknown_attr = 42
        assert plan_core._some_unknown_attr == 42
