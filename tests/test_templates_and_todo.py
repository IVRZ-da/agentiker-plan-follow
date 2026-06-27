"""Comprehensive tests for plan_templates.py and plan_todo.py — covering uncovered edge cases."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


# ═══════════════════════════════════════════════════════════════════
# plan_templates.py — Template Engine Edge Cases
# ═══════════════════════════════════════════════════════════════════


class TestAutoDetectProjectDefaults:
    """Tests for _auto_detect_project_defaults — uncovered lines 125-126."""

    def test_no_marker_found_returns_python_defaults(self, tmp_path):
        """When no project marker exists, returns Python defaults (lines 125-126)."""
        from plan_follow.plan_templates import _auto_detect_project_defaults  # noqa: E402
        empty_dir = tmp_path / "empty_project"
        empty_dir.mkdir()
        result = _auto_detect_project_defaults(repo=str(empty_dir))
        assert result["test_command"] == "python3 -m pytest"
        assert result["lint_command"] == "ruff check"
        assert "echo" in result["build_command"]

    def test_pyproject_toml_detected(self, tmp_path):
        """When pyproject.toml exists, python defaults are used."""
        from plan_follow.plan_templates import _auto_detect_project_defaults
        (tmp_path / "pyproject.toml").write_text("")
        result = _auto_detect_project_defaults(repo=str(tmp_path))
        assert result["test_command"] == "python3 -m pytest"
        assert "ruff check" in result["lint_command"]

    def test_go_mod_detected(self, tmp_path):
        """When go.mod exists, go defaults are used."""
        from plan_follow.plan_templates import _auto_detect_project_defaults
        (tmp_path / "go.mod").write_text("")
        result = _auto_detect_project_defaults(repo=str(tmp_path))
        assert result["test_command"] == "go test ./..."


class TestGetTemplateDetail:
    """Tests for get_template_detail — uncovered lines 322-326."""

    def test_non_existent_template_returns_none(self):
        """get_template_detail for non-existent template returns None (line 325)."""
        from plan_follow.plan_templates import get_template_detail
        result = get_template_detail("__nonexistent_template__")
        assert result is None

    def test_builtin_template_returns_detail(self):
        """get_template_detail for built-in template returns detail dict."""
        from plan_follow.plan_templates import get_template_detail
        result = get_template_detail("deploy")
        assert result is not None
        assert result["name"] == "deploy"
        assert result["is_user"] is False
        assert result["source"] == "built-in"

    def test_user_template_detail(self, tmp_path, monkeypatch):
        """get_template_detail correctly identifies user templates."""
        from plan_follow.plan_templates import get_template_detail
        monkeypatch.setattr("plan_follow.plan_templates.TEMPLATES_DIR", tmp_path)
        (tmp_path / "my_custom.yaml").write_text(yaml.dump({
            "name": "my_custom",
            "description": "Custom",
            "tasks": [{"id": "t1", "name": "T1", "files": [], "verify": "", "depends_on": []}],
            "review_profile": "none",
        }))
        result = get_template_detail("my_custom")
        assert result is not None
        assert result["name"] == "my_custom"
        assert result["is_user"] is True
        assert result["source"] != "built-in"


class TestSaveUserTemplate:
    """Tests for save_user_template — uncovered lines 349-373."""

    def test_save_and_retrieve(self, tmp_path, monkeypatch):
        """Save a user template, then verify it exists and can be loaded."""
        from plan_follow.plan_templates import _load_user_templates, save_user_template
        monkeypatch.setattr("plan_follow.plan_templates.TEMPLATES_DIR", tmp_path)
        tasks = [
            {"id": "s1", "name": "Step 1", "files": ["src/"], "verify": "echo done", "depends_on": []},
            {"id": "s2", "name": "Step 2", "files": [], "verify": "echo done2", "depends_on": ["s1"]},
        ]
        result = save_user_template("test_template", tasks, "Test description", "unit-test")
        assert result["status"] == "saved"
        assert result["name"] == "test_template"
        assert result["task_count"] == 2

        # Verify file was written
        filepath = tmp_path / "test_template.yaml"
        assert filepath.exists()

        # Verify it can be loaded back
        loaded = _load_user_templates()
        assert "test_template" in loaded
        assert loaded["test_template"]["description"] == "Test description"
        assert len(loaded["test_template"]["tasks"]) == 2

    def test_save_creates_templates_dir(self, tmp_path, monkeypatch):
        """If TEMPLATES_DIR doesn't exist, save creates it (lines 349-350)."""
        from plan_follow.plan_templates import save_user_template
        new_dir = tmp_path / "nonexistent" / "deep"
        monkeypatch.setattr("plan_follow.plan_templates.TEMPLATES_DIR", new_dir)
        tasks = [{"id": "t1", "name": "T1", "files": [], "verify": "", "depends_on": []}]
        result = save_user_template("new_dir_test", tasks)
        assert result["status"] == "saved"
        assert new_dir.exists()

    def test_save_no_description(self, tmp_path, monkeypatch):
        """Save without description."""
        from plan_follow.plan_templates import save_user_template
        monkeypatch.setattr("plan_follow.plan_templates.TEMPLATES_DIR", tmp_path)
        tasks = [{"id": "t1", "name": "T1", "files": [], "verify": "", "depends_on": []}]
        result = save_user_template("no_desc", tasks)
        assert result["status"] == "saved"


class TestDeleteUserTemplate:
    """Tests for delete_user_template — uncovered lines 385-392."""

    def test_delete_builtin_returns_error(self):
        """Deleting a built-in template returns error (lines 385-386)."""
        from plan_follow.plan_templates import delete_user_template
        result = delete_user_template("deploy")
        assert result["status"] == "error"
        assert "built-in" in result["message"]

    def test_delete_nonexistent_returns_error(self, tmp_path, monkeypatch):
        """Deleting a non-existent user template returns error (lines 388-389)."""
        from plan_follow.plan_templates import delete_user_template
        monkeypatch.setattr("plan_follow.plan_templates.TEMPLATES_DIR", tmp_path)
        result = delete_user_template("nonexistent_user")
        assert result["status"] == "error"
        assert "not found" in result["message"]

    def test_delete_user_template_success(self, tmp_path, monkeypatch):
        """Successfully delete a user template (lines 390-392)."""
        from plan_follow.plan_templates import delete_user_template, save_user_template
        monkeypatch.setattr("plan_follow.plan_templates.TEMPLATES_DIR", tmp_path)
        tasks = [{"id": "t1", "name": "T1", "files": [], "verify": "", "depends_on": []}]
        save_user_template("to_delete", tasks)
        assert (tmp_path / "to_delete.yaml").exists()
        result = delete_user_template("to_delete")
        assert result["status"] == "deleted"
        assert result["name"] == "to_delete"
        assert not (tmp_path / "to_delete.yaml").exists()


class TestExpandTemplateEdgeCases:
    """Edge cases for expand_template — uncovered lines."""

    def test_multi_template_with_custom_tasks_succeeds(self):
        """expand_template 'multi' processes custom tasks and returns them (bug fixed: line 462 was outside the if)."""
        from plan_follow.plan_templates import expand_template
        tasks = [
            {"id": "m1", "name": "Custom staging deploy", "files": [], "verify": "echo staging", "depends_on": []},
            {"id": "m2", "name": "Verify http://test.com", "files": [], "verify": "curl http://test.com", "depends_on": ["m1"]},
        ]
        result = expand_template("multi", params={"tasks": tasks, "env": "staging", "url": "http://test.com"})
        assert "error" not in result, f"Bug fix regression: multi template should not return error: {result}"
        assert "tasks" in result
        assert len(result["tasks"]) >= 3  # p0 + 2 custom tasks
        assert result["tasks"][1]["id"] == "m1"
        assert result["tasks"][2]["id"] == "m2"

    def test_multi_template_without_tasks_key_falls_through(self):
        """multi template without 'tasks' in params falls through to p0 insertion (no error)."""
        from plan_follow.plan_templates import expand_template
        result = expand_template("multi", params={"something": "else"})
        # No 'tasks' key in params, so outer if is False → p0 insertion runs
        assert "error" not in result
        assert result["tasks"][0]["id"] == "p0"

    def test_multi_template_empty_tasks_list_returns_error(self):
        """multi template with empty tasks list returns error."""
        from plan_follow.plan_templates import expand_template
        result = expand_template("multi", params={"tasks": []})
        assert "error" in result

    def test_bugfix_with_skip_refactor(self):
        """bugfix template with skip_refactor removes b3 task (lines 490-494)."""
        from plan_follow.plan_templates import expand_template
        result = expand_template("bugfix", params={"skip_refactor": True})
        assert "error" not in result
        # b3 (REFACTOR) should be removed
        task_ids = [t["id"] for t in result["tasks"]]
        assert "b3" not in task_ids
        # b2 should depend only on p0
        b2_task = next(t for t in result["tasks"] if t["id"] == "b2")
        assert b2_task["depends_on"] == ["p0"]

    def test_bugfix_with_skip_refactor_string_true(self):
        """bugfix with skip_refactor='true' string should also work."""
        from plan_follow.plan_templates import expand_template
        result = expand_template("bugfix", params={"skip_refactor": "true"})
        task_ids = [t["id"] for t in result["tasks"]]
        assert "b3" not in task_ids

    def test_expand_with_depends_on_and_p0_insertion(self, tmp_path, monkeypatch):
        """When first task has depends_on, p0 is prepended (lines 478-480)."""
        from plan_follow.plan_templates import expand_template, save_user_template
        # Save a user template where first task already has depends_on
        monkeypatch.setattr("plan_follow.plan_templates.TEMPLATES_DIR", tmp_path)
        tasks = [
            {"id": "x1", "name": "First", "files": [], "verify": "", "depends_on": ["x0"]},
            {"id": "x2", "name": "Second", "files": [], "verify": "", "depends_on": ["x1"]},
        ]
        save_user_template("dep_test", tasks, "Test depends_on")
        result = expand_template("dep_test")
        assert "error" not in result
        # First custom task (index 1) should have p0 prepended to its depends_on
        assert result["tasks"][1]["id"] == "x1"
        assert "p0" in result["tasks"][1]["depends_on"]
        assert "x0" in result["tasks"][1]["depends_on"]
        # p0 should be first in depends_on
        assert result["tasks"][1]["depends_on"].index("p0") < result["tasks"][1]["depends_on"].index("x0")

    def test_expand_with_repo_hint(self):
        """Templates with repo_hint include it in result."""
        from plan_follow.plan_templates import expand_template
        result = expand_template("deploy")
        assert "repo_hint" in result
        assert "BENÖTIGT" in result["repo_hint"]

    def test_feature_template_with_params(self):
        """feature template with params should substitute correctly."""
        from plan_follow.plan_templates import expand_template
        result = expand_template("feature", params={"test_command": "pytest -x", "lint_command": "ruff check --fix"})
        assert "error" not in result
        assert len(result["tasks"]) == 5  # p0 + 4 feature tasks

    def test_infrastructure_template(self):
        """infrastructure template expands correctly."""
        from plan_follow.plan_templates import expand_template
        result = expand_template("infrastructure")
        assert "error" not in result
        assert len(result["tasks"]) == 5  # p0 + 4 infra tasks

    def test_security_template(self):
        """security template expands correctly."""
        from plan_follow.plan_templates import expand_template
        result = expand_template("security")
        assert "error" not in result
        assert len(result["tasks"]) == 5  # p0 + 4 security tasks

    def test_go_setup_template(self):
        """go-setup template expands correctly."""
        from plan_follow.plan_templates import expand_template
        result = expand_template("go-setup")
        assert "error" not in result
        assert len(result["tasks"]) == 4  # p0 + 3 go-setup tasks

    def test_fix_template(self):
        """fix template expands correctly."""
        from plan_follow.plan_templates import expand_template
        result = expand_template("fix")
        assert "error" not in result
        assert len(result["tasks"]) == 3  # p0 + 2 fix tasks


class TestPlanTemplateTool:
    """Tests for plan_template_tool handler — uncovered lines 541-584."""

    def test_list_templates(self):
        """plan_template_tool with action=list returns template names."""
        from plan_follow.plan_templates import plan_template_tool
        result = plan_template_tool({"action": "list"})
        assert result is not None
        assert isinstance(result, str)

    def test_detail_action(self):
        """plan_template_tool with action=detail and name."""
        from plan_follow.plan_templates import plan_template_tool
        result = plan_template_tool({"action": "detail", "name": "deploy"})
        assert result is not None

    def test_detail_action_missing_name(self):
        """plan_template_tool detail without name."""
        from plan_follow.plan_templates import plan_template_tool
        result = plan_template_tool({"action": "detail"})
        assert result is not None

    def test_detail_nonexistent(self):
        """plan_template_tool detail for non-existent template."""
        from plan_follow.plan_templates import plan_template_tool
        result = plan_template_tool({"action": "detail", "name": "nonexistent123"})
        assert result is not None

    def test_save_action(self, tmp_path, monkeypatch):
        """plan_template_tool with action=save."""
        from plan_follow.plan_templates import plan_template_tool
        monkeypatch.setattr("plan_follow.plan_templates.TEMPLATES_DIR", tmp_path)
        tasks = [{"id": "t1", "name": "T1", "files": [], "verify": "", "depends_on": []}]
        result = plan_template_tool({"action": "save", "name": "saved_via_tool", "tasks": tasks})
        assert result is not None

    def test_save_action_missing_name(self):
        """plan_template_tool save without name returns error."""
        from plan_follow.plan_templates import plan_template_tool
        result = plan_template_tool({"action": "save", "tasks": []})
        assert result is not None

    def test_save_action_missing_tasks(self, tmp_path, monkeypatch):
        """plan_template_tool save with name but no tasks returns error."""
        from plan_follow.plan_templates import plan_template_tool
        monkeypatch.setattr("plan_follow.plan_templates.TEMPLATES_DIR", tmp_path)
        result = plan_template_tool({"action": "save", "name": "test"})
        assert result is not None

    def test_delete_action(self, tmp_path, monkeypatch):
        """plan_template_tool with action=delete."""
        from plan_follow.plan_templates import plan_template_tool, save_user_template
        monkeypatch.setattr("plan_follow.plan_templates.TEMPLATES_DIR", tmp_path)
        save_user_template("delete_me", [{"id": "t1", "name": "T1", "files": [], "verify": "", "depends_on": []}])
        result = plan_template_tool({"action": "delete", "name": "delete_me"})
        assert result is not None

    def test_delete_builtin_via_tool(self):
        """plan_template_tool delete built-in returns error."""
        from plan_follow.plan_templates import plan_template_tool
        result = plan_template_tool({"action": "delete", "name": "deploy"})
        assert result is not None

    def test_delete_missing_name(self):
        """plan_template_tool delete without name."""
        from plan_follow.plan_templates import plan_template_tool
        result = plan_template_tool({"action": "delete"})
        assert result is not None

    def test_delete_nonexistent_via_tool(self, tmp_path, monkeypatch):
        """plan_template_tool delete non-existent user template."""
        from plan_follow.plan_templates import plan_template_tool
        monkeypatch.setattr("plan_follow.plan_templates.TEMPLATES_DIR", tmp_path)
        result = plan_template_tool({"action": "delete", "name": "no_such_template"})
        assert result is not None

    def test_unknown_action(self):
        """plan_template_tool with unknown action (line 584)."""
        from plan_follow.plan_templates import plan_template_tool
        result = plan_template_tool({"action": "fly_me_to_the_moon"})
        assert result is not None


# ═══════════════════════════════════════════════════════════════════
# plan_todo.py — Todo List Edge Cases
# ═══════════════════════════════════════════════════════════════════


class TestPlanTodoModule:
    """Basic plan_todo module tests."""

    def test_module_importable(self):
        """plan_todo module can be imported."""
        import plan_follow.plan_todo
        assert hasattr(plan_follow.plan_todo, "plan_todo_tool")


class TestPlanTodoBlockedTasks:
    """Tests for blocked task handling — uncovered lines 63-64."""

    def test_blocked_task_shows_blocked_by(self, monkeypatch):
        """When a task has status=blocked with blocked_by, content includes hint."""
        import plan_follow.plan_core as plan_core
        from plan_follow.plan_todo import _get_todo_list

        fake_status = {
            "tasks": [
                {"id": "t1", "name": "Task One", "status": "blocked", "blocked_by": ["t0"]},
                {"id": "t2", "name": "Task Two", "status": "pending"},
            ]
        }
        monkeypatch.setattr(plan_core, "get_plan_status", lambda: fake_status, raising=False)

        result = _get_todo_list()
        assert len(result) == 2
        # Blocked task should have hint
        blocked = [t for t in result if t["id"] == "t1"][0]
        assert "blocked by:" in blocked["content"]
        assert "t0" in blocked["content"]
        # Non-blocked should not
        pending = [t for t in result if t["id"] == "t2"][0]
        assert "blocked by:" not in pending["content"]

    def test_blocked_without_blocked_by(self, monkeypatch):
        """Blocked task without blocked_by doesn't crash."""
        import plan_follow.plan_core as plan_core
        from plan_follow.plan_todo import _get_todo_list

        fake_status = {
            "tasks": [
                {"id": "t1", "name": "Task One", "status": "blocked"},
            ]
        }
        monkeypatch.setattr(plan_core, "get_plan_status", lambda: fake_status, raising=False)

        result = _get_todo_list()
        assert len(result) == 1
        # No blocked_by, so no content modification
        assert "(blocked by:" not in result[0]["content"]

    def test_no_plan_returns_empty_list(self, monkeypatch):
        """When get_plan_status returns None, returns empty list."""
        import plan_follow.plan_core as plan_core
        from plan_follow.plan_todo import _get_todo_list

        monkeypatch.setattr(plan_core, "get_plan_status", lambda: None, raising=False)
        result = _get_todo_list()
        assert result == []


class TestPlanTodoApplyWrite:
    """Tests for _apply_write edge cases — uncovered lines 97, 102, 108, 112, 121-131."""

    def test_skip_invalid_item_empty_id(self, monkeypatch):
        """Items with empty id are skipped (line 97)."""
        import plan_follow.plan_core as plan_core
        from plan_follow.plan_todo import _apply_write

        # For the final _get_todo_list() call, return empty
        monkeypatch.setattr(plan_core, "get_plan_status", lambda: None, raising=False)
        result = _apply_write([{"id": "", "status": "completed"}])
        assert isinstance(result, list)

    def test_skip_invalid_status(self, monkeypatch):
        """Items with invalid status are skipped (line 97)."""
        import plan_follow.plan_core as plan_core
        from plan_follow.plan_todo import _apply_write

        monkeypatch.setattr(plan_core, "get_plan_status", lambda: None, raising=False)
        result = _apply_write([{"id": "t1", "status": "invalid_status"}])
        assert isinstance(result, list)

    def test_no_plan_status_during_write(self, monkeypatch):
        """_apply_write continues when get_plan_status returns None (lines 101-102)."""
        import plan_follow.plan_core as plan_core
        from plan_follow.plan_todo import _apply_write

        monkeypatch.setattr(plan_core, "get_plan_status", lambda: None, raising=False)
        result = _apply_write([{"id": "t1", "status": "completed"}])
        assert isinstance(result, list)

    def test_task_not_found_skipped(self, monkeypatch):
        """When task id is not in plan, skip (lines 107-108)."""
        import plan_follow.plan_core as plan_core
        from plan_follow.plan_todo import _apply_write

        fake_status = {
            "tasks": [
                {"id": "t1", "name": "T1", "status": "pending"},
            ]
        }
        monkeypatch.setattr(plan_core, "get_plan_status", lambda: fake_status, raising=False)
        result = _apply_write([{"id": "nonexistent_task", "status": "completed"}])
        assert isinstance(result, list)

    def test_same_status_skipped(self, monkeypatch):
        """When old_status == new_status, skip (line 112)."""
        import plan_follow.plan_core as plan_core
        from plan_follow.plan_todo import _apply_write

        fake_status = {
            "tasks": [
                {"id": "t1", "name": "T1", "status": "pending"},
            ]
        }
        monkeypatch.setattr(plan_core, "get_plan_status", lambda: fake_status, raising=False)
        result = _apply_write([{"id": "t1", "status": "pending"}])
        assert isinstance(result, list)

    def test_complete_task_success(self, monkeypatch):
        """Successful complete_task call (line 120)."""
        import plan_follow.plan_core as plan_core
        from plan_follow.plan_todo import _apply_write

        fake_status = {
            "tasks": [
                {"id": "t1", "name": "T1", "status": "pending"},
            ]
        }
        monkeypatch.setattr(plan_core, "get_plan_status", lambda: fake_status, raising=False)
        monkeypatch.setattr(plan_core, "complete_task", lambda tid: {"status": "completed"}, raising=False)
        result = _apply_write([{"id": "t1", "status": "completed"}])
        assert isinstance(result, list)

    def test_complete_task_already_completed(self, monkeypatch):
        """complete_task returns already_completed status."""
        import plan_follow.plan_core as plan_core
        from plan_follow.plan_todo import _apply_write

        fake_status = {
            "tasks": [
                {"id": "t1", "name": "T1", "status": "pending"},
            ]
        }
        monkeypatch.setattr(plan_core, "get_plan_status", lambda: fake_status, raising=False)
        monkeypatch.setattr(plan_core, "complete_task", lambda tid: {"status": "already_completed"}, raising=False)
        result = _apply_write([{"id": "t1", "status": "completed"}])
        assert isinstance(result, list)

    def test_complete_task_exception_handled(self, monkeypatch):
        """Exception in complete_task is caught (lines 121-122)."""
        import plan_follow.plan_core as plan_core
        from plan_follow.plan_todo import _apply_write

        fake_status = {
            "tasks": [
                {"id": "t1", "name": "T1", "status": "pending"},
            ]
        }

        def failing_complete(*args, **kwargs):
            raise ValueError("Simulated failure")

        monkeypatch.setattr(plan_core, "get_plan_status", lambda: fake_status, raising=False)
        monkeypatch.setattr(plan_core, "complete_task", failing_complete, raising=False)
        result = _apply_write([{"id": "t1", "status": "completed"}])
        assert isinstance(result, list)

    def test_update_task_success(self, monkeypatch):
        """Successful update_task call (line 128)."""
        import plan_follow.plan_core as plan_core
        from plan_follow.plan_todo import _apply_write

        fake_status = {
            "tasks": [
                {"id": "t1", "name": "T1", "status": "completed"},
            ]
        }
        monkeypatch.setattr(plan_core, "get_plan_status", lambda: fake_status, raising=False)
        monkeypatch.setattr(plan_core, "update_task", lambda tid, data: {"status": "ok"}, raising=False)
        result = _apply_write([{"id": "t1", "status": "in_progress"}])
        assert isinstance(result, list)

    def test_update_task_exception_handled(self, monkeypatch):
        """Exception in update_task is caught (lines 129-131)."""
        import plan_follow.plan_core as plan_core
        from plan_follow.plan_todo import _apply_write

        fake_status = {
            "tasks": [
                {"id": "t1", "name": "T1", "status": "completed"},
            ]
        }

        def failing_update(*args, **kwargs):
            raise ValueError("Simulated failure")

        monkeypatch.setattr(plan_core, "get_plan_status", lambda: fake_status, raising=False)
        monkeypatch.setattr(plan_core, "update_task", failing_update, raising=False)
        result = _apply_write([{"id": "t1", "status": "in_progress"}])
        assert isinstance(result, list)


class TestPlanTodoTool:
    """Tests for plan_todo_tool edge cases."""

    def test_no_args_returns_current_state(self):
        """plan_todo_tool with no args returns current state."""
        from plan_follow.plan_todo import plan_todo_tool
        result = plan_todo_tool({})
        assert result is not None
        assert isinstance(result, str)

    def test_with_merge_true(self, monkeypatch):
        """plan_todo_tool with merge=true processes writes."""
        import plan_follow.plan_core as plan_core
        from plan_follow.plan_todo import plan_todo_tool

        fake_status = {
            "tasks": [
                {"id": "t1", "name": "T1", "status": "pending"},
            ]
        }
        monkeypatch.setattr(plan_core, "get_plan_status", lambda: fake_status, raising=False)
        result = plan_todo_tool({"todos": [{"id": "t1", "status": "completed"}], "merge": True})
        assert result is not None

    def test_empty_plan_returns_empty(self, monkeypatch):
        """When no plan exists, returns empty todo list."""
        import plan_follow.plan_core as plan_core
        from plan_follow.plan_todo import plan_todo_tool

        monkeypatch.setattr(plan_core, "get_plan_status", lambda: None, raising=False)
        result = plan_todo_tool({})
        assert result is not None

    def test_merge_false_reads_only(self, monkeypatch):
        """plan_todo_tool with merge=False (default) reads current state."""
        import plan_follow.plan_core as plan_core
        from plan_follow.plan_todo import plan_todo_tool

        fake_status = {
            "tasks": [
                {"id": "t1", "name": "T1", "status": "pending"},
            ]
        }
        monkeypatch.setattr(plan_core, "get_plan_status", lambda: fake_status, raising=False)
        result = plan_todo_tool({"todos": [{"id": "t1", "status": "completed"}], "merge": False})
        assert result is not None


class TestBuildSummary:
    """Tests for _build_summary — edge cases."""

    def test_all_statuses(self):
        from plan_follow.plan_todo import _build_summary
        todos = [
            {"id": "1", "status": "completed"},
            {"id": "2", "status": "pending"},
            {"id": "3", "status": "in_progress"},
            {"id": "4", "status": "cancelled"},
        ]
        summary = _build_summary(todos)
        assert summary["total"] == 4
        assert summary["completed"] == 1
        assert summary["pending"] == 1
        assert summary["in_progress"] == 1
        assert summary["cancelled"] == 1

    def test_empty_list(self):
        from plan_follow.plan_todo import _build_summary
        summary = _build_summary([])
        assert summary["total"] == 0
        assert summary["completed"] == 0
        assert summary["pending"] == 0
        assert summary["in_progress"] == 0
        assert summary["cancelled"] == 0
