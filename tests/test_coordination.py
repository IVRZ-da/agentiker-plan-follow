"""Tests for coordinate.py — Honcho + Git + Lock integration."""

import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

# Ensure plugin is importable (same pattern as test_coord_state.py)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# Create tools.registry module mock so from tools.registry import registry works
import types  # noqa: E402

_tools_reg_mock = types.ModuleType("tools.registry")
_tools_reg_mock.registry = MagicMock()
sys.modules["tools.registry"] = _tools_reg_mock

from plan_follow.tools.coordination import (  # noqa: E402
    _auto_lock_task_files,
    _auto_unlock_task_files,
    _dispatch_honcho_tool,
    _git_commit_if_active,
    _load_plan_state_from_honcho,
    _retry_with_backoff,
    _save_plan_state_to_honcho,
)

# ─── _retry_with_backoff ────────────────────────────────────────────────────────


class TestRetryWithBackoff:
    """Test _retry_with_backoff — exponential backoff wrapper."""

    def test_success_on_first_try(self):
        """Return result immediately if fn succeeds on first attempt."""
        fn = MagicMock(return_value="ok")
        assert _retry_with_backoff(fn, max_attempts=3) == "ok"
        fn.assert_called_once()

    def test_succeeds_on_second_attempt(self, caplog):
        """Retry on failure, succeed on 2nd attempt."""
        caplog.set_level("DEBUG")
        side_effects = [ValueError("first fail"), "success"]
        fn = MagicMock(side_effect=side_effects)
        with patch.object(time, "sleep") as mock_sleep:
            result = _retry_with_backoff(fn, max_attempts=3)
        assert result == "success"
        assert fn.call_count == 2
        mock_sleep.assert_called_once_with(1)  # 2^0 = 1s
        assert "Honcho retry" in caplog.text

    def test_fails_all_retries(self):
        """Raise the last exception when all retries fail."""
        fn = MagicMock(side_effect=ValueError("always fails"))
        with patch.object(time, "sleep"):
            with pytest.raises(ValueError, match="always fails"):
                _retry_with_backoff(fn, max_attempts=3)
        assert fn.call_count == 3

    def test_max_attempts_zero_raises_runtime_error(self):
        """When max_attempts=0 and no exception caught, raise RuntimeError."""
        # fn succeeds on first try, but max_attempts=0 means loop doesn't run
        fn = MagicMock(return_value="works")
        with pytest.raises(RuntimeError, match="_retry_with_backoff: no exception was caught"):
            _retry_with_backoff(fn, max_attempts=0)
        fn.assert_not_called()

    def test_max_attempts_one_fails(self):
        """With max_attempts=1, fails immediately (no retry sleep)."""
        fn = MagicMock(side_effect=ValueError("single fail"))
        with patch.object(time, "sleep") as mock_sleep:
            with pytest.raises(ValueError, match="single fail"):
                _retry_with_backoff(fn, max_attempts=1)
        assert fn.call_count == 1
        mock_sleep.assert_not_called()

    def test_multiple_failures_backoff_times(self, caplog):
        """Verify exponential backoff: 1s, 2s, 4s for 3 failures with max_attempts=4."""
        caplog.set_level("DEBUG")
        fn = MagicMock(side_effect=RuntimeError("fail"))
        with patch.object(time, "sleep") as mock_sleep:
            with pytest.raises(RuntimeError, match="fail"):
                _retry_with_backoff(fn, max_attempts=4)
        assert fn.call_count == 4
        assert mock_sleep.call_args_list == [call(1), call(2), call(4)]
        assert caplog.text.count("Honcho retry") == 3


# ─── _dispatch_honcho_tool ──────────────────────────────────────────────────────


class TestDispatchHonchoTool:
    """Test _dispatch_honcho_tool — registry dispatch with fallback."""

    def _make_mock_registry(self, mock_get_entry):
        """Set up tools.registry via sys.modules injection to avoid import conflicts."""
        # Create a fresh tools.registry module in sys.modules
        reg_mod = types.ModuleType("tools.registry")
        reg_mod.registry = MagicMock()
        reg_mod.registry.get_entry = mock_get_entry
        sys.modules["tools.registry"] = reg_mod
        return reg_mod.registry

    def test_registry_has_tool_returns_parsed_result(self):
        """Registry returns handler that returns JSON string → parsed dict."""
        entry_mock = MagicMock()
        entry_mock.handler = lambda args: json.dumps({"result": "ok", "key": "value"})
        mock_get_entry = MagicMock(return_value=entry_mock)
        self._make_mock_registry(mock_get_entry)

        result = _dispatch_honcho_tool("honcho_conclude", {"foo": "bar"})

        assert result == {"result": "ok", "key": "value"}

    def test_registry_has_tool_handler_returns_dict(self):
        """Handler returns a dict directly (not a string) — returned as-is."""
        entry_mock = MagicMock()
        entry_mock.handler = lambda args: {"result": "ok"}
        mock_get_entry = MagicMock(return_value=entry_mock)
        self._make_mock_registry(mock_get_entry)

        result = _dispatch_honcho_tool("honcho_conclude", {"foo": "bar"})

        assert result == {"result": "ok"}

    def test_registry_has_no_tool_returns_none(self):
        """get_entry returns None → returns None."""
        mock_get_entry = MagicMock(return_value=None)
        self._make_mock_registry(mock_get_entry)

        result = _dispatch_honcho_tool("nonexistent", {})

        assert result is None

    def test_handler_not_callable_returns_none(self):
        """Entry exists but handler is not callable → returns None."""
        entry_mock = MagicMock()
        entry_mock.handler = "not_callable_string"
        mock_get_entry = MagicMock(return_value=entry_mock)
        self._make_mock_registry(mock_get_entry)

        result = _dispatch_honcho_tool("some_tool", {})

        assert result is None

    def test_exception_during_dispatch_returns_none(self):
        """Exception during dispatch is caught, logged at debug, returns None."""
        mock_get_entry = MagicMock(side_effect=ValueError("registry error"))
        self._make_mock_registry(mock_get_entry)

        with patch("plan_follow.tools.coordination.logger") as mock_logger:
            result = _dispatch_honcho_tool("honcho_conclude", {})

        assert result is None
        mock_logger.debug.assert_called_once_with("Honcho dispatch failed (best-effort)")


# ─── _save_plan_state_to_honcho ────────────────────────────────────────────────


class TestSavePlanStateToHoncho:
    """Test _save_plan_state_to_honcho — registry dispatch → HTTP fallback."""

    @patch("plan_follow.tools.coordination._dispatch_honcho_tool")
    def test_registry_dispatch_succeeds_early_return(self, mock_dispatch):
        """Registry dispatch returns non-None → function returns immediately."""
        mock_dispatch.return_value = {"result": "ok"}

        _save_plan_state_to_honcho("plan-123", "task-1", "active")

        mock_dispatch.assert_called_once_with("honcho_conclude", {
            "conclusion": json.dumps({
                "source": "plan_follow",
                "plan_id": "plan-123",
                "task_id": "task-1",
                "status": "active",
            }),
            "target": "memory",
        })

    @patch("plan_follow.tools.coordination._dispatch_honcho_tool")
    @patch("urllib.request.urlopen")
    @patch("urllib.request.Request")
    def test_registry_returns_none_falls_back_to_http(
        self, mock_request, mock_urlopen, mock_dispatch
    ):
        """Registry dispatch returns None → falls back to HTTP save."""
        from plan_follow.tools.resolver import resolve_honcho_url, resolve_honcho_workspace

        mock_dispatch.return_value = None
        mock_request.return_value = MagicMock()
        mock_urlopen.return_value = MagicMock()

        _save_plan_state_to_honcho("plan-456", "task-2", "completed")

        # Verify HTTP request was made
        expected_url = (
            f"{resolve_honcho_url()}/v3/workspaces/{resolve_honcho_workspace()}/conclusions"
        )
        mock_request.assert_called_once()
        call_args, call_kwargs = mock_request.call_args
        assert call_args[0] == expected_url
        assert call_kwargs["headers"]["Content-Type"] == "application/json"
        mock_urlopen.assert_called_once()

    @patch("plan_follow.tools.coordination._dispatch_honcho_tool")
    @patch("urllib.request.urlopen")
    def test_http_fails_logs_warning(self, mock_urlopen, mock_dispatch, caplog):
        """HTTP fallback raises exception → logger.warning is called."""
        caplog.set_level("WARNING")
        mock_dispatch.return_value = None
        mock_urlopen.side_effect = ConnectionError("cannot connect")

        _save_plan_state_to_honcho("plan-789", "task-3", "failed")

        assert "Honcho save failed after retries (non-fatal)" in caplog.text
        assert "cannot connect" in caplog.text


# ─── _load_plan_state_from_honcho ──────────────────────────────────────────────


class TestLoadPlanStateFromHoncho:
    """Test _load_plan_state_from_honcho — registry dispatch → HTTP fallback."""

    @patch("plan_follow.tools.coordination._dispatch_honcho_tool")
    def test_registry_returns_json_format(self, mock_dispatch):
        """Registry dispatch returns conclusions with JSON format → returns plan_id."""
        mock_dispatch.return_value = {
            "conclusions": [
                {
                    "content": json.dumps({
                        "source": "plan_follow",
                        "plan_id": "plan-json-1",
                        "task_id": "task-1",
                        "status": "active",
                    })
                }
            ]
        }

        result = _load_plan_state_from_honcho()
        assert result == "plan-json-1"

    @patch("plan_follow.tools.coordination._dispatch_honcho_tool")
    def test_registry_returns_legacy_format(self, mock_dispatch):
        """Registry dispatch returns legacy content string → returns plan_id."""
        mock_dispatch.return_value = {
            "conclusions": [
                {"content": "plan_follow:plan-legacy-1:active=true"}
            ]
        }

        result = _load_plan_state_from_honcho()
        assert result == "plan-legacy-1"

    @patch("plan_follow.tools.coordination._dispatch_honcho_tool")
    def test_registry_returns_no_matching_plan(self, mock_dispatch):
        """No conclusion has plan_follow active → returns None."""
        mock_dispatch.return_value = {
            "conclusions": [
                {"content": json.dumps({"source": "other", "plan_id": "p1", "status": "active"})}
            ]
        }

        result = _load_plan_state_from_honcho()
        assert result is None

    @patch("plan_follow.tools.coordination._dispatch_honcho_tool")
    def test_registry_returns_empty_conclusions(self, mock_dispatch):
        """Empty conclusions list → returns None."""
        mock_dispatch.return_value = {"conclusions": []}
        result = _load_plan_state_from_honcho()
        assert result is None

    @patch("plan_follow.tools.coordination._dispatch_honcho_tool")
    def test_registry_returns_none_type_not_handled(self, mock_dispatch):
        """registry_result is not a dict → treats empty conclusions → None."""
        mock_dispatch.return_value = None
        result = _load_plan_state_from_honcho()
        assert result is None

    @patch("plan_follow.tools.coordination._dispatch_honcho_tool")
    def test_registry_no_active_plan_returns_none(self, mock_dispatch):
        """Plan exists but status is not 'active' → returns None."""
        mock_dispatch.return_value = {
            "conclusions": [
                {
                    "content": json.dumps({
                        "source": "plan_follow",
                        "plan_id": "plan-completed",
                        "status": "completed",
                    })
                }
            ]
        }
        result = _load_plan_state_from_honcho()
        assert result is None

    # ── HTTP fallback tests ──

    @patch("plan_follow.tools.coordination._dispatch_honcho_tool")
    @patch("urllib.request.urlopen")
    @patch("urllib.request.Request")
    def test_http_fallback_json_format(self, mock_request, mock_urlopen, mock_dispatch):
        """Registry returns None → HTTP fallback → JSON format → returns plan_id."""
        mock_dispatch.return_value = None

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps([
            {
                "content": json.dumps({
                    "source": "plan_follow",
                    "plan_id": "plan-http-1",
                    "task_id": "task-x",
                    "status": "active",
                })
            }
        ]).encode()
        mock_urlopen.return_value = mock_response
        mock_request.return_value = MagicMock()

        result = _load_plan_state_from_honcho()
        assert result == "plan-http-1"

    @patch("plan_follow.tools.coordination._dispatch_honcho_tool")
    @patch("urllib.request.urlopen")
    @patch("urllib.request.Request")
    def test_http_fallback_legacy_format(self, mock_request, mock_urlopen, mock_dispatch):
        """Registry returns None → HTTP fallback → legacy format → returns plan_id."""
        mock_dispatch.return_value = None

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps([
            {"content": "plan_follow:plan-legacy-http:active=true"}
        ]).encode()
        mock_urlopen.return_value = mock_response
        mock_request.return_value = MagicMock()

        result = _load_plan_state_from_honcho()
        assert result == "plan-legacy-http"

    @patch("plan_follow.tools.coordination._dispatch_honcho_tool")
    @patch("urllib.request.urlopen")
    @patch("urllib.request.Request")
    def test_http_fallback_no_plan_found(self, mock_request, mock_urlopen, mock_dispatch):
        """HTTP fallback finds no active plan → returns None."""
        mock_dispatch.return_value = None

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps([
            {"content": json.dumps({"source": "other", "plan_id": "p99", "status": "active"})}
        ]).encode()
        mock_urlopen.return_value = mock_response
        mock_request.return_value = MagicMock()

        result = _load_plan_state_from_honcho()
        assert result is None

    @patch("plan_follow.tools.coordination._dispatch_honcho_tool")
    @patch("urllib.request.urlopen")
    @patch("plan_follow.tools.coordination.logger")
    def test_http_fails_logs_warning(self, mock_logger, mock_urlopen, mock_dispatch):
        """HTTP fallback raises exception → logs warning, returns None."""
        mock_dispatch.return_value = None
        mock_urlopen.side_effect = ConnectionError("timeout")

        result = _load_plan_state_from_honcho()

        assert result is None
        mock_logger.warning.assert_called_once()
        assert "Honcho load failed after retries" in mock_logger.warning.call_args[0][0]


# ─── _git_commit_if_active ──────────────────────────────────────────────────────


class TestGitCommitIfActive:
    """Test _git_commit_if_active — auto Git-commit of plan JSON."""

    def test_no_git_dir_returns_early(self):
        """If .git dir does not exist under plans_dir, return early."""
        with patch("plan_follow.tools.coordination.resolve_plans_dir") as mock_resolve:
            mock_resolve.return_value = Path("/tmp/nonexistent_plans")
            # .git dir check: /tmp/nonexistent_plans/.git does not exist
            _git_commit_if_active({"plan_id": "p1", "current_task": "t1", "tasks": {}})
            # No subprocess calls should happen
            # We patched resolve_plans_dir, so subprocess.run should not be called

    def test_git_add_fails_returns_early(self):
        """If git add returns non-zero, return early."""
        plan = {"plan_id": "plan-1", "current_task": "task-1", "tasks": {"t1": {"status": "completed"}}}
        with patch("plan_follow.tools.coordination.resolve_plans_dir") as mock_resolve:
            mock_plans_dir = MagicMock(spec=Path)
            mock_resolve.return_value = mock_plans_dir
            mock_git_dir = MagicMock(spec=Path)
            mock_plans_dir.__truediv__.return_value = mock_git_dir
            mock_git_dir.exists.return_value = True

            with patch("subprocess.run") as mock_run:
                # git add fails
                mock_run.return_value.returncode = 1

                _git_commit_if_active(plan)

                assert mock_run.call_count >= 1

    def test_no_changes_returns_early(self):
        """If git diff --cached --stat is empty, return early."""
        plan = {"plan_id": "plan-1", "current_task": "task-1", "tasks": {"t1": {"status": "completed"}}}
        with patch("plan_follow.tools.coordination.resolve_plans_dir") as mock_resolve:
            mock_plans_dir = MagicMock(spec=Path)
            mock_resolve.return_value = mock_plans_dir
            mock_git_dir = MagicMock(spec=Path)
            mock_plans_dir.__truediv__.return_value = mock_git_dir
            mock_git_dir.exists.return_value = True

            with patch("subprocess.run") as mock_run:
                # First call (git add) succeeds
                # Second call (git diff) returns empty
                add_result = MagicMock()
                add_result.returncode = 0
                diff_result = MagicMock()
                diff_result.stdout = ""
                diff_result.stderr = ""
                mock_run.side_effect = [add_result, diff_result]

                _git_commit_if_active(plan)

                assert mock_run.call_count == 2

    def test_git_succeeds_commits(self):
        """If git add succeeds and there are changes, git commit is called."""
        plan = {"plan_id": "plan-1", "current_task": "task-1", "tasks": {"t1": {"status": "completed"}, "t2": {"status": "pending"}}}  # noqa: E501
        with patch("plan_follow.tools.coordination.resolve_plans_dir") as mock_resolve:
            mock_plans_dir = MagicMock(spec=Path)
            mock_resolve.return_value = mock_plans_dir
            mock_git_dir = MagicMock(spec=Path)
            mock_plans_dir.__truediv__.return_value = mock_git_dir
            mock_git_dir.exists.return_value = True

            with patch("subprocess.run") as mock_run:
                add_result = MagicMock()
                add_result.returncode = 0
                diff_result = MagicMock()
                diff_result.stdout = "1 file changed"
                diff_result.stderr = ""
                commit_result = MagicMock()
                commit_result.returncode = 0
                mock_run.side_effect = [add_result, diff_result, commit_result]

                _git_commit_if_active(plan)

                assert mock_run.call_count == 3
                # Check the commit call
                commit_call = mock_run.call_args_list[2]
                assert commit_call[0][0][:2] == ["git", "commit"]

    @patch("plan_follow.tools.coordination.logger")
    def test_exception_during_git_logs_debug(self, mock_logger):
        """Exception during git operations is caught and logged at debug."""
        plan = {"plan_id": "plan-1", "current_task": "task-1", "tasks": {}}
        with patch("plan_follow.tools.coordination.resolve_plans_dir") as mock_resolve:
            mock_plans_dir = MagicMock(spec=Path)
            mock_resolve.return_value = mock_plans_dir
            mock_git_dir = MagicMock(spec=Path)
            mock_plans_dir.__truediv__.return_value = mock_git_dir
            mock_git_dir.exists.return_value = True

            with patch("subprocess.run", side_effect=OSError("git not found")):
                _git_commit_if_active(plan)
                mock_logger.debug.assert_called_once_with("Auto Git-commit failed (best-effort)")


# ─── _auto_lock_task_files ──────────────────────────────────────────────────────


class TestAutoLockTaskFiles:
    """Test _auto_lock_task_files — auto-acquire locks for task files."""

    def test_no_files_returns_early(self):
        """If task has no files, return immediately without calling acquire_lock."""
        with patch("plan_follow.coord_state.acquire_lock") as mock_lock:
            _auto_lock_task_files({"files": []})
            mock_lock.assert_not_called()

        with patch("plan_follow.coord_state.acquire_lock") as mock_lock:
            _auto_lock_task_files({"name": "no-files"})
            mock_lock.assert_not_called()

    def test_acquires_locks_for_each_file(self):
        """For each file, acquire_lock is called with the file path and session_id."""
        files = ["file1.py", "file2.py", "file3.py"]
        with patch("plan_follow.coord_state.acquire_lock") as mock_lock:
            with patch("plan_follow.tools.coordination.get_session_id", return_value="sess-1"):
                _auto_lock_task_files({"files": files})
                assert mock_lock.call_count == 3
                mock_lock.assert_has_calls([
                    call("file1.py", "sess-1"),
                    call("file2.py", "sess-1"),
                    call("file3.py", "sess-1"),
                ])

    def test_exception_caught_and_logged(self, caplog):
        """Exception during locking is caught, logged at debug."""
        caplog.set_level("DEBUG")
        with patch("plan_follow.coord_state.acquire_lock", side_effect=ValueError("lock error")):
            _auto_lock_task_files({"files": ["f1.py"]})
            assert "Auto lock failed (best-effort)" in caplog.text


# ─── _auto_unlock_task_files ────────────────────────────────────────────────────


class TestAutoUnlockTaskFiles:
    """Test _auto_unlock_task_files — auto-release locks for task files."""

    def test_no_files_returns_early(self):
        """If task has no files, return immediately without calling release_lock."""
        with patch("plan_follow.coord_state.release_lock") as mock_unlock:
            _auto_unlock_task_files({"files": []})
            mock_unlock.assert_not_called()

        with patch("plan_follow.coord_state.release_lock") as mock_unlock:
            _auto_unlock_task_files({"name": "no-files"})
            mock_unlock.assert_not_called()

    def test_releases_locks_for_each_file(self):
        """For each file, release_lock is called with the file path and session_id."""
        files = ["f1.py", "f2.py"]
        with patch("plan_follow.coord_state.release_lock") as mock_unlock:
            with patch("plan_follow.tools.coordination.get_session_id", return_value="sess-2"):
                _auto_unlock_task_files({"files": files})
                assert mock_unlock.call_count == 2
                mock_unlock.assert_has_calls([
                    call("f1.py", "sess-2"),
                    call("f2.py", "sess-2"),
                ])

    def test_exception_caught_and_logged(self, caplog):
        """Exception during unlocking is caught, logged at debug."""
        caplog.set_level("DEBUG")
        with patch("plan_follow.coord_state.release_lock", side_effect=RuntimeError("unlock error")):
            _auto_unlock_task_files({"files": ["f.py"]})
            assert "Auto unlock failed (best-effort)" in caplog.text
