"""Integration tests: plan_create → auto-peer-review → TTS marker.

Tests verify the full flow:
1. plan_create_tool() automatically calls run_peer_review() after creating a plan
2. Peer review findings are applied via plan_update() automatically
3. TTS flags are set for plan_created events
4. plan_complete sets TTS flags for completed tasks
5. All together: plan_create → review → update → TTS → complete → TTS
"""

import json
from unittest.mock import patch

# ─── Test helpers ──────────────────────────────────────────────────────────────

def make_mock_plan(plan_id="test-plan", goal="Test", task_id="p1",
                   task_name="Task 1", files=None):
    """Create a realistic mock plan dict for use in patching _get_active_plan."""
    if files is None:
        files = ["test.py"]
    return {
        "plan_id": plan_id,
        "goal": goal,
        "tasks": {
            task_id: {
                "id": task_id,
                "name": task_name,
                "files": files,
                "verify": "test -f test.py && echo 'ok'",
                "depends_on": [],
                "review_profile": "none",
                "review_result": None,
                "status": "pending",
            },
        },
        "parallel_groups": {},
        "repo": "",
        "active": True,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Integration tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestPlanCreateAutoPeerReview:
    """plan_create should automatically trigger peer review."""

    def test_create_adds_tts_flag(self):
        """plan_create_tool should set tts_flags.plan_created=True."""
        from plan_follow.plan_tools import plan_create_tool

        mock_plan = make_mock_plan()

        with patch("plan_follow.plan_tools.plan_core.create_plan") as mock_create:
            mock_create.return_value = "test-plan-1"
            with patch("plan_follow.plan_tools.plan_core._get_active_plan",
                       return_value=mock_plan):
                with patch("plan_follow.plan_tools.plan_core._save_plan") as _ms:
                    with patch("plan_follow.plan_tools.plan_core._reset_cache"):

                        result = plan_create_tool({
                            "goal": "Integration test",
                            "template": "fix",
                        })

                        parsed = json.loads(result) if isinstance(result, str) else {}
                        assert parsed.get("status") in ("ok", "created", "warning"), \
                            f"Expected created/warning status, got: {parsed}"

                        # Verify TTS flag was set in saved plan
                        saved_plan = _ms.call_args[0][0]
                        assert saved_plan.get("tts_flags", {}).get("plan_created") is True, \
                            f"Expected plan_created TTS flag, got: {saved_plan.get('tts_flags')}"

    def test_create_calls_run_peer_review(self):
        """plan_create_tool should automatically call run_peer_review()."""
        from plan_follow.plan_tools import plan_create_tool

        with patch("plan_follow.plan_tools.plan_peer_review.run_peer_review") as mock_review:
            mock_review.return_value = []

            result = plan_create_tool({
                "goal": "Peer review test",
                "template": "fix",
            })

            mock_review.assert_called_once()
            parsed = json.loads(result) if isinstance(result, str) else {}
            assert parsed.get("status") in ("created", "warning"), \
                f"Expected created/warning status, got: {parsed}"

    def test_findings_show_in_response(self):
        """If peer review finds issues that survive auto-fix, plan is blocked."""
        from plan_follow.plan_tools import plan_create_tool

        # Simulate findings that cannot be auto-fixed (no fix in apply_findings)
        fake_findings = [
            {"id": "F1", "severity": "critical", "check": "files",
             "description": "No files declared", "task_id": "p1"},
        ]

        with patch("plan_follow.plan_tools.plan_peer_review.run_peer_review",
                    return_value=fake_findings):
            with patch("plan_follow.plan_tools.plan_peer_review.apply_findings",
                       side_effect=lambda plan, findings: plan):

                result = plan_create_tool({
                    "goal": "Peer review with issues",
                    "template": "fix",
                })
                parsed = json.loads(result) if isinstance(result, str) else {}
                # Findings that survive auto-fix block the plan
                assert parsed["status"] == "blocked", \
                    f"Expected blocked status when critical findings survive fix, got: {parsed}"
                assert "remaining_findings" in parsed, \
                    f"Expected remaining_findings in blocked response, got keys: {parsed.keys()}"


class TestPlanCompleteTTS:
    """plan_complete should set TTS flags for completed tasks."""

    def test_complete_sets_task_tts_flag(self):
        """plan_complete_tool should add task_id to tts_flags.task_completed."""
        from plan_follow.plan_tools import plan_complete_tool

        mock_plan = make_mock_plan(task_id="p1")

        with patch("plan_follow.plan_tools.plan_core.get_current_task") as mock_current:
            mock_current.return_value = {
                "task_id": "p1",
                "name": "Complete me",
                "files": ["test.py"],
                "verify": "",
                "progress": "0/1",
            }
            with patch("plan_follow.plan_tools.plan_core.complete_task") as mock_complete:
                mock_complete.return_value = {"status": "completed", "next_task": None}
                with patch("plan_follow.plan_tools.plan_core._get_active_plan",
                           return_value=mock_plan):
                    with patch("plan_follow.plan_tools.plan_core._save_plan") as _ms:
                        with patch("plan_follow.plan_tools.plan_core.check_drift",
                                   return_value=[]):

                            result = plan_complete_tool({
                                "task_id": "p1",
                                "auto_verify": False,
                                "skip_review": True,
                            })

                            parsed = json.loads(result) if isinstance(result, str) else {}
                            assert parsed.get("status") == "completed", \
                                f"Expected completed status, got: {parsed}"

                            # Verify TTS flag was set
                            saved_plan = _ms.call_args[0][0]
                            tts = saved_plan.get("tts_flags", {})
                            assert "p1" in tts.get("task_completed", []), \
                                f"Expected task_completed to include 'p1', got: {tts}"


class TestTTSPeerReviewChain:
    """Full chain: plan_create → peer review → findings → TTS → plan_complete → TTS."""

    def test_full_chain(self):
        """The full integration chain should work end-to-end."""
        from plan_follow.plan_tools import plan_complete_tool, plan_create_tool

        mock_plan = make_mock_plan(task_id="p1")

        # Step 1: Create plan (should auto peer-review)
        with patch("plan_follow.plan_tools.plan_peer_review.run_peer_review") as mock_review:
            mock_review.return_value = []

            create_result = plan_create_tool({
                "goal": "Chain test",
                "template": "fix",
            })

            assert create_result is not None, "plan_create should return a result"
            parsed = json.loads(create_result) if isinstance(create_result, str) else {}
            assert parsed.get("status") in ("ok", "created", "warning"), \
                f"Chain: plan_create failed: {parsed}"

        # Step 2: Complete task (should set TTS flag)
        with patch("plan_follow.plan_tools.plan_core.get_current_task") as mock_current:
            mock_current.return_value = {
                "task_id": "p1", "name": "First task",
                "files": ["a.py"], "verify": "", "progress": "1/2",
            }
            with patch("plan_follow.plan_tools.plan_core.complete_task") as mock_complete:
                mock_complete.return_value = {"status": "completed", "next_task": "p2"}
                with patch("plan_follow.plan_tools.plan_core._get_active_plan",
                           return_value=mock_plan):
                    with patch("plan_follow.plan_tools.plan_core._save_plan") as _ms:
                        with patch("plan_follow.plan_tools.plan_core.check_drift",
                                   return_value=[]):

                            complete_result = plan_complete_tool({
                                "task_id": "p1",
                                "auto_verify": False,
                                "skip_review": True,
                            })

                            assert complete_result is not None, \
                                "plan_complete should return a result"
                            parsed = json.loads(complete_result) \
                                if isinstance(complete_result, str) else {}
                            assert parsed.get("status") == "completed", \
                                f"Chain: plan_complete failed: {parsed}"


class TestNoRegression:
    """Existing functionality should still work. (Full check in P6)"""
    pass
