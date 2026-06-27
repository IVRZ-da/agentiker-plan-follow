"""Tests for plan_hooks.py uncovered lines — push coverage to 90%.

Targets:
  Line 305: my_locks > 2  → "... und N weitere"
  Lines 367–394: Repo conflict section
  Lines 558–559: _do_coordination_housekeeping exception in on_pre_llm_call
  Lines 639–681: Cross-session terminal warning in on_post_tool_call
  Lines 734–735: coord_state.send_notification exception in lock enforcement
  Lines 790–792: lock release at session end (released > 0)
  Lines 802–803: unregister session exception in on_session_end
  Lines 815–819: log finalize exception + outer exception in on_session_end
"""

import json
import logging
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# ─── Helpers (mirrored from test_hooks.py) ───────────────────────────────────


def _make_current(**overrides) -> dict:
    base = {
        "task_id": "T001",
        "name": "Test Task",
        "files": ["/workspace/src/main.py"],
        "progress": "in_progress",
        "review_profile": "none",
    }
    base.update(overrides)
    return base


def _make_plan(**overrides) -> dict:
    base = {
        "id": "plan-001",
        "name": "Test Plan",
        "goal": "Test goal",
        "tasks": {},
        "repo": "/workspace",
        "repos": ["/workspace"],
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def reset_hooks_state():
    """Reset module-level caches before each test."""
    import plan_follow.plan_hooks as ph  # noqa: E402
    ph._hook_cache.clear()
    ph._breaker_state.clear()


@pytest.fixture
def mock_time(monkeypatch):
    """Control time.monotonic for deterministic tests."""
    fake_time = [1000.0]
    def _monotonic():
        return fake_time[0]
    monkeypatch.setattr(time, "monotonic", _monotonic)
    return fake_time


# ═══════════════════════════════════════════════════════════════════════════════
# Line 305 — my_locks > 2 in _build_coordination_banner
# ═══════════════════════════════════════════════════════════════════════════════

class TestCoordBannerMyLocksTruncated:
    """Target line 305: my_locks > 2 → '... und N weitere'."""

    def test_my_locks_truncated(self, monkeypatch, mock_time):
        """More than 2 own locks should show truncation line."""
        import plan_follow.coord_state as cs
        from plan_follow.plan_hooks import _build_coordination_banner

        my_sid = "session-mine"
        # 4 locks for "my" session
        locks = {
            f"/workspace/src/file{i}.py": {
                "session_id": my_sid,
                "since": "2024-01-01T00:00:00",
            }
            for i in range(4)
        }

        monkeypatch.setattr(cs, "get_sessions", lambda: {})
        monkeypatch.setattr(cs, "get_locks", lambda: locks)
        monkeypatch.setattr(cs, "get_notifications", lambda *a, **kw: [])
        monkeypatch.setattr(cs, "cleanup_stale_sessions", lambda *a, **kw: None)
        monkeypatch.setattr(cs, "cleanup_stale_locks", lambda *a, **kw: None)
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: None,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_session_id",
            lambda: my_sid,
        )

        lines = _build_coordination_banner()
        text = "\n".join(lines)
        assert "Eigene Locks" in text
        assert "und 2 weitere" in text or "und 2 mehr" in text


# ═══════════════════════════════════════════════════════════════════════════════
# Lines 367–394 — Repo-Konflikt section in _build_coordination_banner
# ═══════════════════════════════════════════════════════════════════════════════

class TestCoordBannerRepoConflict:
    """Target lines 367–394: repo conflict with other sessions."""

    def test_repo_conflict(self, monkeypatch, mock_time, tmp_path):
        """Other session with same repo should trigger repo conflict warning."""
        import plan_follow.coord_state as cs
        from plan_follow.plan_hooks import _build_coordination_banner

        my_sid = "session-mine"

        # Create a fake plan file for the other session's plan
        other_plan_id = "other-plan-001"
        other_plan_data = {
            "plan_id": other_plan_id,
            "repos": ["/workspace"],  # same repo as ours
        }
        other_plan_file = tmp_path / f"{other_plan_id}.json"
        other_plan_file.write_text(json.dumps(other_plan_data))

        monkeypatch.setattr(cs, "get_sessions", lambda: {
            my_sid: {"plan_id": "my-plan", "last_seen": "2024-01-01T12:00:00"},
            "session-other": {"plan_id": other_plan_id, "last_seen": "2024-01-01T12:00:00"},
        })
        monkeypatch.setattr(cs, "get_locks", lambda: {})
        monkeypatch.setattr(cs, "get_notifications", lambda *a, **kw: [])
        monkeypatch.setattr(cs, "cleanup_stale_sessions", lambda *a, **kw: None)
        monkeypatch.setattr(cs, "cleanup_stale_locks", lambda *a, **kw: None)
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: _make_current(),
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_session_id",
            lambda: my_sid,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_active_plan",
            lambda: _make_plan(repos=["/workspace"]),
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_repos",
            lambda p: ["/workspace"],
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.PLANS_DIR",
            tmp_path,
        )

        lines = _build_coordination_banner()
        text = "\n".join(lines)
        assert "Repo-Konflikt" in text

    def test_repo_conflict_with_string_repo(self, monkeypatch, mock_time, tmp_path):
        """Other session plan has 'repo' as string (not list)."""
        import plan_follow.coord_state as cs
        from plan_follow.plan_hooks import _build_coordination_banner

        my_sid = "session-mine"
        other_plan_id = "other-plan-002"
        other_plan_data = {
            "plan_id": other_plan_id,
            "repo": "/workspace",  # string, not list
        }
        other_plan_file = tmp_path / f"{other_plan_id}.json"
        other_plan_file.write_text(json.dumps(other_plan_data))

        monkeypatch.setattr(cs, "get_sessions", lambda: {
            my_sid: {"plan_id": "my-plan", "last_seen": "2024-01-01T12:00:00"},
            "session-other": {"plan_id": other_plan_id, "last_seen": "2024-01-01T12:00:00"},
        })
        monkeypatch.setattr(cs, "get_locks", lambda: {})
        monkeypatch.setattr(cs, "get_notifications", lambda *a, **kw: [])
        monkeypatch.setattr(cs, "cleanup_stale_sessions", lambda *a, **kw: None)
        monkeypatch.setattr(cs, "cleanup_stale_locks", lambda *a, **kw: None)
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: _make_current(),
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_session_id",
            lambda: my_sid,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_active_plan",
            lambda: _make_plan(repos=["/workspace"]),
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_repos",
            lambda p: ["/workspace"],
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.PLANS_DIR",
            tmp_path,
        )

        lines = _build_coordination_banner()
        text = "\n".join(lines)
        assert "Repo-Konflikt" in text

    def test_repo_conflict_skipped_no_plan(self, monkeypatch, mock_time):
        """Skipped when no active plan."""
        import plan_follow.coord_state as cs
        from plan_follow.plan_hooks import _build_coordination_banner

        monkeypatch.setattr(cs, "get_sessions", lambda: {
            "s1": {"plan_id": "p1", "last_seen": "2024-01-01T12:00:00"},
            "s2": {"plan_id": "p2", "last_seen": "2024-01-01T12:00:00"},
        })
        monkeypatch.setattr(cs, "get_locks", lambda: {})
        monkeypatch.setattr(cs, "get_notifications", lambda *a, **kw: [])
        monkeypatch.setattr(cs, "cleanup_stale_sessions", lambda *a, **kw: None)
        monkeypatch.setattr(cs, "cleanup_stale_locks", lambda *a, **kw: None)
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: _make_current(),
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_session_id",
            lambda: "session-mine",
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_active_plan",
            lambda: None,  # no active plan
        )

        lines = _build_coordination_banner()
        # Should not crash, just returns whatever it gathered
        assert isinstance(lines, list)

    def test_repo_conflict_skipped_empty_repos(self, monkeypatch, mock_time):
        """Skipped when our plan has no repos."""
        import plan_follow.coord_state as cs
        from plan_follow.plan_hooks import _build_coordination_banner

        monkeypatch.setattr(cs, "get_sessions", lambda: {
            "s1": {"plan_id": "p1", "last_seen": "2024-01-01T12:00:00"},
            "s2": {"plan_id": "p2", "last_seen": "2024-01-01T12:00:00"},
        })
        monkeypatch.setattr(cs, "get_locks", lambda: {})
        monkeypatch.setattr(cs, "get_notifications", lambda *a, **kw: [])
        monkeypatch.setattr(cs, "cleanup_stale_sessions", lambda *a, **kw: None)
        monkeypatch.setattr(cs, "cleanup_stale_locks", lambda *a, **kw: None)
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: _make_current(),
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_session_id",
            lambda: "session-mine",
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_active_plan",
            lambda: _make_plan(),
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_repos",
            lambda p: [],  # empty repos
        )

        lines = _build_coordination_banner()
        assert isinstance(lines, list)


# ═══════════════════════════════════════════════════════════════════════════════
# Lines 558–559 — _do_coordination_housekeeping exception in on_pre_llm_call
# ═══════════════════════════════════════════════════════════════════════════════

class TestOnPreLLMCallHousekeepingException:
    """Target lines 558–559: housekeeping exception caught by pass."""

    def test_housekeeping_exception_passed(self, monkeypatch, mock_time):
        """on_pre_llm_call should not crash when housekeeping raises."""
        from plan_follow.plan_hooks import on_pre_llm_call

        current = _make_current(review_profile="none")
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: current,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_active_plan",
            lambda: _make_plan(),
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_repos",
            lambda p: [],
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.check_drift",
            lambda: [],
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_drift_warnings",
            lambda: [],
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_task_due_info",
            lambda: None,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_task_review_state",
            lambda c: "none",
        )
        # Make _do_coordination_housekeeping raise
        monkeypatch.setattr(
            "plan_follow.plan_hooks._do_coordination_housekeeping",
            lambda c: (_ for _ in ()).throw(RuntimeError("housekeeping failed")),
        )

        result = on_pre_llm_call()
        # Should still produce a banner despite housekeeping failure
        assert result is not None
        assert "[PLAN]" in result


# ═══════════════════════════════════════════════════════════════════════════════
# Lines 639–681 — Cross-session terminal warning in on_post_tool_call
# ═══════════════════════════════════════════════════════════════════════════════

class TestOnPostToolCallCrossSession:
    """Target lines 639–681: terminal() with other sessions active."""

    def test_terminal_cross_session_warning(self, monkeypatch, mock_time):
        """terminal() with pytest should warn about other sessions."""
        from plan_follow.plan_hooks import on_post_tool_call
        drift_warnings = []
        notifications = []

        current = _make_current()
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: current,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.record_tool_call",
            lambda *a, **kw: None,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.record_drift_warning",
            lambda msg: drift_warnings.append(msg),
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_session_id",
            lambda: "my-session",
        )

        # Mock coord_state for other sessions and notifications
        import plan_follow.coord_state as cs
        monkeypatch.setattr(cs, "get_sessions", lambda: {
            "my-session": {"plan_id": "p1"},
            "other-1": {"plan_id": "p2"},
        })
        monkeypatch.setattr(
            cs, "send_notification",
            lambda from_session=None, to_session=None, message="", kind="info": (
                notifications.append((to_session, message))
            ),
        )

        on_post_tool_call(
            tool_name="terminal",
            duration_ms=100,
            status="ok",
            error="",
            args={"command": "pytest tests/"},
        )

        assert len(drift_warnings) >= 1
        assert "Cross-Session" in drift_warnings[0] or "Konflikt" in drift_warnings[0]
        # Should have sent notification to the other session
        assert len(notifications) >= 1

    def test_terminal_cross_session_notify_failure(self, monkeypatch, mock_time):
        """send_notification failure should be caught."""
        from plan_follow.plan_hooks import on_post_tool_call
        drift_warnings = []

        current = _make_current()
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: current,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.record_tool_call",
            lambda *a, **kw: None,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.record_drift_warning",
            lambda msg: drift_warnings.append(msg),
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_session_id",
            lambda: "my-session",
        )

        import plan_follow.coord_state as cs
        monkeypatch.setattr(cs, "get_sessions", lambda: {
            "my-session": {"plan_id": "p1"},
            "other-1": {"plan_id": "p2"},
        })
        # Make send_notification raise
        monkeypatch.setattr(
            cs, "send_notification",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("notify failed")),
        )

        # Should not raise
        on_post_tool_call(
            tool_name="terminal",
            duration_ms=100,
            status="ok",
            error="",
            args={"command": "git commit -m 'test'"},
        )
        assert len(drift_warnings) >= 1

    def test_terminal_no_other_sessions(self, monkeypatch, mock_time):
        """No drift warning when no other sessions exist."""
        from plan_follow.plan_hooks import on_post_tool_call
        drift_warnings = []

        current = _make_current()
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: current,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.record_tool_call",
            lambda *a, **kw: None,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.record_drift_warning",
            lambda msg: drift_warnings.append(msg),
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_session_id",
            lambda: "my-session",
        )

        import plan_follow.coord_state as cs
        monkeypatch.setattr(cs, "get_sessions", lambda: {
            "my-session": {"plan_id": "p1"},
        })

        on_post_tool_call(
            tool_name="terminal",
            duration_ms=100,
            status="ok",
            error="",
            args={"command": "pytest tests/"},
        )
        assert len(drift_warnings) == 0

    def test_terminal_non_conflicting_command(self, monkeypatch, mock_time):
        """Non-conflicting commands should NOT trigger cross-session warning."""
        from plan_follow.plan_hooks import on_post_tool_call
        drift_warnings = []

        current = _make_current()
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: current,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.record_tool_call",
            lambda *a, **kw: None,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.record_drift_warning",
            lambda msg: drift_warnings.append(msg),
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_session_id",
            lambda: "my-session",
        )

        on_post_tool_call(
            tool_name="terminal",
            duration_ms=100,
            status="ok",
            error="",
            args={"command": "echo hello"},
        )
        # echo is not a conflicting command
        assert len(drift_warnings) == 0

    def test_terminal_cross_session_exception(self, monkeypatch, mock_time):
        """Cross-session terminal check should not crash on exception."""
        from plan_follow.plan_hooks import on_post_tool_call

        current = _make_current()
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: current,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.record_tool_call",
            lambda *a, **kw: None,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.record_drift_warning",
            lambda *a, **kw: None,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_session_id",
            lambda: "my-session",
        )

        # Make coord_state.get_sessions raise
        import plan_follow.coord_state as cs
        monkeypatch.setattr(
            cs, "get_sessions",
            lambda: (_ for _ in ()).throw(RuntimeError("coord_state error")),
        )

        # Should not raise
        on_post_tool_call(
            tool_name="terminal",
            duration_ms=100,
            status="ok",
            error="",
            args={"command": "pytest tests/"},
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Lines 734–735 — coord_state.send_notification exception in lock enforcement
# ═══════════════════════════════════════════════════════════════════════════════

class TestOnPostToolCallAutoNotifyException:
    """Target lines 734–735: send_notification exception caught."""

    def test_auto_notify_exception_caught(self, monkeypatch, mock_time):
        """Exception in coord_state.send_notification should be caught."""
        from plan_follow.plan_hooks import on_post_tool_call
        drift_warnings = []

        current = _make_current(files=["/workspace/src/main.py"])
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: current,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.record_tool_call",
            lambda *a, **kw: None,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.record_drift_warning",
            lambda msg: drift_warnings.append(msg),
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_session_id",
            lambda: "my-session",
        )

        import plan_follow.coord_state as cs
        monkeypatch.setattr(
            cs, "get_lock",
            lambda path: {
                "session_id": "other-session",
                "since": "2024-01-01T00:00:00",
            },
        )
        # Make send_notification raise
        monkeypatch.setattr(
            cs, "send_notification",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("send failed")),
        )
        monkeypatch.setattr(
            cs, "acquire_lock",
            lambda path, sid: {"status": "acquired"},
        )

        # Should not raise
        on_post_tool_call(
            tool_name="code_refactor",
            duration_ms=100,
            status="ok",
            error="",
            args={"path": "/workspace/src/main.py"},
        )
        assert len(drift_warnings) >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# Lines 790–792 — Lock release at session end
# ═══════════════════════════════════════════════════════════════════════════════

class TestOnSessionEnd:
    """Target lines 790–792, 802–803, 815–819."""

    def test_lock_release_logged(self, monkeypatch, caplog):
        """Line 790–792: released > 0 logs info."""
        from plan_follow.plan_hooks import on_session_end

        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_active_plan",
            lambda: _make_plan(),
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._save_plan",
            lambda p: None,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_session_id",
            lambda: "test-session",
        )

        import plan_follow.coord_state as cs
        monkeypatch.setattr(
            cs, "release_all_locks",
            lambda sid: 3,  # released 3 locks
        )
        monkeypatch.setattr(
            cs, "unregister_session",
            lambda sid: None,
        )

        # Patch PLANS_DIR to prevent log file write errors
        import tempfile
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.PLANS_DIR",
            Path(tempfile.mkdtemp()),
        )

        caplog.set_level(logging.INFO)
        on_session_end()

        assert "Released 3 lock(s)" in caplog.text

    def test_unregister_session_exception(self, monkeypatch, caplog):
        """Line 802–803: unregister_session exception should be caught."""
        from plan_follow.plan_hooks import on_session_end

        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_active_plan",
            lambda: _make_plan(),
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._save_plan",
            lambda p: None,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_session_id",
            lambda: "test-session",
        )

        import plan_follow.coord_state as cs
        monkeypatch.setattr(
            cs, "release_all_locks",
            lambda sid: 0,
        )
        monkeypatch.setattr(
            cs, "unregister_session",
            lambda sid: (_ for _ in ()).throw(RuntimeError("unregister failed")),
        )

        import tempfile
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.PLANS_DIR",
            Path(tempfile.mkdtemp()),
        )

        caplog.set_level(logging.DEBUG)
        # Should not raise
        on_session_end()
        # The exception should be logged at DEBUG level
        debug_text = caplog.text
        assert "unregister" in debug_text or "on_session_end" in debug_text or "failed" in debug_text

    def test_log_finalize_exception(self, monkeypatch, caplog):
        """Lines 815–816: log write exception in on_session_end."""
        from plan_follow.plan_hooks import on_session_end

        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_active_plan",
            lambda: _make_plan(),
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._save_plan",
            lambda p: None,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_session_id",
            lambda: "test-session",
        )

        import plan_follow.coord_state as cs
        monkeypatch.setattr(
            cs, "release_all_locks",
            lambda sid: 0,
        )
        monkeypatch.setattr(
            cs, "unregister_session",
            lambda sid: None,
        )

        # Make log_dir creation fail by making PLANS_DIR point to a file
        import tempfile
        tmpfile = Path(tempfile.mkstemp()[1])
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.PLANS_DIR",
            tmpfile,  # this is a file, can't mkdir on it (but mkdir exists_ok, so it won't fail)
        )

        caplog.set_level(logging.DEBUG)
        # Should not raise
        on_session_end()

    def test_outer_exception_handled(self, monkeypatch):
        """Line 818–819: outer exception in on_session_end caught."""
        from plan_follow.plan_hooks import on_session_end

        # Make the first thing inside the try block raise
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_active_plan",
            lambda: (_ for _ in ()).throw(RuntimeError("outer crash")),
        )
        # Should not raise
        on_session_end()

    def test_no_plan_no_session(self, monkeypatch):
        """on_session_end with no plan and no session should not crash."""
        from plan_follow.plan_hooks import on_session_end

        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_active_plan",
            lambda: None,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_session_id",
            lambda: None,
        )

        # Should not raise
        on_session_end()

    def test_lock_release_failure(self, monkeypatch, caplog):
        """on_session_end: lock release raises exception."""
        from plan_follow.plan_hooks import on_session_end

        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_active_plan",
            lambda: _make_plan(),
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._save_plan",
            lambda p: None,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_session_id",
            lambda: "test-session",
        )

        import plan_follow.coord_state as cs
        monkeypatch.setattr(
            cs, "release_all_locks",
            lambda sid: (_ for _ in ()).throw(RuntimeError("release failed")),
        )

        caplog.set_level(logging.DEBUG)
        on_session_end()
        # Should not crash, should log debug about lock release failure


# ═══════════════════════════════════════════════════════════════════════════════
# Additional edge-case tests for the stale-lock-since parsing (lines 314–319)
# ═══════════════════════════════════════════════════════════════════════════════

class TestCoordBannerStaleLockParsing:
    """Target lines 314–319: stale lock since parsing edge cases."""

    def test_stale_lock_bad_since_format(self, monkeypatch, mock_time):
        """Bad 'since' format should not crash (caught by ValueError)."""
        import plan_follow.coord_state as cs
        from plan_follow.plan_hooks import _build_coordination_banner

        monkeypatch.setattr(cs, "get_sessions", lambda: {})
        monkeypatch.setattr(cs, "get_locks", lambda: {
            "/bad/file.py": {
                "session_id": "other",
                "since": "not-a-valid-date",
            },
        })
        monkeypatch.setattr(cs, "get_notifications", lambda *a, **kw: [])
        monkeypatch.setattr(cs, "cleanup_stale_sessions", lambda *a, **kw: None)
        monkeypatch.setattr(cs, "cleanup_stale_locks", lambda *a, **kw: None)
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: None,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_session_id",
            lambda: "session-1",
        )

        lines = _build_coordination_banner()
        # Should not crash
        assert isinstance(lines, list)

    def test_stale_lock_since_none(self, monkeypatch, mock_time):
        """None 'since' should not crash."""
        import plan_follow.coord_state as cs
        from plan_follow.plan_hooks import _build_coordination_banner

        monkeypatch.setattr(cs, "get_sessions", lambda: {})
        monkeypatch.setattr(cs, "get_locks", lambda: {
            "/bad/file.py": {
                "session_id": "other",
                "since": None,
            },
        })
        monkeypatch.setattr(cs, "get_notifications", lambda *a, **kw: [])
        monkeypatch.setattr(cs, "cleanup_stale_sessions", lambda *a, **kw: None)
        monkeypatch.setattr(cs, "cleanup_stale_locks", lambda *a, **kw: None)
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: None,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_session_id",
            lambda: "session-1",
        )

        lines = _build_coordination_banner()
        assert isinstance(lines, list)


# ═══════════════════════════════════════════════════════════════════════════════
# Additional edge-case tests for _build_drift_banner (lines 220–227)
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildDriftBannerEdgeCases:
    """Target drift_warnings path in _build_drift_banner."""

    def test_drift_with_warnings(self, monkeypatch, mock_time):
        """_build_drift_banner with drift_warnings (not just drift)."""
        from plan_follow.plan_hooks import _build_drift_banner
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.check_drift",
            lambda: [],
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_drift_warnings",
            lambda: ["Warning 1", "Warning 2"],
        )
        lines = _build_drift_banner()
        text = "\n".join(lines)
        assert "DRIFT WARNING" in text

    def test_drift_warnings_truncated(self, monkeypatch, mock_time):
        """More than 2 drift_warnings → '... and N more'."""
        from plan_follow.plan_hooks import _build_drift_banner
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.check_drift",
            lambda: [],
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_drift_warnings",
            lambda: ["w1", "w2", "w3"],
        )
        lines = _build_drift_banner()
        text = "\n".join(lines)
        assert "more" in text


# ═══════════════════════════════════════════════════════════════════════════════
# Additional edge-case tests for _build_due_banner (lines 240–250)
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildDueBannerEdgeCases:
    """Target overdue and due-soon paths."""

    def test_overdue_zero_days(self, monkeypatch):
        """Overdue with 0 days remaining."""
        from plan_follow.plan_hooks import _build_due_banner
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_task_due_info",
            lambda: {"overdue": True, "days_remaining": 0, "due": "2024-01-01"},
        )
        lines = _build_due_banner()
        text = "\n".join(lines)
        assert "OVERDUE" in text

    def test_due_soon_boundary(self, monkeypatch):
        """Exactly 3 days remaining should still show warning."""
        from plan_follow.plan_hooks import _build_due_banner
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_task_due_info",
            lambda: {"overdue": False, "days_remaining": 3, "due": "2024-01-04"},
        )
        lines = _build_due_banner()
        text = "\n".join(lines)
        assert "DEADLINE" in text or "SOON" in text or "Noch" in text


# ═══════════════════════════════════════════════════════════════════════════════
# Additional edge-case tests for _build_review_banner (lines 493–494)
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildReviewBannerEdgeCases:
    """Target passed review state."""

    def test_review_passed_msg(self, monkeypatch):
        """Review passed should show completion message."""
        from plan_follow.plan_hooks import _build_review_banner
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_task_review_state",
            lambda c: "passed",
        )
        current = _make_current(review_profile="strict")
        lines = _build_review_banner(current)
        text = "\n".join(lines)
        assert "PASSED" in text or "✅" in text


# ═══════════════════════════════════════════════════════════════════════════════
# Additional edge-case tests for _build_breaker_banner (lines 501–515)
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildBreakerBannerEdgeCases:
    """Target lines 511–512: more than 3 breakers → '... und N weitere'."""

    def test_breaker_more_than_3(self, mock_time):
        """More than 3 active breakers should show truncation."""
        from plan_follow.plan_hooks import _build_breaker_banner, _set_breaker
        for i in range(5):
            _set_breaker(f"tool_{i}", f"error {i}")
        lines = _build_breaker_banner()
        text = "\n".join(lines)
        assert "CIRCUIT BREAKER" in text
        assert "weitere" in text or "more" in text


# ═══════════════════════════════════════════════════════════════════════════════
# Additional edge-case tests for on_post_tool_call logging (lines 748–762)
# ═══════════════════════════════════════════════════════════════════════════════

class TestOnPostToolCallLogging:
    """Target the log write path (should already be hit but let's be safe)."""

    def test_session_log_write(self, monkeypatch, mock_time, tmp_path):
        """Verify the session log file is written."""
        from plan_follow.plan_hooks import on_post_tool_call

        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: None,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.record_tool_call",
            lambda *a, **kw: None,
        )

        log_dir = tmp_path / ".session-logs"
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.PLANS_DIR",
            tmp_path,
        )

        on_post_tool_call(tool_name="code_search", duration_ms=50, status="ok")

        log_file = log_dir / "tool-calls.log"
        assert log_file.exists()
        content = log_file.read_text()
        assert "code_search" in content
        assert "ok" in content

    def test_session_log_append(self, monkeypatch, mock_time, tmp_path):
        """Log entries should append, not overwrite."""
        from plan_follow.plan_hooks import on_post_tool_call

        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: None,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.record_tool_call",
            lambda *a, **kw: None,
        )

        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.PLANS_DIR",
            tmp_path,
        )

        on_post_tool_call(tool_name="code_search", duration_ms=50, status="ok")
        on_post_tool_call(tool_name="patch", duration_ms=100, status="ok")

        log_file = tmp_path / ".session-logs" / "tool-calls.log"
        content = log_file.read_text()
        entries = content.strip().split("\n")
        assert len(entries) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# Final uncovered lines: 46, 374, 377, 387–388
# ═══════════════════════════════════════════════════════════════════════════════

class TestHousekeepingUpdateSession:
    """Target line 46: _do_coordination_housekeeping update_session path."""

    def test_housekeeping_updates_existing_session(self, monkeypatch):
        """When session already registered, update_session is called."""
        from plan_follow import coord_state, plan_core
        from plan_follow.plan_hooks import _do_coordination_housekeeping

        # Pre-register the session so get_session returns truthy
        coord_state.register_session("test-session-42", plan_id="p1", goal="initial")
        assert coord_state.get_session("test-session-42") is not None

        monkeypatch.setattr(
            plan_core, "get_session_id", lambda: "test-session-42"
        )
        monkeypatch.setattr(
            plan_core, "_get_active_plan",
            lambda: {"plan_id": "p2", "goal": "Updated Goal"},
        )

        current = _make_current(task_id="T001", files=[])
        result = _do_coordination_housekeeping(current)

        # Should have called update_session (not register_session)
        # The session should still exist with updated info
        session = coord_state.get_session("test-session-42")
        assert session is not None
        # Result is 0 because no files to lock
        assert result == 0


class TestRepoConflictEdgeCases:
    """Target lines 374, 377, 387–388: edge cases in repo conflict loop."""

    def test_repo_conflict_empty_other_pid(self, monkeypatch, mock_time):
        """Line 374: continue when other session has no plan_id."""
        import plan_follow.coord_state as cs
        from plan_follow.plan_hooks import _build_coordination_banner

        my_sid = "session-mine"
        monkeypatch.setattr(cs, "get_sessions", lambda: {
            my_sid: {"plan_id": "my-plan", "last_seen": "2024-01-01T12:00:00"},
            "session-other": {"plan_id": "", "last_seen": "2024-01-01T12:00:00"},  # empty pid
        })
        monkeypatch.setattr(cs, "get_locks", lambda: {})
        monkeypatch.setattr(cs, "get_notifications", lambda *a, **kw: [])
        monkeypatch.setattr(cs, "cleanup_stale_sessions", lambda *a, **kw: None)
        monkeypatch.setattr(cs, "cleanup_stale_locks", lambda *a, **kw: None)
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: _make_current(),
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_session_id",
            lambda: my_sid,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_active_plan",
            lambda: _make_plan(repos=["/workspace"]),
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_repos",
            lambda p: ["/workspace"],
        )

        # Should not crash despite empty plan_id
        lines = _build_coordination_banner()
        assert isinstance(lines, list)

    def test_repo_conflict_file_not_exists(self, monkeypatch, mock_time, tmp_path):
        """Line 377: continue when other plan file doesn't exist."""
        import plan_follow.coord_state as cs
        from plan_follow.plan_hooks import _build_coordination_banner

        my_sid = "session-mine"
        other_plan_id = "nonexistent-plan"

        monkeypatch.setattr(cs, "get_sessions", lambda: {
            my_sid: {"plan_id": "my-plan", "last_seen": "2024-01-01T12:00:00"},
            "session-other": {"plan_id": other_plan_id, "last_seen": "2024-01-01T12:00:00"},
        })
        monkeypatch.setattr(cs, "get_locks", lambda: {})
        monkeypatch.setattr(cs, "get_notifications", lambda *a, **kw: [])
        monkeypatch.setattr(cs, "cleanup_stale_sessions", lambda *a, **kw: None)
        monkeypatch.setattr(cs, "cleanup_stale_locks", lambda *a, **kw: None)
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: _make_current(),
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_session_id",
            lambda: my_sid,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_active_plan",
            lambda: _make_plan(repos=["/workspace"]),
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_repos",
            lambda p: ["/workspace"],
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.PLANS_DIR",
            tmp_path,  # empty tmp dir, file won't exist
        )

        # Should not crash
        lines = _build_coordination_banner()
        assert isinstance(lines, list)

    def test_repo_conflict_json_read_error(self, monkeypatch, mock_time, tmp_path):
        """Lines 387–388: continue when JSON read fails."""
        import plan_follow.coord_state as cs
        from plan_follow.plan_hooks import _build_coordination_banner

        my_sid = "session-mine"
        other_plan_id = "corrupt-plan"

        # Create a file with invalid JSON
        other_file = tmp_path / f"{other_plan_id}.json"
        other_file.write_text("not valid json {[}]")

        monkeypatch.setattr(cs, "get_sessions", lambda: {
            my_sid: {"plan_id": "my-plan", "last_seen": "2024-01-01T12:00:00"},
            "session-other": {"plan_id": other_plan_id, "last_seen": "2024-01-01T12:00:00"},
        })
        monkeypatch.setattr(cs, "get_locks", lambda: {})
        monkeypatch.setattr(cs, "get_notifications", lambda *a, **kw: [])
        monkeypatch.setattr(cs, "cleanup_stale_sessions", lambda *a, **kw: None)
        monkeypatch.setattr(cs, "cleanup_stale_locks", lambda *a, **kw: None)
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_current_task_cached",
            lambda: _make_current(),
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.get_session_id",
            lambda: my_sid,
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_active_plan",
            lambda: _make_plan(repos=["/workspace"]),
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core._get_repos",
            lambda p: ["/workspace"],
        )
        monkeypatch.setattr(
            "plan_follow.plan_hooks.plan_core.PLANS_DIR",
            tmp_path,
        )

        # Should not crash despite corrupt JSON
        lines = _build_coordination_banner()
        assert isinstance(lines, list)
