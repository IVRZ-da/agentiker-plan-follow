"""Tests for coord_state.py (Cross-Session Coordination) + optional Git integration.

Run: python -m pytest tests/test_coord_state.py -v
"""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure plugin is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

try:
    from plan_follow.coord_state import (
        register_session, unregister_session, update_session,
        get_sessions, get_session,
        acquire_lock, release_lock, get_locks, get_lock,
        send_notification, get_notifications, clear_notifications,
        cleanup_stale_sessions, cleanup_stale_locks,
        SHARED_DIR, SESSIONS_FILE, LOCKS_FILE, NOTIFICATIONS_FILE,
    )
except ImportError:
    # Silent fallback — expected when running tests directly
    # (conftest.py handles module setup for pytest suite runs)
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from coord_state import (
        register_session, unregister_session, update_session,
        get_sessions, get_session,
        acquire_lock, release_lock, get_locks, get_lock,
        send_notification, get_notifications, clear_notifications,
        cleanup_stale_sessions, cleanup_stale_locks,
        SHARED_DIR, SESSIONS_FILE, LOCKS_FILE, NOTIFICATIONS_FILE,
    )


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clean_shared_state():
    """Clean shared state files before each test."""
    for f in [SESSIONS_FILE, LOCKS_FILE, NOTIFICATIONS_FILE]:
        f.unlink(missing_ok=True)
    yield


@pytest.fixture
def sample_session():
    """Register a sample session for tests."""
    register_session("session-a", plan_id="plan-1", goal="Test Plan A")
    register_session("session-b", plan_id="plan-2", goal="Test Plan B")
    yield
    unregister_session("session-a")
    unregister_session("session-b")


# ─── Session Tests (15 Tests) ─────────────────────────────────────────────────


class TestSessions:
    def test_register_session(self):
        s = register_session("test-1", plan_id="p1", goal="Goal")
        assert "test-1" in s
        assert s["test-1"]["plan_id"] == "p1"
        assert s["test-1"]["goal"] == "Goal"

    def test_register_multiple_sessions(self):
        register_session("s1", plan_id="p1")
        register_session("s2", plan_id="p2")
        sessions = get_sessions()
        assert len(sessions) == 2
        assert "s1" in sessions
        assert "s2" in sessions

    def test_unregister_session(self):
        register_session("temp", plan_id="p1")
        assert "temp" in get_sessions()
        unregister_session("temp")
        assert "temp" not in get_sessions()

    def test_unregister_nonexistent(self):
        """Unregistering a non-existent session should not raise."""
        result = unregister_session("ghost")
        assert isinstance(result, dict)

    def test_get_session(self):
        register_session("find-me", plan_id="p1", goal="Find")
        s = get_session("find-me")
        assert s is not None
        assert s["plan_id"] == "p1"

    def test_get_session_missing(self):
        assert get_session("ghost") is None

    def test_update_session(self):
        register_session("upd", plan_id="p1")
        update_session("upd", plan_id="p2", goal="Updated")
        s = get_session("upd")
        assert s["plan_id"] == "p2"
        assert s["goal"] == "Updated"

    def test_update_session_timestamp(self):
        """last_seen should be updated on every update."""
        register_session("ts", plan_id="p1")
        s1 = get_session("ts")
        t1 = s1["last_seen"]
        update_session("ts", plan_id="p1")
        s2 = get_session("ts")
        assert s2["last_seen"] >= t1

    def test_cleanup_stale_sessions(self, sample_session):
        """Cleanup with max_age=0 should remove all."""
        removed = cleanup_stale_sessions(max_age_minutes=0)
        assert removed >= 2

    def test_cleanup_preserves_fresh(self, sample_session):
        """Cleanup with large max_age should not remove fresh sessions."""
        removed = cleanup_stale_sessions(max_age_minutes=999)
        assert removed == 0

    def test_cleanup_idempotent(self):
        """Running cleanup on empty state should not error."""
        removed = cleanup_stale_sessions(max_age_minutes=0)
        assert removed == 0

    def test_get_sessions_empty(self):
        assert get_sessions() == {}

    def test_register_with_cwd(self):
        register_session("cwd-test", cwd="/home/test/project")
        s = get_session("cwd-test")
        assert s["cwd"] == "/home/test/project"

    def test_session_persistence_across_calls(self):
        register_session("persist", plan_id="p1")
        s1 = get_sessions()
        s2 = get_sessions()
        assert s1 == s2

    def test_session_no_crosstalk(self):
        """Different session IDs should not interfere."""
        register_session("a", plan_id="pa")
        register_session("b", plan_id="pb")
        assert get_session("a")["plan_id"] == "pa"
        assert get_session("b")["plan_id"] == "pb"


# ─── Lock Tests (12 Tests) ────────────────────────────────────────────────────


class TestLocks:
    def test_acquire_lock(self):
        result = acquire_lock("/path/file.ts", "session-a")
        assert result["status"] == "acquired"
        assert result["locked_by"] == "session-a"

    def test_acquire_lock_conflict(self):
        acquire_lock("/path/file.ts", "session-a")
        result = acquire_lock("/path/file.ts", "session-b")
        assert result["status"] == "exists"
        assert result["locked_by"] == "session-a"

    def test_acquire_lock_renew(self):
        """Same session should be able to re-acquire (renew)."""
        acquire_lock("/path/file.ts", "session-a")
        result = acquire_lock("/path/file.ts", "session-a")
        assert result["status"] == "acquired"

    def test_release_lock(self):
        acquire_lock("/path/file.ts", "session-a")
        result = release_lock("/path/file.ts", "session-a")
        assert result["status"] == "released"

    def test_release_not_holder(self):
        acquire_lock("/path/file.ts", "session-a")
        result = release_lock("/path/file.ts", "session-b")
        assert result["status"] == "not_holder"
        assert result["locked_by"] == "session-a"

    def test_release_not_locked(self):
        result = release_lock("/nonexistent.ts", "session-a")
        assert result["status"] == "not_locked"

    def test_get_lock(self):
        acquire_lock("/locked.ts", "session-a")
        lock = get_lock("/locked.ts")
        assert lock is not None
        assert lock["session_id"] == "session-a"

    def test_get_lock_free(self):
        """Getting a lock on a free path should return None."""
        assert get_lock("/free.ts") is None

    def test_get_locks(self):
        acquire_lock("/a.ts", "s1")
        acquire_lock("/b.ts", "s2")
        locks = get_locks()
        assert len(locks) == 2
        assert "/a.ts" in locks
        assert "/b.ts" in locks

    def test_cleanup_stale_locks(self):
        acquire_lock("/stale.ts", "s1")
        removed = cleanup_stale_locks(max_age_minutes=0)
        assert removed >= 1
        assert get_lock("/stale.ts") is None

    def test_multiple_locks_same_session(self):
        acquire_lock("/a.ts", "s1")
        acquire_lock("/b.ts", "s1")
        assert len(get_locks()) == 2

    def test_release_nonexistent_session(self):
        """Releasing from a session that never existed should be safe."""
        result = release_lock("/test.ts", "phantom")
        assert result["status"] == "not_locked"


# ─── Notification Tests (8 Tests) ─────────────────────────────────────────────


class TestNotifications:
    def test_send_notification(self):
        result = send_notification("alice", "bob", "Hallo Bob", kind="info")
        assert result["to"] == "bob"
        assert result["from"] == "alice"
        assert result["message"] == "Hallo Bob"

    def test_get_notifications(self):
        send_notification("alice", "bob", "Nachricht 1")
        send_notification("charlie", "bob", "Nachricht 2")
        pending = get_notifications("bob")
        assert len(pending) == 2

    def test_get_notifications_marks_read(self):
        send_notification("alice", "bob", "Test")
        get_notifications("bob")
        # Zweites Lesen sollte leer sein (mark_read=True)
        remaining = get_notifications("bob")
        assert len(remaining) == 0

    def test_get_notifications_empty(self):
        assert get_notifications("nobody") == []

    def test_clear_notifications(self):
        send_notification("alice", "bob", "Nachricht")
        clear_notifications("bob")
        assert get_notifications("bob") == []

    def test_notification_kind(self):
        result = send_notification("a", "b", "Warnung", kind="warning")
        assert result["kind"] == "warning"

    def test_notification_multiple_senders(self):
        send_notification("alice", "bob", "Von Alice")
        send_notification("charlie", "bob", "Von Charlie")
        pending = get_notifications("bob")
        messages = {n["from"]: n["message"] for n in pending}
        assert messages["alice"] == "Von Alice"
        assert messages["charlie"] == "Von Charlie"

    def test_notification_timestamp(self):
        result = send_notification("a", "b", "Test")
        assert "timestamp" in result
        assert result["timestamp"]  # Nicht leer


# ─── Plan-Tool Tests via direkter Import (10 Tests) ───────────────────────────


class TestPlanTools:
    """Test the tool functions directly (without Hermes plugin context).

These tests import via plan_follow.plan_tools so relative imports work.
"""

    def test_plan_session_tool_empty(self):
        from plan_follow.plan_tools import plan_session_tool
        result = plan_session_tool({}, **{})
        assert "active_sessions" in result or "sessions" in result

    def test_plan_session_with_data(self, sample_session):
        from plan_follow.plan_tools import plan_session_tool
        result = plan_session_tool({}, **{})
        data = json.loads(result) if isinstance(result, str) else result

    def test_plan_lock_tool_acquire(self):
        from plan_follow.plan_tools import plan_lock_tool
        result = plan_lock_tool({"action": "lock", "path": "/test.ts", "session_id": "s1"}, **{})
        assert "acquired" in result

    def test_plan_lock_tool_status(self):
        from plan_follow.plan_tools import plan_lock_tool
        result = plan_lock_tool({"action": "status", "path": "/test.ts"}, **{})
        assert "free" in result or "locked" in result

    def test_plan_lock_tool_unlock(self):
        from plan_follow.plan_tools import plan_lock_tool
        plan_lock_tool({"action": "lock", "path": "/test.ts", "session_id": "s1"}, **{})
        result = plan_lock_tool({"action": "unlock", "path": "/test.ts", "session_id": "s1"}, **{})
        assert "released" in result

    def test_plan_lock_tool_missing_args(self):
        from plan_follow.plan_tools import plan_lock_tool
        result = plan_lock_tool({}, **{})
        assert "error" in result or "action" in result

    def test_plan_notify_send(self):
        from plan_follow.plan_tools import plan_notify_tool
        result = plan_notify_tool({"action": "send", "to": "target", "message": "Hi"}, **{})
        assert "sent" in result

    def test_plan_notify_check_empty(self):
        from plan_follow.plan_tools import plan_notify_tool
        result = plan_notify_tool({"action": "check"}, **{})
        assert "check" in result

    def test_plan_notify_missing_args(self):
        from plan_follow.plan_tools import plan_notify_tool
        result = plan_notify_tool({}, **{})
        assert "error" in result

    def test_plan_history_no_git(self):
        """plan_history should return 'not active' hint when no .git exists."""
        from plan_follow.plan_tools import plan_history_tool
        from plan_follow.plan_core import PLANS_DIR

        git_dir = PLANS_DIR / ".git"
        had_git = git_dir.exists()
        try:
            if had_git:
                import shutil, tempfile
                backup = tempfile.mkdtemp()
                shutil.move(str(git_dir), os.path.join(backup, "dot_git"))

            result = plan_history_tool({"plan_id": "test-plan"}, **{})
            assert "nicht aktiv" in result or "Keine" in result
        finally:
            if had_git:
                import shutil
                shutil.move(os.path.join(backup, "dot_git"), str(git_dir))


# ─── Git-Integration Tests (10 Tests) ─────────────────────────────────────────


class TestGitIntegration:
    """Tests for optional Git integration."""

    def test_git_commit_if_no_git(self):
        """_git_commit_if_active should silently skip when no .git exists."""
        from plan_follow.plan_core import _git_commit_if_active
        result = _git_commit_if_active({"plan_id": "test", "tasks": {}, "current_task": None})
        assert result is None  # Silent skip

    def test_git_commit_creates_commit(self, tmp_path):
        """_git_commit_if_active should create a commit when .git exists."""
        from plan_follow.plan_core import _git_commit_if_active, PLANS_DIR

        # Temporarily create a git repo in PLANS_DIR
        import subprocess
        orig_git = PLANS_DIR / ".git"
        had_git = orig_git.exists()

        try:
            if not had_git:
                subprocess.run(["git", "init"], cwd=PLANS_DIR, capture_output=True, timeout=10)

            plan = {"plan_id": "git-test-plan", "tasks": {"t1": {"status": "completed"}}, "current_task": "t1"}

            # Save plan first (otherwise _git_commit_if_active has nothing to add)
            from plan_core import _save_plan
            _save_plan(plan)

            # Check commit exists
            log = subprocess.run(
                ["git", "log", "--oneline", "--", "git-test-plan.json"],
                cwd=PLANS_DIR, capture_output=True, text=True, timeout=10,
            )
            assert log.stdout.strip(), "Expected at least one commit for git-test-plan.json"
        finally:
            if not had_git and orig_git.exists():
                import shutil
                shutil.rmtree(orig_git)

    def test_git_skip_on_no_git(self, tmp_path):
        """Without .git dir, _save_plan should work normally."""
        from plan_follow.plan_core import _save_plan, PLANS_DIR

        git_dir = PLANS_DIR / ".git"
        had_git = git_dir.exists()

        try:
            if had_git:
                import shutil, tempfile
                backup = tmp_path / "dot_git_backup"
                shutil.move(str(git_dir), str(backup))

            plan = {"plan_id": "no-git-test", "tasks": {}, "current_task": None}
            _save_plan(plan)  # Should not raise

            # Verify plan was saved
            plan_path = PLANS_DIR / "no-git-test.json"
            assert plan_path.exists(), "Plan sollte gespeichert sein"
            plan_path.unlink()
        finally:
            if not had_git:
                pass
            elif had_git and not git_dir.exists():
                import shutil
                shutil.move(str(backup), str(git_dir))

    def test_plan_git_init_tool(self):
        """plan_git_init should work and show 'initialized' or 'already active'."""
        from plan_follow.plan_tools import plan_git_init_tool

        git_dir = Path.home() / ".hermes" / "plans" / ".git"
        had_git = git_dir.exists()

        try:
            if had_git:
                import shutil, tempfile
                backup = tempfile.mkdtemp()
                shutil.move(str(git_dir), os.path.join(backup, "dot_git"))

            result = plan_git_init_tool({}, **{})
            assert "initialized" in result or "bereits aktiv" in result
        finally:
            if had_git:
                import shutil
                shutil.move(os.path.join(backup, "dot_git"), str(git_dir))

    def test_history_tool_custom_plan_id(self):
        """plan_history with specific plan_id should work."""
        from plan_follow.plan_tools import plan_history_tool
        result = plan_history_tool({"plan_id": "non-existent-plan"}, **{})
        # Should return either 'Keine Git-History' or 'nicht aktiv'
        assert any(x in result for x in ["nicht aktiv", "Keine", "error"])

    def test_history_tool_invalid_lines(self):
        """plan_history should handle various lines params."""
        from plan_follow.plan_tools import plan_history_tool
        result = plan_history_tool({"plan_id": "test", "lines": -1}, **{})
        # Should not crash
        assert result is not None


# ─── Edge Cases (5 Tests) ─────────────────────────────────────────────────────


class TestEdgeCases:
    def test_concurrent_sessions_same_goal(self):
        """Two sessions with same goal should coexist."""
        register_session("alpha", plan_id="p1", goal="Gleiches Ziel")
        register_session("beta", plan_id="p2", goal="Gleiches Ziel")
        sessions = get_sessions()
        assert len(sessions) == 2

    def test_lock_after_release(self):
        """After releasing a lock, another session should acquire it."""
        acquire_lock("/shared.ts", "alice")
        release_lock("/shared.ts", "alice")
        result = acquire_lock("/shared.ts", "bob")
        assert result["status"] == "acquired"

    def test_notifications_not_leaking(self):
        """Notifications for session A should not appear for session B."""
        send_notification("alice", "bob", "Geheim")
        alice_notifs = get_notifications("alice")
        bob_notifs = get_notifications("bob")
        assert len(alice_notifs) == 0
        assert len(bob_notifs) == 1

    def test_register_without_plan_id(self):
        """Registering without plan_id should work (default empty)."""
        register_session("no-plan")
        s = get_session("no-plan")
        assert s["plan_id"] == ""
        unregister_session("no-plan")

    def test_smoke_run_all_tools(self):
        """Quick smoke test of all 5 new tools without crashing."""
        from plan_follow.plan_tools import (
            plan_session_tool, plan_lock_tool, plan_notify_tool,
            plan_history_tool, plan_git_init_tool,
        )
        # Just call them — they should not crash
        plan_session_tool({}, **{})
        plan_lock_tool({"action": "status", "path": "/smoke.ts"}, **{})
        plan_notify_tool({"action": "check"}, **{})
        plan_history_tool({"plan_id": "smoke"}, **{})
        plan_git_init_tool({}, **{})
        

# ─── Auto-Lock/Unlock Tests ────────────────────────────────────────────────────


class TestAutoLocks:
    """Tests for auto-lock/unlock on task activation/completion."""

    def test_auto_lock_task_files(self):
        """_auto_lock_task_files should acquire locks for all task files."""
        from plan_follow.plan_core import _auto_lock_task_files

        task = {"files": ["src/foo.py", "src/bar.ts"]}
        _auto_lock_task_files(task)

        locks = get_locks()
        assert "src/foo.py" in locks
        assert "src/bar.ts" in locks

    def test_auto_lock_empty_files(self):
        """_auto_lock_task_files with empty files should not crash."""
        from plan_follow.plan_core import _auto_lock_task_files
        _auto_lock_task_files({"files": []})  # Should not raise

    def test_auto_lock_no_files_key(self):
        """_auto_lock_task_files without 'files' key should not crash."""
        from plan_follow.plan_core import _auto_lock_task_files
        _auto_lock_task_files({})  # Should not raise

    def test_auto_unlock_task_files(self):
        """_auto_unlock_task_files should release locks."""
        from plan_follow.plan_core import _auto_lock_task_files, _auto_unlock_task_files

        task = {"files": ["src/release.ts"]}
        _auto_lock_task_files(task)
        assert "src/release.ts" in get_locks()

        _auto_unlock_task_files(task)
        assert "src/release.ts" not in get_locks()

    def test_auto_lock_then_unlock_reacquire(self):
        """After unlock, another lock should succeed."""
        from plan_follow.plan_core import _auto_lock_task_files, _auto_unlock_task_files

        task = {"files": ["src/shared.ts"]}
        _auto_lock_task_files(task)
        _auto_unlock_task_files(task)

        # Another session should be able to lock now
        result = acquire_lock("src/shared.ts", "other-session")
        assert result["status"] == "acquired"


# ─── Session-ID Tests ──────────────────────────────────────────────────────────


class TestSessionId:
    """Tests for centralized get_session_id()."""

    def test_get_session_id_cached(self):
        """get_session_id should return same value within a session."""
        from plan_follow.plan_core import get_session_id, reset_session_id
        reset_session_id()
        sid1 = get_session_id()
        sid2 = get_session_id()
        assert sid1 == sid2

    def test_get_session_id_set_env(self):
        """get_session_id should use HERMES_SESSION_ID env var when set."""
        from plan_follow.plan_core import get_session_id, reset_session_id
        reset_session_id()
        expected = "my-custom-session-42"
        os.environ["HERMES_SESSION_ID"] = expected
        try:
            reset_session_id()
            sid = get_session_id()
            assert sid == expected
        finally:
            os.environ.pop("HERMES_SESSION_ID", None)

    def test_get_session_id_fallback_uuid(self):
        """Without env var, get_session_id should return a UUID (not hostname)."""
        from plan_follow.plan_core import get_session_id, reset_session_id

        # Remove env vars to force UUID fallback
        orig_h = os.environ.pop("HERMES_SESSION_ID", None)
        orig_s = os.environ.pop("SESSION_ID", None)
        try:
            reset_session_id()
            sid = get_session_id()
            # Should look like a UUID: 8-4-4-4-12 hex pattern
            import re
            assert re.match(r"^[a-f0-9-]{36}$", sid), f"Expected UUID, got: {sid}"
        finally:
            if orig_h:
                os.environ["HERMES_SESSION_ID"] = orig_h
            if orig_s:
                os.environ["SESSION_ID"] = orig_s

    def test_notification_with_real_session(self):
        """Notifications with real session IDs should work end-to-end."""
        from plan_follow.plan_core import get_session_id, reset_session_id
        reset_session_id()

        sid = "test-real-session"
        send_notification("alice", sid, "Hi from Alice")
        notifs = get_notifications(sid, mark_read=False)
        assert len(notifs) == 1
        assert notifs[0]["message"] == "Hi from Alice"


# ─── Cleanup Stale Tests ────────────────────────────────────────────────────────


class TestCleanupStale:
    """Tests for automatic stale session/lock cleanup."""

    def test_cleanup_stale_sessions_removes_old(self):
        """cleanup_stale_sessions should remove sessions older than max_age."""
        register_session("old-session")
        # Manually set last_seen far in the past
        import json
        from datetime import datetime, timezone
        old_time = (datetime.now(timezone.utc).isoformat())
        sessions = get_sessions()
        sessions["old-session"]["last_seen"] = "2020-01-01T00:00:00"
        from plan_follow.coord_state import _atomic_write
        _atomic_write(SESSIONS_FILE, sessions)

        removed = cleanup_stale_sessions(max_age_minutes=1)
        assert removed >= 1
        assert "old-session" not in get_sessions()

    def test_cleanup_stale_sessions_keeps_fresh(self):
        """cleanup_stale_sessions should NOT remove fresh sessions."""
        register_session("fresh-session")
        removed = cleanup_stale_sessions(max_age_minutes=60)
        assert removed == 0
        assert "fresh-session" in get_sessions()
        unregister_session("fresh-session")

    def test_cleanup_stale_locks_removes_old(self):
        """cleanup_stale_locks should remove locks older than max_age."""
        acquire_lock("/old-file.ts", "old")
        # Manually set since far in the past
        import json
        from datetime import datetime, timezone
        from plan_follow.coord_state import _atomic_write
        locks = get_locks()
        assert "/old-file.ts" in locks
        locks["/old-file.ts"]["since"] = "2020-01-01T00:00:00"
        _atomic_write(LOCKS_FILE, locks)

        removed = cleanup_stale_locks(max_age_minutes=1)
        assert removed >= 1
        assert "/old-file.ts" not in get_locks()
