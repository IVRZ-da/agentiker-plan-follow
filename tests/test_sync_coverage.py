"""Coverage gap tests for plan_sync.py — error paths and edge cases.

Tests cover uncovered lines:
- sync_to_github() — line 90: empty repo after auto-detection
- plan_sync_tool() — lines 304, 310–312, 317–321, 325, 330–340
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure the plugin package is on sys.path
_PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))

MODULE_PATH = "plan_follow.plan_sync"


# ─── Helpers ────────────────────────────────────────────────────────────────


def make_plan(**overrides) -> dict:
    plan = {
        "plan_id": "test-plan",
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
        },
    }
    plan.update(overrides)
    return plan


# ═══════════════════════════════════════════════════════════════════════════════
# sync_to_github — edge case: repo auto-detect yields empty
# ═══════════════════════════════════════════════════════════════════════════════


class TestSyncToGithubEdgeCases:
    """Coverage: sync_to_github() line 90 — empty repo after auto-detection."""

    def test_auto_detect_returns_non_github_url(self):
        """If git remote URL doesn't contain 'github.com', repo stays empty → error."""
        from plan_follow.plan_sync import sync_to_github  # noqa: E402

        plan = make_plan()

        with patch(f"{MODULE_PATH}._check_gh", return_value=True), \
             patch(f"{MODULE_PATH}.subprocess.run") as mock_subp:
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.stdout = "git@gitlab.com:owner/project.git\n"
            mock_proc.stderr = ""
            mock_subp.return_value = mock_proc

            result = sync_to_github(plan)

        assert result["success"] is False
        assert "repo is required" in result["error"]

    def test_auto_detect_returns_empty_string(self):
        """If git remote URL is empty string, repo stays empty → error."""
        from plan_follow.plan_sync import sync_to_github

        plan = make_plan()

        with patch(f"{MODULE_PATH}._check_gh", return_value=True), \
             patch(f"{MODULE_PATH}.subprocess.run") as mock_subp:
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.stdout = ""
            mock_proc.stderr = ""
            mock_subp.return_value = mock_proc

            result = sync_to_github(plan)

        assert result["success"] is False
        assert "repo is required" in result["error"]


# ═══════════════════════════════════════════════════════════════════════════════
# plan_sync_tool — edge cases and error paths
# ═══════════════════════════════════════════════════════════════════════════════


class TestPlanSyncToolEdgeCases:
    """Coverage: plan_sync_tool() lines 304, 310–312, 317–321, 325, 330–340."""

    def test_no_action(self):
        """Returns error when no action is provided."""
        from plan_follow.plan_sync import plan_sync_tool

        result = plan_sync_tool({})
        assert "error" in result or "action is required" in result

    def test_unknown_action(self):
        """Returns error for unknown action."""
        from plan_follow.plan_sync import plan_sync_tool

        result = plan_sync_tool({"action": "fly"})
        assert "error" in result or "Unknown action" in result

    def test_github_sync_with_no_plan(self):
        """Returns error when github action has no plan and no active plan."""
        from plan_follow.plan_sync import plan_sync_tool

        with patch("plan_follow.plan_core._get_active_plan", return_value=None):
            result = plan_sync_tool({"action": "github"})
        assert "error" in result or "No plan" in result

    def test_export_with_no_plan(self):
        """Returns error when export action has no plan available."""
        from plan_follow.plan_sync import plan_sync_tool

        with patch("plan_follow.plan_core._get_active_plan", return_value=None):
            result = plan_sync_tool({"action": "export"})
        assert "error" in result or "No plan" in result

    def test_import_missing_markdown(self):
        """Returns error when import action has no markdown content."""
        from plan_follow.plan_sync import plan_sync_tool

        result = plan_sync_tool({"action": "import"})
        assert "error" in result or "markdown content is required" in result

    def test_import_parse_failure(self):
        """Returns error when import cannot parse the markdown."""
        from plan_follow.plan_sync import plan_sync_tool

        result = plan_sync_tool({"action": "import", "markdown": "# Just a header\nno table here"})
        assert "error" in result or "Could not parse plan from markdown" in result

    def test_import_with_valid_markdown(self):
        """Successful import returns parsed plan info."""
        from plan_follow.plan_sync import plan_sync_tool

        md = (
            "| ID | Name | Status | Files | Review |\n"
            "|----|------|--------|-------|--------|\n"
            "| a1 | Task A | ⏳ pending |  | none |\n"
        )
        result = plan_sync_tool({"action": "import", "markdown": md})
        assert "error" not in result

    def test_plan_id_not_found(self):
        """Returns error when a specific plan_id is given but not found."""
        from plan_follow.plan_sync import plan_sync_tool

        with patch("plan_follow.plan_core._load_plan", return_value=None):
            result = plan_sync_tool({"action": "export", "plan_id": "nonexistent"})
        assert "error" in result or "not found" in result

    def test_github_with_explicit_plan_id(self):
        """github action with a valid plan_id works."""
        from plan_follow.plan_sync import plan_sync_tool

        plan = make_plan()
        with patch("plan_follow.plan_core._load_plan", return_value=plan), \
             patch(f"{MODULE_PATH}._check_gh", return_value=True), \
             patch(f"{MODULE_PATH}._run_gh", return_value={"success": True, "data": {"url": "http://example.com/1"}}):
            result = plan_sync_tool({"action": "github", "plan_id": "test-plan", "repo": "owner/repo"})
        assert "error" not in result

    def test_github_sync_task_failure(self):
        """github action when some individual issues fail."""
        from plan_follow.plan_sync import plan_sync_tool

        plan = make_plan()
        with patch("plan_follow.plan_core._get_active_plan", return_value=plan), \
             patch(f"{MODULE_PATH}._check_gh", return_value=True), \
             patch(f"{MODULE_PATH}._run_gh", return_value={"success": False, "error": "API error"}):
            result = plan_sync_tool({"action": "github", "repo": "owner/repo"})
        # The overall result is success; per-task errors appear in the data
        # fmt_ok wraps the full dict in JSON, so data-level "error" values are present
        assert '"success": true' in result  # overall tool reports success

    def test_export_success(self):
        """Successful export returns plan info with markdown."""
        from plan_follow.plan_sync import plan_sync_tool

        plan = make_plan()
        with patch("plan_follow.plan_core._get_active_plan", return_value=plan):
            result = plan_sync_tool({"action": "export"})
        assert "error" not in result
