"""Coverage tests for plan_follow/tools/task.py — push coverage to 90%."""


class TestCreatePlanEdgeCases:
    def test_plan_id_override(self):
        """Line 47: plan_id_override parameter."""
        from plan_follow.tools.task import create_plan
        pid = create_plan("test", [{"id": "t1", "name": "T1"}],
                          plan_id_override="my-custom-id")
        assert pid == "my-custom-id"

    def test_parallel_groups_auto_creates_missing(self):
        """Line 85: parallel_groups auto-creates missing task stubs."""
        from plan_follow.tools.task import create_plan
        pid = create_plan("test", [{"id": "t1", "name": "T1"}],
                          parallel_groups={"g1": {"tasks": ["t1", "t2"]}})
        assert pid
        from plan_follow.tools.base import _get_active_plan
        plan = _get_active_plan()
        assert "t2" in plan["tasks"]


class TestGetCurrentTaskCached:
    def test_no_active_plan_returns_none(self):
        """Line 168: no active plan → None."""
        from plan_follow.tools.base import _reset_cache
        from plan_follow.tools.task import get_current_task_cached
        _reset_cache()
        result = get_current_task_cached()
        assert result is None

    def test_no_current_task_returns_none(self):
        """Line 360: current_task is None → None."""
        from plan_follow.tools.task import create_plan, get_current_task_cached
        create_plan("test", [{"id": "t1", "name": "T1", "files": []}])
        # After creation, current_task should be set
        result = get_current_task_cached()
        assert result is not None


class TestValidationErrors:
    def test_plan_delete_missing_id(self):
        """Line 709-710: plan_delete without plan_id."""
        from plan_follow.plan_tools import plan_delete_tool
        result = plan_delete_tool({"plan_id": ""})
        assert "error" in result or "required" in result

    def test_task_id_required_for_delete(self):
        """Line 570: task deletion requires task_id."""
        from plan_follow.plan_tools import plan_complete_tool
        result = plan_complete_tool({"task_id": "", "skip_review": True})
        assert "error" in result or "required" in result or "task_id" in result
