"""Coverage gap tests for plan_peer_review.py — edge cases and error paths.

Tests cover uncovered lines:
- run_peer_review() — line 121 (tasks as list), lines 141-144 (get_task with list),
  line 151 (task_ids from list), lines 194-195, 212-213 (Exception in auto-detect),
  line 302 (non-dict gdata in parallel_groups)
- apply_findings() — lines 352-353 (tasks list normalization), lines 359, 363 (continue)
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

# Ensure the plugin package is on sys.path
_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))

MODULE_PATH = "plan_follow.plan_peer_review"


# ─── Helpers ────────────────────────────────────────────────────────────────


def make_task(task_id: str, name: str = "", **overrides) -> dict:
    task = {
        "id": task_id,
        "name": name or task_id,
        "files": [],
        "verify": "",
        "depends_on": [],
        "review_profile": "none",
        "status": "pending",
    }
    task.update(overrides)
    return task


def make_plan(tasks: dict | list, parallel_groups: dict | None = None, **overrides) -> dict:
    plan = {
        "plan_id": "test-plan",
        "goal": "Test plan",
        "tasks": tasks,
        "parallel_groups": parallel_groups or {},
        "active": True,
    }
    plan.update(overrides)
    return plan


# ═══════════════════════════════════════════════════════════════════════════════
# run_peer_review — tasks as list, get_task with list, task_ids from list
# ═══════════════════════════════════════════════════════════════════════════════


class TestRunPeerReviewTasksAsList:
    """Coverage: run_peer_review() line 121 — tasks as a list."""

    def test_tasks_is_list_converted_to_dict(self):
        """When plan.tasks is a list, it's converted to dict."""
        from plan_follow.plan_peer_review import run_peer_review  # noqa: E402

        tasks_list = [
            make_task("t1", name="Task One"),
            make_task("t2", name="Task Two", depends_on=["t1"]),
        ]
        plan = make_plan(tasks_list)
        findings = run_peer_review(plan)
        assert isinstance(findings, list)


class TestRunPeerReviewGetTaskWithList:
    """Coverage: run_peer_review() lines 141-144 — get_task with list tasks."""

    def test_get_task_works_with_list_tasks(self):
        """get_task() iterates over list when tasks is a list."""
        from plan_follow.plan_peer_review import run_peer_review

        # A plan with parallel_groups referencing tasks — triggers get_task()
        tasks_list = [
            make_task("t1", files=["src/a.py"]),
            make_task("t2", files=["src/b.py"]),
        ]
        plan = make_plan(tasks_list, parallel_groups={"g1": {"tasks": ["t1", "t2"]}})
        findings = run_peer_review(plan)
        # Should work without crashing — parallel group with diff files = no findings
        assert isinstance(findings, list)

    def test_get_task_with_list_finds_by_id(self):
        """get_task correctly finds a task by id in list mode."""
        from plan_follow.plan_peer_review import run_peer_review

        tasks_list = [
            make_task("t1", files=["src/common.py"]),
            make_task("t2", files=["src/common.py"]),
        ]
        plan = make_plan(tasks_list, parallel_groups={"g1": {"tasks": ["t1", "t2"]}})
        findings = run_peer_review(plan)
        # Should detect file conflict
        conflict = [f for f in findings if f["check"] == "parallel_groups"]
        assert len(conflict) > 0


class TestRunPeerReviewTaskIdsFromList:
    """Coverage: run_peer_review() line 151 — task_ids set from list."""

    def test_task_ids_built_from_list(self):
        """task_ids is correctly built when tasks is a list."""
        from plan_follow.plan_peer_review import run_peer_review

        tasks_list = [
            make_task("a1", depends_on=["nonexistent"]),
        ]
        plan = make_plan(tasks_list)
        findings = run_peer_review(plan)
        # Should flag nonexistent dependency
        dep_findings = [f for f in findings if f["check"] == "depends_on"]
        assert any("nonexistent" in f.get("description", "") for f in dep_findings)


# ═══════════════════════════════════════════════════════════════════════════════
# run_peer_review — auto-detect exception paths
# ═══════════════════════════════════════════════════════════════════════════════


class TestRunPeerReviewAutoDetectExceptions:
    """Coverage: run_peer_review() lines 194-195, 212-213 — Exception in auto-detect."""

    def test_empty_verify_auto_detect_raises_exception(self):
        """When _auto_detect_project_defaults raises, fallback verify is used."""
        from plan_follow.plan_peer_review import run_peer_review

        task = make_task("t1", verify="")
        plan = make_plan({"t1": task})

        with patch("plan_follow.plan_templates._auto_detect_project_defaults",
                   side_effect=ImportError("no plan_templates module")):
            findings = run_peer_review(plan)

        verify_findings = [f for f in findings if f["check"] == "verify"]
        assert len(verify_findings) > 0
        # Should have fallback verify = python3 -m pytest
        fix = verify_findings[0].get("fix", {})
        assert fix.get("verify") == "python3 -m pytest"

    def test_meaningless_verify_auto_detect_raises_exception(self):
        """When verify is echo-only and auto-detect raises, fallback is used."""
        from plan_follow.plan_peer_review import run_peer_review

        task = make_task("t1", verify="echo 'done'")
        plan = make_plan({"t1": task})

        with patch("plan_follow.plan_templates._auto_detect_project_defaults",
                   side_effect=RuntimeError("unexpected")):
            findings = run_peer_review(plan)

        verify_findings = [f for f in findings if f["check"] == "verify"]
        assert len(verify_findings) > 0
        fix = verify_findings[0].get("fix", {})
        assert fix.get("verify") == "python3 -m pytest"


# ═══════════════════════════════════════════════════════════════════════════════
# run_peer_review — non-dict gdata in parallel_groups
# ═══════════════════════════════════════════════════════════════════════════════


class TestRunPeerReviewNonDictGdata:
    """Coverage: run_peer_review() line 302 — continue for non-dict gdata."""

    def test_non_dict_parallel_group_value_skipped(self):
        """A parallel_groups value that is not a dict is skipped gracefully."""
        from plan_follow.plan_peer_review import run_peer_review

        tasks_dict = {"t1": make_task("t1", files=["a.py"])}
        plan = make_plan(tasks_dict, parallel_groups={"g1": None})
        # Should not crash
        findings = run_peer_review(plan)
        assert isinstance(findings, list)

    def test_parallel_group_with_string_value_skipped(self):
        """A parallel_groups value that is a string is skipped gracefully."""
        from plan_follow.plan_peer_review import run_peer_review

        tasks_dict = {"t1": make_task("t1", files=["a.py"])}
        plan = make_plan(tasks_dict, parallel_groups={"g1": "not-a-dict"})
        findings = run_peer_review(plan)
        assert isinstance(findings, list)

    def test_parallel_group_with_single_task_skipped(self):
        """A parallel group with fewer than 2 tasks is skipped (line 304-305)."""
        from plan_follow.plan_peer_review import run_peer_review

        tasks_dict = {"t1": make_task("t1", files=["a.py"])}
        plan = make_plan(tasks_dict, parallel_groups={"g1": {"tasks": ["t1"]}})
        findings = run_peer_review(plan)
        parallel_findings = [f for f in findings if f["check"] == "parallel_groups"]
        assert len(parallel_findings) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# apply_findings — edge cases
# ═══════════════════════════════════════════════════════════════════════════════


class TestApplyFindingsEdgeCases:
    """Coverage: apply_findings() lines 352-353, 359, 363."""

    def test_tasks_as_list_normalized(self):
        """When plan.tasks is a list, apply_findings normalizes it to dict."""
        from plan_follow.plan_peer_review import apply_findings

        tasks_list = [make_task("t1", verify="echo 'done'")]
        plan = make_plan(tasks_list)
        findings = [{
            "task_id": "t1",
            "check": "verify",
            "severity": "critical",
            "fix": {"verify": "pytest"},
        }]
        updated = apply_findings(plan, findings)
        assert isinstance(updated["tasks"], dict)
        assert updated["tasks"]["t1"]["verify"] == "pytest"

    def test_finding_without_task_id_skipped(self):
        """A finding without task_id is skipped (line 359)."""
        from plan_follow.plan_peer_review import apply_findings

        tasks_dict = {"t1": make_task("t1", verify="echo 'done'")}
        plan = make_plan(tasks_dict)
        findings = [{
            "check": "verify",
            "severity": "critical",
            "fix": {"verify": "pytest"},
            # no task_id
        }]
        updated = apply_findings(plan, findings)
        assert updated["tasks"]["t1"]["verify"] == "echo 'done'"  # unchanged

    def test_finding_without_fix_skipped(self):
        """A finding without fix is skipped (line 359)."""
        from plan_follow.plan_peer_review import apply_findings

        tasks_dict = {"t1": make_task("t1", verify="echo 'done'")}
        plan = make_plan(tasks_dict)
        findings = [{
            "task_id": "t1",
            "check": "verify",
            "severity": "critical",
            # no fix
        }]
        updated = apply_findings(plan, findings)
        assert updated["tasks"]["t1"]["verify"] == "echo 'done'"  # unchanged

    def test_finding_for_nonexistent_task_skipped(self):
        """A finding for a task not in the plan is skipped (line 363)."""
        from plan_follow.plan_peer_review import apply_findings

        tasks_dict = {"t1": make_task("t1", verify="echo 'done'")}
        plan = make_plan(tasks_dict)
        findings = [{
            "task_id": "ghost",
            "check": "verify",
            "severity": "critical",
            "fix": {"verify": "pytest"},
        }]
        updated = apply_findings(plan, findings)
        assert "ghost" not in updated["tasks"]
        assert updated["tasks"]["t1"]["verify"] == "echo 'done'"  # unchanged

    def test_apply_fix_to_task(self):
        """A valid finding applies its fix to the task."""
        from plan_follow.plan_peer_review import apply_findings

        tasks_dict = {"t1": make_task("t1", verify="echo 'done'")}
        plan = make_plan(tasks_dict)
        findings = [{
            "task_id": "t1",
            "check": "verify",
            "severity": "critical",
            "fix": {"verify": "python3 -m pytest"},
        }]
        updated = apply_findings(plan, findings)
        assert updated["tasks"]["t1"]["verify"] == "python3 -m pytest"

    def test_empty_findings_list(self):
        """apply_findings with empty findings returns plan unchanged."""
        from plan_follow.plan_peer_review import apply_findings

        tasks_dict = {"t1": make_task("t1", verify="echo 'done'")}
        plan = make_plan(tasks_dict)
        updated = apply_findings(plan, [])
        assert updated["tasks"]["t1"]["verify"] == "echo 'done'"


# ═══════════════════════════════════════════════════════════════════════════════
# run_peer_review — OR_TRUE_PATTERN edge case (lines 236-243)
# ═══════════════════════════════════════════════════════════════════════════════


class TestOrTruePattern:
    """Coverage: run_peer_review() lines 236-243 — || true masking check."""

    def test_or_true_masking_flagged(self):
        """verify with '|| true' should flag as important."""
        from plan_follow.plan_peer_review import run_peer_review

        tasks_dict = {"t1": make_task("t1", verify="grep -q pattern file.x || true")}
        plan = make_plan(tasks_dict)
        findings = run_peer_review(plan)
        or_true = [f for f in findings if "|| true" in f.get("description", "")]
        assert len(or_true) > 0
        assert or_true[0]["severity"] == "important"
