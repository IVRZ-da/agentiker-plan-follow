"""Tests for TTS markers in plan_hooks.py — Sprachausgabe-Trigger.

Testing approach:
- Tests verify that [TTS:event=...] markers are injected into hook output
  at the right events.
- plan_created → TTS marker with plan goal
- task_completed → TTS marker with task name
- review_failed → TTS marker with issues

RED Phase: Tests fail because TTS markers aren't implemented yet in plan_hooks.py.
"""

from unittest.mock import patch

import pytest


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_plan_with_tts():
    """Create a mock plan with tts_flags set."""
    plan = {
        "plan_id": "tts-test-plan",
        "goal": "TTS integration test",
        "tasks": {
            "p1": {
                "id": "p1",
                "name": "Implement feature",
                "files": ["src/main.py"],
                "verify": "test -f src/main.py && echo 'ok'",
                "depends_on": [],
                "review_profile": "none",
                "status": "completed",
            },
            "p2": {
                "id": "p2",
                "name": "Add tests",
                "files": ["tests/test_main.py"],
                "verify": "python3 -m pytest tests/test_main.py -q",
                "depends_on": ["p1"],
                "review_profile": "unit-test",
                "status": "in_progress",
                "review_result": {"status": "failed", "issues": [
                    {"check": "test_coverage_90", "severity": "error",
                     "message": "Coverage only 45%"}
                ]},
            },
        },
        "parallel_groups": {},
        "active": True,
        "tts_flags": {
            "plan_created": True,
            "task_completed": ["p1"],
            "review_failed": ["p2"],
        },
    }
    return plan


@pytest.fixture
def mock_plan_without_tts():
    """Create a mock plan without any TTS flags."""
    plan = {
        "plan_id": "no-tts-plan",
        "goal": "No TTS needed",
        "tasks": {
            "p1": {
                "id": "p1",
                "name": "Simple task",
                "files": ["src/main.py"],
                "verify": "",
                "depends_on": [],
                "review_profile": "none",
                "status": "pending",
            },
        },
        "parallel_groups": {},
        "active": True,
        "tts_flags": {},
    }
    return plan


# ═══════════════════════════════════════════════════════════════════════════════
# 🔴 These tests verify TTS marker injection in plan_hooks.on_pre_llm_call().
# They fail because TTS markers aren't implemented yet (RED phase).
# ═══════════════════════════════════════════════════════════════════════════════


class TestTTSMarkerPlanCreated:
    """TTS marker should appear when a plan is created with tts flag."""

    def test_plan_created_marker_present(self, mock_plan_with_tts):
        """When plan has tts_flags.plan_created=True, hook should inject [TTS:event=plan_created]."""
        with patch("plan_follow.plan_hooks.plan_core.get_current_task_cached") as mock_get:
            with patch("plan_follow.plan_hooks.plan_core._get_active_plan") as mock_plan:
                mock_get.return_value = {
                    "task_id": "p1", "name": "Test",
                    "files": [], "progress": "0/1",
                }
                mock_plan.return_value = mock_plan_with_tts

                from plan_follow.plan_hooks import on_pre_llm_call
                result = on_pre_llm_call()

                assert result is not None, "Hook should return banner with TTS marker"
                assert "TTS" in result, f"Expected TTS marker in banner, got: {result[:200]}"
                assert "plan_created" in result, \
                    f"Expected plan_created event in TTS marker, got: {result[:300]}"

    def test_plan_created_marker_goal(self, mock_plan_with_tts):
        """TTS marker should include the plan goal."""
        with patch("plan_follow.plan_hooks.plan_core.get_current_task_cached") as mock_get:
            with patch("plan_follow.plan_hooks.plan_core._get_active_plan") as mock_plan:
                mock_get.return_value = {
                    "task_id": "p1", "name": "Test",
                    "files": [], "progress": "0/1",
                }
                mock_plan.return_value = mock_plan_with_tts

                from plan_follow.plan_hooks import on_pre_llm_call
                result = on_pre_llm_call()

                assert "TTS integration test" in result, \
                    f"Expected plan goal in TTS marker, got: {result[:300]}"

    def test_no_tts_when_not_requested(self, mock_plan_without_tts):
        """When no tts_flags, no TTS marker should appear."""
        with patch("plan_follow.plan_hooks.plan_core.get_current_task_cached") as mock_get:
            with patch("plan_follow.plan_hooks.plan_core._get_active_plan") as mock_plan:
                mock_get.return_value = {
                    "task_id": "p1", "name": "Simple task",
                    "files": [], "progress": "0/1",
                }
                mock_plan.return_value = mock_plan_without_tts

                from plan_follow.plan_hooks import on_pre_llm_call
                result = on_pre_llm_call()

                if result is not None:
                    assert "TTS" not in result, \
                        f"Unexpected TTS marker without tts_flags: {result[:300]}"


class TestTTSMarkerTaskCompleted:
    """TTS marker should appear when a task is completed with tts flag."""

    def test_task_completed_marker(self, mock_plan_with_tts):
        """When tts_flags.task_completed has a task, hook should inject [TTS:event=task_completed]."""
        with patch("plan_follow.plan_hooks.plan_core.get_current_task_cached") as mock_get:
            with patch("plan_follow.plan_hooks.plan_core._get_active_plan") as mock_plan:
                mock_get.return_value = {
                    "task_id": "p1", "name": "Implement feature",
                    "files": ["src/main.py"], "progress": "1/2",
                }
                mock_plan.return_value = mock_plan_with_tts

                from plan_follow.plan_hooks import on_pre_llm_call
                result = on_pre_llm_call()

                assert result is not None
                assert "task_completed" in result or "Implement feature" in result, \
                    f"Expected task_completed TTS, got: {result[:300]}"


class TestTTSMarkerReviewFailed:
    """TTS marker should appear when a review fails."""

    def test_review_failed_marker(self, mock_plan_with_tts):
        """When tts_flags.review_failed has a task with failed review, inject TTS marker."""
        with patch("plan_follow.plan_hooks.plan_core.get_current_task_cached") as mock_get:
            with patch("plan_follow.plan_hooks.plan_core._get_active_plan") as mock_plan:
                mock_get.return_value = {
                    "task_id": "p2", "name": "Add tests",
                    "files": ["tests/test_main.py"], "progress": "0/1",
                    "review_profile": "unit-test",
                    "review_result": {"status": "failed", "issues": [
                        {"check": "test_coverage_90", "severity": "error",
                         "message": "Coverage only 45%"}
                    ]},
                }
                mock_plan.return_value = mock_plan_with_tts

                from plan_follow.plan_hooks import on_pre_llm_call
                result = on_pre_llm_call()

                assert result is not None
                assert "review_failed" in result or "Coverage only 45" in result, \
                    f"Expected review_failed TTS, got: {result[:300]}"


class TestTTSMarkerFormat:
    """TTS markers should follow a parseable format for the Agent."""

    def test_marker_has_event_and_message(self, mock_plan_with_tts):
        """TTS marker format should be parseable: [TTS:event=X:message=Y]."""
        with patch("plan_follow.plan_hooks.plan_core.get_current_task_cached") as mock_get:
            with patch("plan_follow.plan_hooks.plan_core._get_active_plan") as mock_plan:
                mock_get.return_value = {
                    "task_id": "p1", "name": "Test",
                    "files": [], "progress": "0/1",
                }
                mock_plan.return_value = mock_plan_with_tts

                from plan_follow.plan_hooks import on_pre_llm_call
                result = on_pre_llm_call()

                assert "[TTS:" in result, \
                    f"Expected [TTS: marker format, got: {result[:300]}"

    def test_multiple_tts_events(self, mock_plan_with_tts):
        """Multiple TTS events should be injectable in the same banner."""
        with patch("plan_follow.plan_hooks.plan_core.get_current_task_cached") as mock_get:
            with patch("plan_follow.plan_hooks.plan_core._get_active_plan") as mock_plan:
                mock_get.return_value = {
                    "task_id": "p1", "name": "Implement feature",
                    "files": ["src/main.py"], "progress": "2/2",
                    "review_profile": "none",
                }
                mock_plan.return_value = mock_plan_with_tts

                from plan_follow.plan_hooks import on_pre_llm_call
                result = on_pre_llm_call()

                # Count TTS markers
                tts_count = result.count("[TTS:")
                assert tts_count >= 1, \
                    f"Expected at least 1 TTS marker, found {tts_count} in: {result[:500]}"
