"""Tests for plan_follow.plan_sync — External Sync (GitHub, Markdown).

Tests cover:
- sync_to_github — GitHub Issues sync via gh CLI
- export_to_markdown — Markdown export with correct structure
- import_from_markdown — Import from valid, invalid, and empty markdown
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# ─── Ensure the plugin package is on sys.path ──────────────────────────
_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent  # → plugins/
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))

# ---------------------------------------------------------------------------
# Module under test
# ---------------------------------------------------------------------------
MODULE_PATH = "plan_follow.plan_sync"

from plan_follow.plan_sync import (  # noqa: E402
    _check_gh,
    _run_gh,
    export_to_markdown,
    import_from_markdown,
    sync_to_github,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_plan(**overrides) -> dict:
    """Create a minimal plan dict for test use."""
    plan = {
        "plan_id": "test",
        "goal": "Test Goal",
        "created": "2026-06-23T12:00:00",
        "current_task": None,
        "parallel_groups": {},
        "tasks": {
            "t1": {
                "id": "t1",
                "name": "T1",
                "files": ["src/main.py"],
                "verify": "echo ok",
                "review_profile": "none",
                "status": "pending",
            },
            "t2": {
                "id": "t2",
                "name": "T2",
                "files": ["src/lib.py"],
                "verify": "",
                "review_profile": "peer",
                "status": "completed",
            },
        },
    }
    plan.update(overrides)
    return plan


def make_empty_plan(**overrides) -> dict:
    """Create a plan with no tasks for edge-case tests."""
    plan = {
        "plan_id": "empty",
        "goal": "Empty Plan",
        "created": "2026-06-23T12:00:00",
        "current_task": None,
        "parallel_groups": {},
        "tasks": {},
    }
    plan.update(overrides)
    return plan


# ---------------------------------------------------------------------------
# _check_gh — GitHub CLI availability check
# ---------------------------------------------------------------------------


class TestCheckGh:
    def test_gh_available(self):
        """_check_gh returns True when gh is installed."""
        with patch(f"{MODULE_PATH}.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            # Reset the module-level cache
            import plan_follow.plan_sync as ps

            ps._GH_AVAILABLE = None
            assert _check_gh() is True

    def test_gh_not_found(self):
        """_check_gh returns False when gh is not installed."""
        with patch(f"{MODULE_PATH}.subprocess.run", side_effect=FileNotFoundError):
            import plan_follow.plan_sync as ps

            ps._GH_AVAILABLE = None
            assert _check_gh() is False

    def test_gh_timeout(self):
        """_check_gh returns False when gh times out."""
        with patch(
            f"{MODULE_PATH}.subprocess.run", side_effect=subprocess.TimeoutExpired("gh", 5)
        ):
            import plan_follow.plan_sync as ps

            ps._GH_AVAILABLE = None
            assert _check_gh() is False

    def test_result_cached(self):
        """_check_gh caches the result and does not call subprocess again."""
        import plan_follow.plan_sync as ps

        ps._GH_AVAILABLE = None
        with patch(f"{MODULE_PATH}.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            _check_gh()
            mock_run.assert_called_once()

        # Second call should use cache, no extra subprocess call
        with patch(f"{MODULE_PATH}.subprocess.run") as mock_run:
            _check_gh()
            mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# _run_gh — low-level gh CLI runner
# ---------------------------------------------------------------------------


class TestRunGh:
    def test_success_with_json_output(self):
        """_run_gh parses stdout JSON successfully."""
        with patch(f"{MODULE_PATH}.subprocess.run") as mock_run:
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.stdout = '{"url": "https://github.com/issue/1"}'
            mock_proc.stderr = ""
            mock_run.return_value = mock_proc

            result = _run_gh(["issue", "create", "--title", "test"])
            assert result["success"] is True
            assert result["data"]["url"] == "https://github.com/issue/1"

    def test_success_no_output(self):
        """_run_gh returns success with None data when stdout is empty."""
        with patch(f"{MODULE_PATH}.subprocess.run") as mock_run:
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.stdout = ""
            mock_proc.stderr = ""
            mock_run.return_value = mock_proc

            result = _run_gh(["issue", "list"])
            assert result["success"] is True
            assert result["data"] is None

    def test_nonzero_returncode(self):
        """_run_gh returns error dict when gh exits non-zero."""
        with patch(f"{MODULE_PATH}.subprocess.run") as mock_run:
            mock_proc = MagicMock()
            mock_proc.returncode = 1
            mock_proc.stdout = ""
            mock_proc.stderr = "error: not authenticated"
            mock_run.return_value = mock_proc

            result = _run_gh(["issue", "create"])
            assert result["success"] is False
            assert "not authenticated" in result["error"]

    def test_file_not_found(self):
        """_run_gh returns error when gh binary missing."""
        with patch(f"{MODULE_PATH}.subprocess.run", side_effect=FileNotFoundError):
            result = _run_gh(["issue", "create"])
            assert result["success"] is False
            assert "not found" in result["error"].lower()

    def test_timeout(self):
        """_run_gh returns error on subprocess timeout."""
        with patch(
            f"{MODULE_PATH}.subprocess.run", side_effect=subprocess.TimeoutExpired("gh", 30)
        ):
            result = _run_gh(["issue", "create"])
            assert result["success"] is False
            assert "timed out" in result["error"].lower()

    def test_json_decode_error(self):
        """_run_gh returns error on invalid JSON in stdout."""
        with patch(f"{MODULE_PATH}.subprocess.run") as mock_run:
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.stdout = "not-json-at-all{{{"
            mock_proc.stderr = ""
            mock_run.return_value = mock_proc

            result = _run_gh(["issue", "create"])
            assert result["success"] is False
            assert "JSON" in result["error"]


# ---------------------------------------------------------------------------
# sync_to_github — GitHub Issues Sync
# ---------------------------------------------------------------------------


class TestSyncToGithub:
    def test_gh_not_available(self):
        """sync_to_github returns error when gh CLI is not available."""
        plan = make_plan()
        # Simulate _check_gh returning False by patching it
        with patch(f"{MODULE_PATH}._check_gh", return_value=False):
            result = sync_to_github(plan, repo="owner/repo")
        assert result["success"] is False
        assert "not available" in result["error"]

    def test_creates_issues_for_all_tasks(self):
        """sync_to_github creates a GitHub issue for each task."""
        plan = make_plan()

        with patch(f"{MODULE_PATH}._check_gh", return_value=True), patch(
            f"{MODULE_PATH}._run_gh"
        ) as mock_run_gh:
            mock_run_gh.return_value = {
                "success": True,
                "data": {"url": "https://github.com/owner/repo/issues/1"},
            }

            result = sync_to_github(plan, repo="owner/repo")

        assert result["success"] is True
        assert result["repo"] == "owner/repo"
        assert result["plan_id"] == "test"
        assert result["created"] == 2
        assert result["failed"] == 0
        assert len(result["results"]) == 2
        assert mock_run_gh.call_count == 2

        # Verify the gh command arguments for first task
        call_args = mock_run_gh.call_args_list[0][0][0]
        assert "--repo" in call_args
        assert "owner/repo" in call_args
        assert "--title" in call_args
        assert "[Plan] T1 (test)" in call_args or any("[Plan]" in a for a in call_args)
        assert "--label" in call_args
        assert "plan-follow" in call_args

    def test_partial_failures(self):
        """sync_to_github reports per-task errors when some issues fail."""
        plan = make_plan()

        with patch(f"{MODULE_PATH}._check_gh", return_value=True), patch(
            f"{MODULE_PATH}._run_gh"
        ) as mock_run_gh:
            # First task succeeds, second fails
            mock_run_gh.side_effect = [
                {"success": True, "data": {"url": "https://github.com/owner/repo/issues/1"}},
                {"success": False, "error": "rate limit exceeded"},
            ]

            result = sync_to_github(plan, repo="owner/repo")

        assert result["success"] is True
        assert result["created"] == 1
        assert result["failed"] == 1
        assert result["results"][0]["status"] == "created"
        assert result["results"][1]["status"] == "error"
        assert "rate limit" in result["results"][1]["error"]

    def test_auto_detect_repo(self):
        """sync_to_github auto-detects repo from git remote."""
        plan = make_plan()

        with patch(f"{MODULE_PATH}._check_gh", return_value=True), patch(
            f"{MODULE_PATH}.subprocess.run"
        ) as mock_subp, patch(f"{MODULE_PATH}._run_gh") as mock_run_gh:
            # Mock git remote get-url origin
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.stdout = "git@github.com:owner/my-repo.git\n"
            mock_proc.stderr = ""
            # First subprocess call is git remote, rest are gh issues
            mock_subp.return_value = mock_proc
            mock_run_gh.return_value = {
                "success": True,
                "data": {"url": "https://github.com/owner/my-repo/issues/1"},
            }

            result = sync_to_github(plan)

        assert result["success"] is True
        assert result["repo"] == "owner/my-repo"

    def test_auto_detect_fails(self):
        """sync_to_github returns error when repo auto-detection fails."""
        plan = make_plan()

        with patch(f"{MODULE_PATH}._check_gh", return_value=True), patch(
            f"{MODULE_PATH}.subprocess.run", side_effect=FileNotFoundError
        ):
            result = sync_to_github(plan)

        assert result["success"] is False
        assert "repo" in result["error"].lower() or "detect" in result["error"].lower()

    def test_empty_task_list(self):
        """sync_to_github handles empty task list gracefully."""
        plan = make_empty_plan()

        with patch(f"{MODULE_PATH}._check_gh", return_value=True), patch(
            f"{MODULE_PATH}._run_gh"
        ) as mock_run_gh:
            result = sync_to_github(plan, repo="owner/repo")

        assert result["success"] is True
        assert result["created"] == 0
        assert result["failed"] == 0
        assert result["results"] == []
        mock_run_gh.assert_not_called()

    def test_custom_prefix(self):
        """sync_to_github uses the provided prefix for issue titles."""
        plan = make_plan()

        with patch(f"{MODULE_PATH}._check_gh", return_value=True), patch(
            f"{MODULE_PATH}._run_gh"
        ) as mock_run_gh:
            mock_run_gh.return_value = {"success": True, "data": {"url": "http://example.com/1"}}

            sync_to_github(plan, repo="owner/repo", prefix="[CUSTOM] ")

            title_arg = mock_run_gh.call_args[0][0]
            # Find the --title and its value
            title_idx = title_arg.index("--title")
            assert "[CUSTOM]" in title_arg[title_idx + 1]


# ---------------------------------------------------------------------------
# export_to_markdown — Markdown Export
# ---------------------------------------------------------------------------


class TestExportToMarkdown:
    def test_contains_plan_goal(self):
        """Exported markdown contains the plan goal as H1."""
        plan = make_plan()
        md = export_to_markdown(plan)
        assert "# Test Goal" in md
        assert "**Plan ID:** `test`" in md

    def test_contains_task_table(self):
        """Exported markdown contains the ## Tasks section with a table."""
        plan = make_plan()
        md = export_to_markdown(plan)
        assert "## Tasks" in md
        assert "| ID | Name | Status | Files | Review |" in md
        assert "| t1 |" in md
        assert "| t2 |" in md

    def test_contains_status_summary(self):
        """Exported markdown contains a ## Status section with counts."""
        plan = make_plan()
        md = export_to_markdown(plan)
        assert "## Status" in md
        assert "pending" in md
        assert "completed" in md

    def test_current_task_section(self):
        """Current task is rendered with its own section."""
        plan = make_plan()
        plan["current_task"] = "t1"
        md = export_to_markdown(plan)
        assert "## Current Task: T1" in md
        assert "**Files:** `src/main.py`" in md
        assert "**Verify:** `echo ok`" in md

    def test_no_current_task(self):
        """No Current Task section when current_task is None."""
        plan = make_plan()
        plan["current_task"] = None
        md = export_to_markdown(plan)
        assert "## Current Task:" not in md

    def test_parallel_groups_included(self):
        """Parallel groups are rendered when present."""
        plan = make_plan()
        plan["parallel_groups"] = {
            "g1": {"tasks": ["t1", "t2"], "status": "pending"},
        }
        md = export_to_markdown(plan)
        assert "## Parallel Groups" in md
        assert "g1" in md

    def test_empty_plan(self):
        """Exporting an empty tasks dict produces valid markdown."""
        plan = make_empty_plan()
        md = export_to_markdown(plan)
        assert "# Empty Plan" in md
        assert "## Tasks" in md
        # Table header should exist even with no rows
        assert "| ID | Name | Status | Files | Review |" in md

    def test_return_type_is_string(self):
        """export_to_markdown always returns a string."""
        plan = make_plan()
        md = export_to_markdown(plan)
        assert isinstance(md, str)
        assert len(md) > 0

    def test_default_goal_when_missing(self):
        """export_to_markdown uses 'Untitled Plan' when goal is missing."""
        plan = make_plan()
        del plan["goal"]
        md = export_to_markdown(plan)
        assert "# Untitled Plan" in md


# ---------------------------------------------------------------------------
# import_from_markdown — Markdown Import
# ---------------------------------------------------------------------------


class TestImportFromMarkdown:
    VALID_MD = """# API Refactoring

**Plan ID:** `plan_001`
**Created:** 2026-06-23
**Tasks:** 3

## Status

- ⏳ **pending**: 2
- ✅ **completed**: 1

## Tasks

| ID | Name | Status | Files | Review |
|----|------|--------|-------|--------|
| t1 | Setup | ⏳ pending |  | none |
| t2 | Implement | ✅ completed |  | peer |
| t3 | Test | ⏳ pending |  | none |
"""

    def test_import_valid(self):
        """Parse valid markdown into a proper plan dict."""
        plan = import_from_markdown(self.VALID_MD)
        assert plan is not None
        assert plan["goal"] == "API Refactoring"
        assert "plan_id" in plan
        assert "created" in plan
        assert "tasks" in plan
        assert len(plan["tasks"]) == 3

    def test_task_details(self):
        """Each imported task has the correct fields."""
        plan = import_from_markdown(self.VALID_MD)
        t1 = plan["tasks"]["t1"]
        assert t1["id"] == "t1"
        assert t1["name"] == "Setup"
        assert t1["status"] == "pending"
        assert t1["files"] == []
        assert t1["verify"] == ""
        assert t1["review_profile"] == "none"

    def test_completed_status(self):
        """Completed tasks get 'completed' status."""
        plan = import_from_markdown(self.VALID_MD)
        assert plan["tasks"]["t2"]["status"] == "completed"

    def test_invalid_markdown(self):
        """Invalid markdown (no task table) returns None."""
        invalid = "# Hello\\n\\nThis has no task table."
        result = import_from_markdown(invalid)
        assert result is None

    def test_empty_string(self):
        """Empty string returns None."""
        result = import_from_markdown("")
        assert result is None

    def test_whitespace_only(self):
        """Whitespace-only string returns None."""
        result = import_from_markdown("   \\n\\n  \\n")
        assert result is None

    def test_no_tasks_table(self):
        """Markdown with H1 but no table still returns None."""
        md = "# Just a Title\\n\\nNo table here."
        result = import_from_markdown(md)
        assert result is None

    def test_table_without_h1(self):
        """Markdown with a table but no H1 still returns a parsed plan."""
        md = """| ID | Name | Status | Files | Review |
|----|------|--------|-------|--------|
| x1 | Orphan | ⏳ pending |  | none |
"""
        result = import_from_markdown(md)
        assert result is not None
        assert result["goal"] == "Imported Plan"
        assert "x1" in result["tasks"]

    def test_roundtrip_preserves_structure(self):
        """Export then import should recover the same tasks."""
        original = make_plan()
        md = export_to_markdown(original)
        recovered = import_from_markdown(md)

        assert recovered is not None
        # The importer creates a new plan_id, so compare tasks
        assert len(recovered["tasks"]) == len(original["tasks"])
        for tid in original["tasks"]:
            assert tid in recovered["tasks"]
            assert recovered["tasks"][tid]["name"] == original["tasks"][tid]["name"]
            assert recovered["tasks"][tid]["status"] == original["tasks"][tid]["status"]

    def test_unknown_status_icon(self):
        """An unknown status icon results in 'pending' fallback."""
        md = """| ID | Name | Status | Files | Review |
|----|------|--------|-------|--------|
| u1 | Unknown | ✅ weird |  | none |
"""
        result = import_from_markdown(md)
        assert result is not None
        # "weird" doesn't match any known status -> pending
        assert result["tasks"]["u1"]["status"] == "pending"

    def test_alternate_status_texts(self):
        """Alternate status texts (done, active) are mapped correctly."""
        md = """| ID | Name | Status | Files | Review |
|----|------|--------|-------|--------|
| a1 | Done Task | ✅ done |  | none |
| a2 | Active Task | ▶️ active |  | none |
| a3 | Blocked Task | ⏳ blocked |  | none |
| a4 | Aborted Task | ⛔ aborted |  | none |
"""
        result = import_from_markdown(md)
        assert result is not None
        assert result["tasks"]["a1"]["status"] == "completed"
        assert result["tasks"]["a2"]["status"] == "in_progress"
        assert result["tasks"]["a3"]["status"] == "blocked"
        assert result["tasks"]["a4"]["status"] == "aborted"
