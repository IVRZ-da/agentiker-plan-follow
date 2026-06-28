"""Coverage tests for plan_follow/tools/plan_mgmt.py — push coverage to 90%."""


class TestRelativeDateParsing:
    def test_tomorrow(self):
        """Line 153: 'tomorrow' shortcut."""
        from plan_follow.tools.plan_mgmt import _parse_relative_date
        result = _parse_relative_date("tomorrow")
        assert result is not None
        assert len(result) == 10  # YYYY-MM-DD

    def test_plus_days(self):
        """Lines 157-160: +Nd pattern."""
        from plan_follow.tools.plan_mgmt import _parse_relative_date
        result = _parse_relative_date("+7d")
        assert result is not None
        assert len(result) == 10

    def test_plus_weeks(self):
        """Lines 161-162: +Nw pattern."""
        from plan_follow.tools.plan_mgmt import _parse_relative_date
        result = _parse_relative_date("+2w")
        assert result is not None
        assert len(result) == 10

    def test_invalid_returns_none(self):
        """Line 164: unparseable returns None."""
        from plan_follow.tools.plan_mgmt import _parse_relative_date
        assert _parse_relative_date("invalid") is None


class TestDeletePlan:
    def test_delete_missing_id(self):
        """Lines 335-339: plan_delete requires plan_id."""
        from plan_follow.plan_tools import plan_delete_tool
        result = plan_delete_tool({"plan_id": ""})
        assert "error" in result or "required" in result


class TestArchiveRestore:
    def test_archive_missing_id(self):
        """Lines 375-376: archive requires plan_id."""
        from plan_follow.plan_tools import plan_archive_tool
        result = plan_archive_tool({"plan_id": ""})
        assert "error" in result or "required" in result

    def test_restore_missing_id(self):
        """Lines 384-385: restore requires plan_id."""
        from plan_follow.plan_tools import plan_restore_tool
        result = plan_restore_tool({"plan_id": ""})
        assert "error" in result or "required" in result


class TestDueDateErrors:
    def test_duedate_nonexistent_task(self):
        """Lines 181-182: duedate for nonexistent task → error."""
        from plan_follow.tools.state import STATE
        STATE.active_plan = None
        STATE.active_plan_id = None
        from plan_follow.tools.task import create_plan
        create_plan("duedate-test", [{"id": "t_real", "name": "Real Task"}])
        from plan_follow.tools.plan_mgmt import set_task_due
        result = set_task_due("nonexistent", "2026-12-31")
        assert result.get("status") == "error"

    def test_invalid_date_format(self):
        """Line 191: invalid date → error."""
        from plan_follow.tools.task import create_plan
        create_plan("test", [{"id": "t1", "name": "T1"}])
        from plan_follow.tools.plan_mgmt import set_task_due
        result = set_task_due("t1", "not-a-date")
        assert "error" in result or "Invalid" in result["message"]
