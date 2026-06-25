"""Tests for plan_follow.plan_decompose (HTN-Style Plan Decomposition).

Tests cover:
- create_compound_task — creating compound tasks with subtasks
- expand_task — expanding compound tasks into top-level tasks
- collapse_task — collapsing subtasks back with aggregate status
- get_subtask_status — reading subtask status breakdown
- prepare_delegation — preparing delegation prompts
- Error cases: no active plan, missing tasks, duplicate IDs, empty subtasks
"""

from __future__ import annotations

import pytest
from unittest.mock import patch
from typing import Any

# ---------------------------------------------------------------------------
# Module under test
# ---------------------------------------------------------------------------
MODULE_PATH = "plan_follow.plan_decompose"

# ---------------------------------------------------------------------------
# Fixtures — build minimal plan dicts
# ---------------------------------------------------------------------------


def make_plan(tasks: dict[str, Any] | None = None, **overrides) -> dict:
    """Create a minimal plan dict for test use."""
    plan: dict[str, Any] = {
        "plan_id": "test_plan_001",
        "goal": "Test plan goal",
        "current_task": None,
        "tasks": tasks or {},
    }
    plan.update(overrides)
    return plan


def make_task(
    task_id: str,
    name: str | None = None,
    status: str = "pending",
    subtasks: list[dict] | None = None,
    subtasks_expanded: bool = False,
    **overrides,
) -> dict:
    """Create a minimal task dict for test use."""
    task: dict[str, Any] = {
        "id": task_id,
        "name": name or task_id,
        "status": status,
        "files": [],
        "verify": "",
        "review_profile": "none",
        "review_result": None,
        "depends_on": [],
    }
    if subtasks is not None:
        task["subtasks"] = subtasks
        task["subtasks_expanded"] = subtasks_expanded
        task["_is_compound"] = True
    task.update(overrides)
    return task


def make_subtask(
    sub_id: str,
    name: str | None = None,
    files: list[str] | None = None,
    verify: str = "",
    depends_on: list[str] | None = None,
) -> dict:
    return {
        "id": sub_id,
        "name": name or sub_id,
        "files": files or [],
        "verify": verify,
        "depends_on": depends_on or [],
    }


# ---------------------------------------------------------------------------
# Helpers: mock _get_active_plan / _save_plan
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_base():
    """Patch _get_active_plan and _save_plan in the module under test.

    Yields (get_active_plan_mock, save_plan_mock) for per-test setup.
    """
    with patch(f"{MODULE_PATH}._get_active_plan") as mock_get, patch(
        f"{MODULE_PATH}._save_plan"
    ) as mock_save:
        yield mock_get, mock_save


def patch_plan(mock_get, plan: dict):
    """Configure _get_active_plan to return *plan*."""
    mock_get.return_value = plan


def patch_no_plan(mock_get):
    """Configure _get_active_plan to return None."""
    mock_get.return_value = None


# ===================================================================
# Tests: create_compound_task
# ===================================================================


class TestCreateCompoundTask:
    def test_basic_creation(self, mock_base):
        """Create a compound task with subtasks, no task_id given."""
        mock_get, mock_save = mock_base
        plan = make_plan()
        patch_plan(mock_get, plan)

        from plan_follow.plan_decompose import create_compound_task

        subtasks = [make_subtask("s1"), make_subtask("s2")]
        result = create_compound_task("My Task", subtasks)

        assert result["status"] == "created"
        assert result["name"] == "My Task"
        assert result["subtasks"] == 2
        assert "task_id" in result
        assert result["task_id"] in plan["tasks"]

        task = plan["tasks"][result["task_id"]]
        assert task["name"] == "My Task"
        assert task["_is_compound"] is True
        assert task["subtasks"] == subtasks
        assert task["subtasks_expanded"] is False
        assert task["status"] == "pending"
        mock_save.assert_called_once_with(plan)

    def test_custom_task_id(self, mock_base):
        """Create a compound task with an explicit task_id."""
        mock_get, mock_save = mock_base
        plan = make_plan()
        patch_plan(mock_get, plan)

        from plan_follow.plan_decompose import create_compound_task

        result = create_compound_task("Named", [make_subtask("s1")], task_id="my_compound")

        assert result["status"] == "created"
        assert result["task_id"] == "my_compound"
        assert "my_compound" in plan["tasks"]

    def test_duplicate_task_id(self, mock_base):
        """Return error when a task with the same ID already exists."""
        mock_get, mock_save = mock_base
        plan = make_plan({"existing": make_task("existing")})
        patch_plan(mock_get, plan)

        from plan_follow.plan_decompose import create_compound_task

        result = create_compound_task("Dup", [make_subtask("s1")], task_id="existing")

        assert result["status"] == "error"
        assert "already exists" in result["message"]
        mock_save.assert_not_called()

    def test_no_active_plan(self, mock_base):
        """Return error when there is no active plan."""
        mock_get, mock_save = mock_base
        patch_no_plan(mock_get)

        from plan_follow.plan_decompose import create_compound_task

        result = create_compound_task("X", [make_subtask("s1")])

        assert result["status"] == "error"
        assert "No active plan" in result["message"]
        mock_save.assert_not_called()

    def test_first_subtask_depends_on_current(self, mock_base):
        """First subtask gets current_task prepended to its depends_on."""
        mock_get, mock_save = mock_base
        plan = make_plan(current_task="prev_task")
        patch_plan(mock_get, plan)

        from plan_follow.plan_decompose import create_compound_task

        subtasks = [make_subtask("s1", depends_on=["pre"]), make_subtask("s2")]
        create_compound_task("Dep", subtasks, task_id="ct_dep")

        # In the actual code, depends_on is modified on the subtask *in the call*,
        # but subtasks[0] gets a reference to the same dict. We check the plan tasks.
        # The compound task stores the subtasks list — the first entry's depends_on
        # should start with "prev_task" then "pre"
        ct = plan["tasks"]["ct_dep"]
        assert ct["subtasks"][0]["depends_on"][0] == "prev_task"
        assert ct["subtasks"][0]["depends_on"][1] == "pre"


# ===================================================================
# Tests: expand_task
# ===================================================================


class TestExpandTask:
    COMPOUND_TASK_ID = "ct1"
    SUBTASK_IDS = ["sub_a", "sub_b"]

    def _make_compound_plan(self, current_task: str | None = None) -> dict:
        """Helper: plan with an unexpanded compound task."""
        subtasks = [
            make_subtask("sub_a", name="Sub A", files=["a.txt"], verify="echo a"),
            make_subtask("sub_b", name="Sub B", files=["b.txt"], verify="echo b"),
        ]
        ct = make_task(
            self.COMPOUND_TASK_ID,
            name="Compound Task",
            status="pending",
            subtasks=subtasks,
            subtasks_expanded=False,
        )
        plan = make_plan(tasks={self.COMPOUND_TASK_ID: ct}, current_task=current_task)
        return plan

    def test_basic_expand(self, mock_base):
        """Promote subtasks to top-level tasks."""
        mock_get, mock_save = mock_base
        plan = self._make_compound_plan()
        patch_plan(mock_get, plan)

        from plan_follow.plan_decompose import expand_task

        result = expand_task(self.COMPOUND_TASK_ID)

        assert result["status"] == "expanded"
        assert result["subtasks_promoted"] == 2
        assert result["current_task"] is None

        # Both subtasks should be in plan["tasks"]
        for sid in self.SUBTASK_IDS:
            assert sid in plan["tasks"]
            st = plan["tasks"][sid]
            assert st["status"] == "pending"
            assert st["_parent_task"] == self.COMPOUND_TASK_ID
            assert self.COMPOUND_TASK_ID in st["depends_on"]

        # Compound task should be marked expanded
        assert plan["tasks"][self.COMPOUND_TASK_ID]["subtasks_expanded"] is True
        assert plan["tasks"][self.COMPOUND_TASK_ID]["status"] == "in_progress"
        mock_save.assert_called_once_with(plan)

    def test_expand_moves_current_task(self, mock_base):
        """When compound task is current_task, move to first subtask."""
        mock_get, mock_save = mock_base
        plan = self._make_compound_plan(current_task=self.COMPOUND_TASK_ID)
        patch_plan(mock_get, plan)

        from plan_follow.plan_decompose import expand_task

        result = expand_task(self.COMPOUND_TASK_ID)

        assert result["current_task"] == "sub_a"
        assert plan["current_task"] == "sub_a"
        assert plan["tasks"]["sub_a"]["status"] == "in_progress"

    def test_expand_idempotent(self, mock_base):
        """Expanding again does not duplicate subtasks."""
        mock_get, mock_save = mock_base
        plan = self._make_compound_plan()
        plan["tasks"][self.COMPOUND_TASK_ID]["subtasks"]
        # Pre-populate one subtask to simulate partial expand
        plan["tasks"]["sub_a"] = make_task("sub_a", status="in_progress")
        patch_plan(mock_get, plan)

        from plan_follow.plan_decompose import expand_task

        result = expand_task(self.COMPOUND_TASK_ID)

        assert result["subtasks_promoted"] == 1  # only sub_b was new
        assert "sub_a" in plan["tasks"]
        assert "sub_b" in plan["tasks"]

    def test_task_not_found(self, mock_base):
        """Return error for unknown task."""
        mock_get, mock_save = mock_base
        plan = make_plan()
        patch_plan(mock_get, plan)

        from plan_follow.plan_decompose import expand_task

        result = expand_task("nonexistent")

        assert result["status"] == "error"
        assert "not found" in result["message"]
        mock_save.assert_not_called()

    def test_no_subtasks(self, mock_base):
        """Return error for task without subtasks."""
        mock_get, mock_save = mock_base
        task = make_task("plain")
        plan = make_plan(tasks={"plain": task})
        patch_plan(mock_get, plan)

        from plan_follow.plan_decompose import expand_task

        result = expand_task("plain")

        assert result["status"] == "error"
        assert "has no sub-tasks" in result["message"]
        mock_save.assert_not_called()

    def test_no_active_plan(self, mock_base):
        """Return error when there is no active plan."""
        mock_get, mock_save = mock_base
        patch_no_plan(mock_get)

        from plan_follow.plan_decompose import expand_task

        result = expand_task("ct1")

        assert result["status"] == "error"
        assert "No active plan" in result["message"]
        mock_save.assert_not_called()


# ===================================================================
# Tests: collapse_task
# ===================================================================


class TestCollapseTask:
    COMPOUND_TASK_ID = "ct_collapse"

    def _make_expanded_plan(self, subtask_statuses: dict[str, str]) -> dict:
        """Build a plan where the compound task is already expanded.

        *subtask_statuses* maps subtask_id -> status string.
        """
        subtasks = [
            make_subtask("s_done", name="Done"),
            make_subtask("s_wip", name="WIP"),
            make_subtask("s_abort", name="Abort"),
        ]
        ct = make_task(
            self.COMPOUND_TASK_ID,
            name="Collapsible",
            status="in_progress",
            subtasks=subtasks,
            subtasks_expanded=True,
        )
        tasks: dict[str, Any] = {
            self.COMPOUND_TASK_ID: ct,
        }
        for sid, st in zip(["s_done", "s_wip", "s_abort"], subtasks):
            tasks[sid] = make_task(
                sid,
                name=st["name"],
                status=subtask_statuses.get(sid, "pending"),
                _parent_task=self.COMPOUND_TASK_ID,
            )
        return make_plan(tasks=tasks, current_task="s_wip")

    def test_collapse_all_completed(self, mock_base):
        """All subtasks completed -> compound task becomes completed."""
        mock_get, mock_save = mock_base
        plan = self._make_expanded_plan({"s_done": "completed", "s_wip": "completed", "s_abort": "completed"})
        patch_plan(mock_get, plan)

        from plan_follow.plan_decompose import collapse_task

        result = collapse_task(self.COMPOUND_TASK_ID)

        assert result["status"] == "collapsed"
        assert result["aggregate_status"] == "completed"
        assert plan["tasks"][self.COMPOUND_TASK_ID]["subtasks_expanded"] is False
        # Subtasks should be removed from plan
        for sid in ("s_done", "s_wip", "s_abort"):
            assert sid not in plan["tasks"]
        mock_save.assert_called_once_with(plan)

    def test_collapse_in_progress(self, mock_base):
        """Some subtasks in_progress -> compound becomes in_progress."""
        mock_get, mock_save = mock_base
        plan = self._make_expanded_plan({"s_done": "completed", "s_wip": "in_progress", "s_abort": "pending"})
        patch_plan(mock_get, plan)

        from plan_follow.plan_decompose import collapse_task

        result = collapse_task(self.COMPOUND_TASK_ID)

        assert result["status"] == "collapsed"
        assert result["aggregate_status"] == "in_progress"

    def test_collapse_aborted(self, mock_base):
        """Any subtask aborted -> compound becomes aborted."""
        mock_get, mock_save = mock_base
        plan = self._make_expanded_plan({"s_done": "completed", "s_wip": "aborted", "s_abort": "pending"})
        patch_plan(mock_get, plan)

        from plan_follow.plan_decompose import collapse_task

        result = collapse_task(self.COMPOUND_TASK_ID)

        assert result["status"] == "collapsed"
        assert result["aggregate_status"] == "aborted"

    def test_collapse_all_pending(self, mock_base):
        """No in_progress / completed / aborted -> compound stays pending."""
        mock_get, mock_save = mock_base
        plan = self._make_expanded_plan({"s_done": "pending", "s_wip": "pending", "s_abort": "pending"})
        patch_plan(mock_get, plan)

        from plan_follow.plan_decompose import collapse_task

        result = collapse_task(self.COMPOUND_TASK_ID)

        assert result["status"] == "collapsed"
        assert result["aggregate_status"] == "pending"

    def test_collapse_resets_current_task(self, mock_base):
        """After collapse, current_task reverts to the compound task."""
        mock_get, mock_save = mock_base
        plan = self._make_expanded_plan({"s_done": "completed", "s_wip": "completed", "s_abort": "completed"})
        plan["current_task"] = "s_wip"
        patch_plan(mock_get, plan)

        from plan_follow.plan_decompose import collapse_task

        collapse_task(self.COMPOUND_TASK_ID)

        assert plan["current_task"] == self.COMPOUND_TASK_ID

    def test_task_not_found(self, mock_base):
        """Return error for unknown task."""
        mock_get, mock_save = mock_base
        plan = make_plan()
        patch_plan(mock_get, plan)

        from plan_follow.plan_decompose import collapse_task

        result = collapse_task("nonexistent")

        assert result["status"] == "error"
        assert "not found" in result["message"]
        mock_save.assert_not_called()

    def test_no_subtasks(self, mock_base):
        """Return error for task without subtasks."""
        mock_get, mock_save = mock_base
        plan = make_plan(tasks={"plain": make_task("plain")})
        patch_plan(mock_get, plan)

        from plan_follow.plan_decompose import collapse_task

        result = collapse_task("plain")

        assert result["status"] == "error"
        assert "has no sub-tasks" in result["message"]
        mock_save.assert_not_called()

    def test_no_active_plan(self, mock_base):
        """Return error when there is no active plan."""
        mock_get, mock_save = mock_base
        patch_no_plan(mock_get)

        from plan_follow.plan_decompose import collapse_task

        result = collapse_task("ct1")

        assert result["status"] == "error"
        assert "No active plan" in result["message"]
        mock_save.assert_not_called()


# ===================================================================
# Tests: get_subtask_status
# ===================================================================


class TestGetSubtaskStatus:
    COMPOUND_TASK_ID = "ct_status"

    def _make_plan(self, expanded: bool = False) -> dict:
        subtasks = [
            make_subtask("st1", name="Step 1", files=["f1.py"]),
            make_subtask("st2", name="Step 2"),
        ]
        ct = make_task(
            self.COMPOUND_TASK_ID,
            name="Status Task",
            status="in_progress" if expanded else "pending",
            subtasks=subtasks,
            subtasks_expanded=expanded,
        )
        tasks: dict[str, Any] = {self.COMPOUND_TASK_ID: ct}
        if expanded:
            tasks["st1"] = make_task("st1", name="Step 1", status="in_progress", files=["f1.py"])
            tasks["st2"] = make_task("st2", name="Step 2", status="pending")
        return make_plan(tasks=tasks)

    def test_basic_status_not_expanded(self, mock_base):
        """Subtask status reports not_expanded when compound not expanded."""
        mock_get, mock_save = mock_base
        plan = self._make_plan(expanded=False)
        patch_plan(mock_get, plan)

        from plan_follow.plan_decompose import get_subtask_status

        result = get_subtask_status(self.COMPOUND_TASK_ID)

        assert result["status"] == "ok"
        assert result["expanded"] is False
        assert result["count"] == 2
        assert result["completed"] == 0
        for st in result["subtasks"]:
            assert st["status"] == "not_expanded"
        mock_save.assert_not_called()

    def test_basic_status_expanded(self, mock_base):
        """Subtask status shows actual statuses when expanded."""
        mock_get, mock_save = mock_base
        plan = self._make_plan(expanded=True)
        # Mark st1 completed
        plan["tasks"]["st1"]["status"] = "completed"
        patch_plan(mock_get, plan)

        from plan_follow.plan_decompose import get_subtask_status

        result = get_subtask_status(self.COMPOUND_TASK_ID)

        assert result["status"] == "ok"
        assert result["expanded"] is True
        assert result["count"] == 2
        assert result["completed"] == 1
        # st1 should be completed, st2 not_expanded (it's in plan but we only check expanded flag
        # at compound level — individual subtask status comes from plan tasks)
        st_map = {st["id"]: st for st in result["subtasks"]}
        assert st_map["st1"]["status"] == "completed"
        assert st_map["st2"]["status"] == "pending"
        assert st_map["st1"]["files"] == ["f1.py"]
        mock_save.assert_not_called()

    def test_no_subtasks(self, mock_base):
        """Return error for task without subtasks attribute."""
        mock_get, mock_save = mock_base
        plan = make_plan(tasks={"plain": make_task("plain")})
        patch_plan(mock_get, plan)

        from plan_follow.plan_decompose import get_subtask_status

        result = get_subtask_status("plain")

        assert result["status"] == "error"
        assert "has no sub-tasks" in result["message"]
        mock_save.assert_not_called()

    def test_task_not_found(self, mock_base):
        """Return error for unknown task."""
        mock_get, mock_save = mock_base
        plan = make_plan()
        patch_plan(mock_get, plan)

        from plan_follow.plan_decompose import get_subtask_status

        result = get_subtask_status("nonexistent")

        assert result["status"] == "error"
        assert "not found" in result["message"]
        mock_save.assert_not_called()

    def test_no_active_plan(self, mock_base):
        """Return error when there is no active plan."""
        mock_get, mock_save = mock_base
        patch_no_plan(mock_get)

        from plan_follow.plan_decompose import get_subtask_status

        result = get_subtask_status("ct1")

        assert result["status"] == "error"
        assert "No active plan" in result["message"]
        mock_save.assert_not_called()


# ===================================================================
# Tests: prepare_delegation
# ===================================================================


class TestPrepareDelegation:
    TASK_ID = "delegable_task"

    def test_basic_delegation(self, mock_base):
        """Generate delegation prompt with files and verify command."""
        mock_get, mock_save = mock_base
        task = make_task(
            self.TASK_ID,
            name="Implement Feature",
            files=["src/feature.py", "tests/test_feature.py"],
            verify="pytest tests/test_feature.py",
            review_profile="code_review",
        )
        plan = make_plan(tasks={self.TASK_ID: task})
        patch_plan(mock_get, plan)

        from plan_follow.plan_decompose import prepare_delegation

        result = prepare_delegation(self.TASK_ID)

        assert result["status"] == "ready"
        assert result["task_id"] == self.TASK_ID
        assert result["task_name"] == "Implement Feature"
        assert result["plan_id"] == "test_plan_001"
        assert "toolsets" in result
        assert "terminal" in result["toolsets"]
        assert "file" in result["toolsets"]

        prompt = result["delegation_prompt"]
        assert "Implement Feature" in prompt
        assert "src/feature.py" in prompt
        assert "tests/test_feature.py" in prompt
        assert "pytest tests/test_feature.py" in prompt
        assert "Review Profile" in prompt
        assert "code_review" in prompt
        assert "Instructions" in prompt
        assert "Implement the necessary changes" in prompt
        mock_save.assert_not_called()

    def test_delegation_no_files(self, mock_base):
        """Delegation prompt shows fallback when no files are declared."""
        mock_get, mock_save = mock_base
        task = make_task(self.TASK_ID, name="No Files")
        plan = make_plan(tasks={self.TASK_ID: task})
        patch_plan(mock_get, plan)

        from plan_follow.plan_decompose import prepare_delegation

        result = prepare_delegation(self.TASK_ID)

        prompt = result["delegation_prompt"]
        assert "no specific files declared" in prompt.lower() or "check the plan goal" in prompt
        mock_save.assert_not_called()

    def test_task_not_found(self, mock_base):
        """Return error for unknown task."""
        mock_get, mock_save = mock_base
        plan = make_plan()
        patch_plan(mock_get, plan)

        from plan_follow.plan_decompose import prepare_delegation

        result = prepare_delegation("nonexistent")

        assert result["status"] == "error"
        assert "not found" in result["message"]
        mock_save.assert_not_called()

    def test_no_active_plan(self, mock_base):
        """Return error when there is no active plan."""
        mock_get, mock_save = mock_base
        patch_no_plan(mock_get)

        from plan_follow.plan_decompose import prepare_delegation

        result = prepare_delegation("x")

        assert result["status"] == "error"
        assert "No active plan" in result["message"]
        mock_save.assert_not_called()


# ===================================================================
# Tests: Integration-style — create → expand → status → collapse
# ===================================================================


class TestLifecycleIntegration:
    """Simulate the full create → expand → status → collapse workflow."""

    def test_full_lifecycle(self, mock_base):
        """Complete workflow: create compound, expand, check status, collapse."""
        mock_get, mock_save = mock_base
        plan = make_plan(current_task="setup")
        patch_plan(mock_get, plan)

        from plan_follow.plan_decompose import (
            create_compound_task,
            expand_task,
            get_subtask_status,
            collapse_task,
        )

        # 1. Create compound task
        subtasks = [
            make_subtask("step1", name="Step One", files=["s1.py"], verify="pytest s1.py"),
            make_subtask("step2", name="Step Two", files=["s2.py"], verify="pytest s2.py"),
        ]
        cr = create_compound_task("Integration Compound", subtasks, task_id="ict")
        assert cr["status"] == "created"
        assert "ict" in plan["tasks"]
        ct = plan["tasks"]["ict"]
        assert ct["subtasks_expanded"] is False

        # 2. Expand
        er = expand_task("ict")
        assert er["status"] == "expanded"
        assert er["subtasks_promoted"] == 2
        assert "step1" in plan["tasks"]
        assert "step2" in plan["tasks"]
        assert plan["tasks"]["ict"]["subtasks_expanded"] is True

        # 3. Get subtask status (not expanded at compound level now)
        sr = get_subtask_status("ict")
        assert sr["status"] == "ok"
        assert sr["expanded"] is True
        assert sr["count"] == 2
        st_map = {st["id"]: st for st in sr["subtasks"]}
        assert st_map["step1"]["status"] == "pending"
        assert st_map["step2"]["status"] == "pending"

        # 4. Simulate step1 completed, step2 in_progress in plan
        plan["tasks"]["step1"]["status"] = "completed"
        plan["tasks"]["step2"]["status"] = "in_progress"

        # 5. Collapse
        col = collapse_task("ict")
        assert col["status"] == "collapsed"
        assert col["aggregate_status"] == "in_progress"  # step2 still in_progress
        assert "step1" not in plan["tasks"]
        assert "step2" not in plan["tasks"]
        assert plan["tasks"]["ict"]["subtasks_expanded"] is False
        assert plan["current_task"] == "ict"


# ===================================================================
# Tests: Edge Cases
# ===================================================================


class TestEdgeCases:
    def test_expand_empty_subtask_id(self, mock_base):
        """Subtask with empty id is skipped during expand."""
        mock_get, mock_save = mock_base
        ct = make_task(
            "ct_empty",
            name="Empty ID",
            status="pending",
            subtasks=[
                make_subtask("", name="NoID"),
                make_subtask("valid_st", name="Valid"),
            ],
            subtasks_expanded=False,
        )
        plan = make_plan(tasks={"ct_empty": ct})
        patch_plan(mock_get, plan)

        from plan_follow.plan_decompose import expand_task

        result = expand_task("ct_empty")

        assert result["subtasks_promoted"] == 1
        assert "" not in plan["tasks"]
        assert "valid_st" in plan["tasks"]

    def test_collapse_subtask_not_in_plan(self, mock_base):
        """Subtask referenced in compound but not in plan tasks is skipped."""
        mock_get, mock_save = mock_base
        subtasks = [make_subtask("orphan", name="Orphan")]
        ct = make_task(
            "ct_orphan",
            name="Orphan child",
            status="in_progress",
            subtasks=subtasks,
            subtasks_expanded=True,
        )
        # Do NOT add "orphan" to plan tasks — it's missing
        plan = make_plan(tasks={"ct_orphan": ct}, current_task="ct_orphan")
        patch_plan(mock_get, plan)

        from plan_follow.plan_decompose import collapse_task

        result = collapse_task("ct_orphan")

        # All subtasks "completed" because the missing one is never checked
        assert result["status"] == "collapsed"
        assert result["aggregate_status"] == "completed"

    def test_delegation_suggestion_string(self, mock_base):
        """Delegation result contains a 'suggestion' key."""
        mock_get, mock_save = mock_base
        plan = make_plan(tasks={"t": make_task("t", name="Task")})
        patch_plan(mock_get, plan)

        from plan_follow.plan_decompose import prepare_delegation

        result = prepare_delegation("t")

        assert "suggestion" in result
        assert "delegate_task" in result["suggestion"]
