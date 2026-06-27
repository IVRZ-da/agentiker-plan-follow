"""Coverage gap tests for plan_decompose.py — edge cases and error paths.

Tests cover uncovered lines in:
- expand_task() — invalid task, missing data
- collapse_task() — status edge cases
- get_subtask_status() — not_expanded path
- prepare_delegation() — no files, missing plan/task
- plan_decompose_tool() — error paths (no action, unknown action, missing task_id)
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

# Ensure the plugin package is on sys.path
_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))

MODULE_PATH = "plan_follow.plan_decompose"


# ─── Helper: minimal plan fixtures ─────────────────────────────────────────


def make_plan(tasks: dict | None = None, current_task: str | None = None, **overrides) -> dict:
    plan = {
        "plan_id": "test-plan",
        "goal": "Test Goal",
        "tasks": tasks or {},
        "current_task": current_task,
        "parallel_groups": {},
    }
    plan.update(overrides)
    return plan


def make_compound_task(task_id: str, subtasks: list[dict], status: str = "pending",
                       subtasks_expanded: bool = False, **overrides) -> dict:
    return {
        "id": task_id,
        "name": f"Task {task_id}",
        "status": status,
        "files": [],
        "verify": "echo ok",
        "review_profile": "none",
        "review_result": None,
        "depends_on": [],
        "subtasks": subtasks,
        "subtasks_expanded": subtasks_expanded,
        "_is_compound": True,
        **overrides,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# expand_task() — edge cases
# ═══════════════════════════════════════════════════════════════════════════════


class TestExpandTaskEdgeCases:
    """Coverage: expand_task() lines 34–41, 44–46."""

    def test_no_active_plan(self):
        """expand_task returns error when there's no active plan."""
        from plan_follow.plan_decompose import expand_task  # noqa: E402

        with patch(f"{MODULE_PATH}._get_active_plan", return_value=None):
            result = expand_task("t1")
        assert result["status"] == "error"
        assert "No active plan" in result["message"]

    def test_task_not_found(self):
        """expand_task returns error when the task ID doesn't exist."""
        from plan_follow.plan_decompose import expand_task

        plan = make_plan(tasks={"other": make_compound_task("other", subtasks=[])})
        with patch(f"{MODULE_PATH}._get_active_plan", return_value=plan), \
             patch(f"{MODULE_PATH}._save_plan"):
            result = expand_task("nonexistent")
        assert result["status"] == "error"
        assert "not found" in result["message"]

    def test_task_has_no_subtasks(self):
        """expand_task returns error when task has no subtasks list."""
        from plan_follow.plan_decompose import expand_task

        task = make_compound_task("t1", subtasks=[])
        plan = make_plan(tasks={"t1": task})
        with patch(f"{MODULE_PATH}._get_active_plan", return_value=plan), \
             patch(f"{MODULE_PATH}._save_plan"):
            result = expand_task("t1")
        assert result["status"] == "error"
        assert "has no sub-tasks" in result["message"]

    def test_subtask_without_id_skipped(self):
        """A subtask dict without an 'id' key is skipped without error."""
        from plan_follow.plan_decompose import expand_task

        subtasks = [
            {"name": "orphan", "files": []},          # no id — should skip
            {"id": "st2", "name": "valid", "files": []},
        ]
        task = make_compound_task("t1", subtasks=subtasks)
        plan = make_plan(tasks={"t1": task})
        with patch(f"{MODULE_PATH}._get_active_plan", return_value=plan), \
             patch(f"{MODULE_PATH}._save_plan"):
            result = expand_task("t1")
        assert result["status"] == "expanded"
        assert result["subtasks_promoted"] == 1  # only st2 promoted
        # st2 should exist in plan tasks
        assert "st2" in plan["tasks"]
        assert plan["tasks"]["st2"]["_parent_task"] == "t1"

    def test_expand_updates_current_task(self):
        """When expanding current_task, moves current to first subtask."""
        from plan_follow.plan_decompose import expand_task

        subtasks = [{"id": "st1", "name": "Sub One", "files": []},
                    {"id": "st2", "name": "Sub Two", "files": []}]
        task = make_compound_task("ct1", subtasks=subtasks)
        plan = make_plan(tasks={"ct1": task}, current_task="ct1")
        with patch(f"{MODULE_PATH}._get_active_plan", return_value=plan), \
             patch(f"{MODULE_PATH}._save_plan"):
            result = expand_task("ct1")
        assert result["status"] == "expanded"
        assert plan["current_task"] == "st1"
        assert plan["tasks"]["st1"]["status"] == "in_progress"

    def test_subtask_already_promoted_skipped(self):
        """If a subtask ID already exists in tasks, it is not re-promoted."""
        from plan_follow.plan_decompose import expand_task

        subtasks = [{"id": "st1", "name": "Existing", "files": []}]
        task = make_compound_task("ct1", subtasks=subtasks)
        plan = make_plan(tasks={"ct1": task, "st1": {"id": "st1", "status": "completed"}})
        with patch(f"{MODULE_PATH}._get_active_plan", return_value=plan), \
             patch(f"{MODULE_PATH}._save_plan"):
            result = expand_task("ct1")
        assert result["status"] == "expanded"
        assert result["subtasks_promoted"] == 0  # not re-promoted


# ═══════════════════════════════════════════════════════════════════════════════
# collapse_task() — edge cases
# ═══════════════════════════════════════════════════════════════════════════════


class TestCollapseTaskEdgeCases:
    """Coverage: collapse_task() status calculation edge cases."""

    def test_collapse_no_active_plan(self):
        """collapse_task returns error when there's no active plan."""
        from plan_follow.plan_decompose import collapse_task

        with patch(f"{MODULE_PATH}._get_active_plan", return_value=None):
            result = collapse_task("t1")
        assert result["status"] == "error"
        assert "No active plan" in result["message"]

    def test_collapse_task_not_found(self):
        """collapse_task returns error when task ID doesn't exist."""
        from plan_follow.plan_decompose import collapse_task

        plan = make_plan()
        with patch(f"{MODULE_PATH}._get_active_plan", return_value=plan), \
             patch(f"{MODULE_PATH}._save_plan"):
            result = collapse_task("nonexistent")
        assert result["status"] == "error"
        assert "not found" in result["message"]

    def test_collapse_no_subtasks(self):
        """collapse_task returns error when compound task has no subtasks."""
        from plan_follow.plan_decompose import collapse_task

        task = make_compound_task("ct1", subtasks=[])
        plan = make_plan(tasks={"ct1": task})
        with patch(f"{MODULE_PATH}._get_active_plan", return_value=plan), \
             patch(f"{MODULE_PATH}._save_plan"):
            result = collapse_task("ct1")
        assert result["status"] == "error"
        assert "has no sub-tasks" in result["message"]

    def test_collapse_all_completed(self):
        """Aggregate status is 'completed' when all subtasks are completed."""
        from plan_follow.plan_decompose import collapse_task

        subtasks = [{"id": "st1"}, {"id": "st2"}]
        task = make_compound_task("ct1", subtasks=subtasks, subtasks_expanded=True)
        plan = make_plan(tasks={
            "ct1": task,
            "st1": {"id": "st1", "status": "completed", "files": []},
            "st2": {"id": "st2", "status": "completed", "files": []},
        })
        with patch(f"{MODULE_PATH}._get_active_plan", return_value=plan), \
             patch(f"{MODULE_PATH}._save_plan"):
            result = collapse_task("ct1")
        assert result["status"] == "collapsed"
        assert result["aggregate_status"] == "completed"

    def test_collapse_mixed_status(self):
        """Aggregate status is 'in_progress' when some but not all done."""
        from plan_follow.plan_decompose import collapse_task

        subtasks = [{"id": "st1"}, {"id": "st2"}, {"id": "st3"}]
        task = make_compound_task("ct1", subtasks=subtasks, subtasks_expanded=True)
        plan = make_plan(tasks={
            "ct1": task,
            "st1": {"id": "st1", "status": "completed", "files": []},
            "st2": {"id": "st2", "status": "in_progress", "files": []},
            "st3": {"id": "st3", "status": "pending", "files": []},
        })
        with patch(f"{MODULE_PATH}._get_active_plan", return_value=plan), \
             patch(f"{MODULE_PATH}._save_plan"):
            result = collapse_task("ct1")
        assert result["status"] == "collapsed"
        assert result["aggregate_status"] == "in_progress"

    def test_collapse_any_aborted(self):
        """Aggregate status is 'aborted' when any subtask is aborted."""
        from plan_follow.plan_decompose import collapse_task

        subtasks = [{"id": "st1"}, {"id": "st2"}]
        task = make_compound_task("ct1", subtasks=subtasks, subtasks_expanded=True)
        plan = make_plan(tasks={
            "ct1": task,
            "st1": {"id": "st1", "status": "completed", "files": []},
            "st2": {"id": "st2", "status": "aborted", "files": []},
        })
        with patch(f"{MODULE_PATH}._get_active_plan", return_value=plan), \
             patch(f"{MODULE_PATH}._save_plan"):
            result = collapse_task("ct1")
        assert result["status"] == "collapsed"
        assert result["aggregate_status"] == "aborted"

    def test_collapse_all_pending(self):
        """Aggregate status is 'pending' when no subtask has started."""
        from plan_follow.plan_decompose import collapse_task

        subtasks = [{"id": "st1"}, {"id": "st2"}]
        task = make_compound_task("ct1", subtasks=subtasks, subtasks_expanded=True)
        plan = make_plan(tasks={
            "ct1": task,
            "st1": {"id": "st1", "status": "pending", "files": []},
            "st2": {"id": "st2", "status": "pending", "files": []},
        })
        with patch(f"{MODULE_PATH}._get_active_plan", return_value=plan), \
             patch(f"{MODULE_PATH}._save_plan"):
            result = collapse_task("ct1")
        assert result["status"] == "collapsed"
        assert result["aggregate_status"] == "pending"

    def test_subtask_not_in_plan_skipped(self):
        """A subtask not promoted yet doesn't crash collapse."""
        from plan_follow.plan_decompose import collapse_task

        subtasks = [{"id": "st1"}, {"id": "st2"}]
        task = make_compound_task("ct1", subtasks=subtasks, subtasks_expanded=True)
        plan = make_plan(tasks={
            "ct1": task,
            # st1 is missing from plan — not promoted yet
            "st2": {"id": "st2", "status": "completed", "files": []},
        })
        with patch(f"{MODULE_PATH}._get_active_plan", return_value=plan), \
             patch(f"{MODULE_PATH}._save_plan"):
            result = collapse_task("ct1")
        assert result["status"] == "collapsed"
        assert result["aggregate_status"] == "completed"


# ═══════════════════════════════════════════════════════════════════════════════
# get_subtask_status() — edge cases
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetSubtaskStatusEdgeCases:
    """Coverage: get_subtask_status() lines 157–167, 170–184."""

    def test_no_active_plan(self):
        from plan_follow.plan_decompose import get_subtask_status

        with patch(f"{MODULE_PATH}._get_active_plan", return_value=None):
            result = get_subtask_status("t1")
        assert result["status"] == "error"
        assert "No active plan" in result["message"]

    def test_task_not_found(self):
        from plan_follow.plan_decompose import get_subtask_status

        plan = make_plan()
        with patch(f"{MODULE_PATH}._get_active_plan", return_value=plan):
            result = get_subtask_status("nonexistent")
        assert result["status"] == "error"
        assert "not found" in result["message"]

    def test_no_subtasks(self):
        from plan_follow.plan_decompose import get_subtask_status

        task = make_compound_task("ct1", subtasks=[])
        plan = make_plan(tasks={"ct1": task})
        with patch(f"{MODULE_PATH}._get_active_plan", return_value=plan):
            result = get_subtask_status("ct1")
        assert result["status"] == "error"
        assert "has no sub-tasks" in result["message"]

    def test_subtask_not_expanded(self):
        """A subtask not yet in plan's tasks shows 'not_expanded' status."""
        from plan_follow.plan_decompose import get_subtask_status

        subtasks = [{"id": "st1", "name": "Sub One"}, {"id": "st2", "name": "Sub Two"}]
        task = make_compound_task("ct1", subtasks=subtasks)
        plan = make_plan(tasks={
            "ct1": task,
            # st2 is promoted, st1 is not
            "st2": {"id": "st2", "name": "Sub Two", "status": "completed", "files": []},
        })
        with patch(f"{MODULE_PATH}._get_active_plan", return_value=plan):
            result = get_subtask_status("ct1")
        assert result["status"] == "ok"
        assert result["count"] == 2
        # st1 should be not_expanded
        st1_result = [r for r in result["subtasks"] if r["id"] == "st1"][0]
        assert st1_result["status"] == "not_expanded"
        # st2 should show actual status
        st2_result = [r for r in result["subtasks"] if r["id"] == "st2"][0]
        assert st2_result["status"] == "completed"


# ═══════════════════════════════════════════════════════════════════════════════
# prepare_delegation() — edge cases
# ═══════════════════════════════════════════════════════════════════════════════


class TestPrepareDelegationEdgeCases:
    """Coverage: prepare_delegation() lines 259–266, 283–287."""

    def test_no_active_plan(self):
        from plan_follow.plan_decompose import prepare_delegation

        with patch(f"{MODULE_PATH}._get_active_plan", return_value=None):
            result = prepare_delegation("t1")
        assert result["status"] == "error"
        assert "No active plan" in result["message"]

    def test_task_not_found(self):
        from plan_follow.plan_decompose import prepare_delegation

        plan = make_plan()
        with patch(f"{MODULE_PATH}._get_active_plan", return_value=plan):
            result = prepare_delegation("nonexistent")
        assert result["status"] == "error"
        assert "not found" in result["message"]

    def test_task_with_no_files_shows_placeholder(self):
        """When a task has no files, the prompt includes a placeholder note."""
        from plan_follow.plan_decompose import prepare_delegation

        task = {"id": "d1", "name": "Delegate Me", "files": [],
                "verify": "pytest", "review_profile": "none"}
        plan = make_plan(tasks={"d1": task})
        with patch(f"{MODULE_PATH}._get_active_plan", return_value=plan):
            result = prepare_delegation("d1")
        assert result["status"] == "ready"
        assert "no specific files declared" in result["delegation_prompt"]

    def test_task_with_files_lists_them(self):
        """When a task has files, they appear in the delegation prompt."""
        from plan_follow.plan_decompose import prepare_delegation

        task = {"id": "d1", "name": "Delegate Me", "files": ["src/main.py", "src/utils.py"],
                "verify": "pytest", "review_profile": "unit-test"}
        plan = make_plan(tasks={"d1": task})
        with patch(f"{MODULE_PATH}._get_active_plan", return_value=plan):
            result = prepare_delegation("d1")
        assert result["status"] == "ready"
        assert "src/main.py" in result["delegation_prompt"]
        assert "src/utils.py" in result["delegation_prompt"]
        assert "unit-test" in result["delegation_prompt"]

    def test_delegation_has_correct_structure(self):
        """Delegation response includes all expected fields."""
        from plan_follow.plan_decompose import prepare_delegation

        task = {"id": "d1", "name": "Delegated", "files": ["a.py"],
                "verify": "python3 a.py", "review_profile": "none"}
        plan = make_plan(tasks={"d1": task}, plan_id="plan_42")
        with patch(f"{MODULE_PATH}._get_active_plan", return_value=plan):
            result = prepare_delegation("d1")
        assert result["status"] == "ready"
        assert result["task_id"] == "d1"
        assert result["plan_id"] == "plan_42"
        assert "toolsets" in result
        assert "delegate_task" in result["suggestion"]


# ═══════════════════════════════════════════════════════════════════════════════
# plan_decompose_tool() — error paths
# ═══════════════════════════════════════════════════════════════════════════════


class TestPlanDecomposeToolErrorPaths:
    """Coverage: plan_decompose_tool() lines 338–340, 343–344, 349–350, 355–356, 362–363, 369–370, 380."""

    def test_no_action(self):
        """Returns error when no action is provided."""
        from plan_follow.plan_decompose import plan_decompose_tool

        result = plan_decompose_tool({})
        assert "error" in result or "action is required" in result

    def test_unknown_action(self):
        """Returns error for unknown action."""
        from plan_follow.plan_decompose import plan_decompose_tool

        result = plan_decompose_tool({"action": "fly"})
        assert "error" in result or "Unknown action" in result

    def test_expand_missing_task_id(self):
        """Returns error when expand is called without task_id."""
        from plan_follow.plan_decompose import plan_decompose_tool

        result = plan_decompose_tool({"action": "expand"})
        assert "error" in result or "task_id is required" in result

    def test_collapse_missing_task_id(self):
        """Returns error when collapse is called without task_id."""
        from plan_follow.plan_decompose import plan_decompose_tool

        result = plan_decompose_tool({"action": "collapse"})
        assert "error" in result or "task_id is required" in result

    def test_status_missing_task_id(self):
        """Returns error when status is called without task_id."""
        from plan_follow.plan_decompose import plan_decompose_tool

        result = plan_decompose_tool({"action": "status"})
        assert "error" in result or "task_id is required" in result

    def test_create_missing_name(self):
        """Returns error when create is called without name."""
        from plan_follow.plan_decompose import plan_decompose_tool

        result = plan_decompose_tool({"action": "create", "subtasks": [{"id": "s1"}]})
        assert "error" in result or "name and subtasks" in result

    def test_create_missing_subtasks(self):
        """Returns error when create is called without subtasks."""
        from plan_follow.plan_decompose import plan_decompose_tool

        result = plan_decompose_tool({"action": "create", "name": "Test"})
        assert "error" in result or "name and subtasks" in result

    def test_delegate_missing_task_id(self):
        """Returns error when delegate is called without task_id."""
        from plan_follow.plan_decompose import plan_decompose_tool

        result = plan_decompose_tool({"action": "delegate"})
        assert "error" in result or "task_id is required" in result

    def test_delegate_no_active_plan(self):
        """Returns error when delegate is called with no active plan."""
        from plan_follow.plan_decompose import plan_decompose_tool

        # plan_decompose_tool uses plan_core._get_active_plan, while prepare_delegation
        # uses _get_active_plan from tools.base — patch the shared source
        with patch("plan_follow.tools.base._get_active_plan", return_value=None):
            result = plan_decompose_tool({"action": "delegate", "task_id": "t1"})
        assert "error" in result or "No active plan" in result

    def test_delegate_task_not_found(self):
        """Returns error when delegate task_id doesn't exist."""
        from plan_follow.plan_decompose import plan_decompose_tool

        plan = make_plan()
        with patch("plan_follow.tools.base._get_active_plan", return_value=plan):
            result = plan_decompose_tool({"action": "delegate", "task_id": "nonexistent"})
        assert "error" in result or "not found" in result

    def test_delegate_success(self):
        """Successful delegate call returns delegation prompt."""
        from plan_follow.plan_decompose import plan_decompose_tool

        task = {"id": "d1", "name": "Delegate", "files": ["a.py"],
                "verify": "echo ok", "review_profile": "none"}
        plan = make_plan(tasks={"d1": task})
        # Patch _get_active_plan at both sites where it's used:
        # - plan_core._get_active_plan() in plan_decompose_tool (via __getattr__ → tools.base)
        # - plan_decompose._get_active_plan() in prepare_delegation (module-level import)
        with patch("plan_follow.tools.base._get_active_plan", return_value=plan), \
             patch("plan_follow.plan_decompose._get_active_plan", return_value=plan):
            result = plan_decompose_tool({"action": "delegate", "task_id": "d1"})
        # fmt_ok wraps the delegation dict in JSON; should contain "status": "ready"
        assert '"status": "ready"' in result
