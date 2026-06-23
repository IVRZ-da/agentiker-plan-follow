"""Tests for tools/auto.py — Auto-Verify, Auto-Commit, Auto-Advance, Git tools.

Targets all functions in plan_follow.tools.auto to increase coverage
from ~28% towards >85%. Covers error paths, edge cases, and git operations
with real temporary repositories.
"""

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# ─── Helpers ───────────────────────────────────────────────────────────────────


def _init_git_repo(tmp_path: Path, name: str = "repo") -> Path:
    """Initialize a real git repo at tmp_path / name with user config."""
    repo = tmp_path / name
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=False)
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo, capture_output=True, check=False,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo, capture_output=True, check=False,
    )
    return repo


def _make_initial_commit(repo: Path) -> None:
    """Create an initial commit so HEAD exists."""
    readme = repo / "README.md"
    readme.write_text("# Test\n")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=False)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=repo, capture_output=True, check=False,
    )


def _make_task(**overrides) -> dict:
    base = {"id": "T001", "name": "Test Task", "status": "pending",
            "files": ["test.py"], "depends_on": []}
    base.update(overrides)
    return base


def _make_plan(**overrides) -> dict:
    base = {
        "plan_id": "plan-001",
        "name": "Test Plan",
        "goal": "Test goal",
        "tasks": {"T001": _make_task(id="T001"), "T002": _make_task(id="T002")},
        "repo": "",
        "repos": [],
    }
    base.update(overrides)
    return base


# ─── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def git_repo(tmp_path):
    """Fixture that yields a real initialized git repo."""
    return _init_git_repo(tmp_path)


@pytest.fixture
def git_repo_with_commit(git_repo):
    """Fixture that yields a git repo with an initial commit."""
    _make_initial_commit(git_repo)
    return git_repo


# ═══════════════════════════════════════════════════════════════════════════════
# dispatch_review
# ═══════════════════════════════════════════════════════════════════════════════


class TestDispatchReview:
    """dispatch_review(profile_name, task, depth)"""

    def test_dispatch_ready(self):
        """Happy path: returns ready status."""
        from plan_follow.tools.auto import dispatch_review

        task = {"id": "T001", "name": "test", "files": ["src/main.py"]}
        with patch(
            "plan_follow.plan_review.dispatch_review",
            return_value={"status": "ready", "message": "Review ready"},
        ):
            result = dispatch_review("unit-test", task, "normal")
        assert result["status"] == "ready"

    def test_dispatch_skipped_no_files(self):
        """Returns skipped when task has no files."""
        from plan_follow.tools.auto import dispatch_review

        task = {"id": "T001", "name": "test", "files": []}
        with patch(
            "plan_follow.plan_review.dispatch_review",
            return_value={"status": "skipped", "message": "No files to review"},
        ):
            result = dispatch_review("unit-test", task, "normal")
        assert result["status"] == "skipped"

    def test_dispatch_error_exception(self):
        """Exception from inner dispatch propagates up."""
        from plan_follow.tools.auto import dispatch_review

        task = {"id": "T001", "name": "test", "files": ["x.py"]}
        with patch(
            "plan_follow.plan_review.dispatch_review",
            side_effect=RuntimeError("boom"),
        ):
            with pytest.raises(RuntimeError, match="boom"):
                dispatch_review("unit-test", task, "deep")


# ═══════════════════════════════════════════════════════════════════════════════
# _find_next_linear
# ═══════════════════════════════════════════════════════════════════════════════


class TestFindNextLinear:
    """_find_next_linear(tasks, completed_task_id) — pure logic, no IO."""

    def test_finds_next_pending_with_satisfied_deps(self):
        """Returns the next task that is pending and whose deps are done."""
        from plan_follow.tools.auto import _find_next_linear

        tasks = {
            "T001": {"status": "completed"},
            "T002": {"status": "pending", "depends_on": ["T001"]},
            "T003": {"status": "pending", "depends_on": ["T002"]},
        }
        assert _find_next_linear(tasks, "T001") == "T002"

    def test_skips_non_pending_tasks(self):
        """Skips over in_progress / blocked tasks; if deps unsatisfied for others, returns None."""
        from plan_follow.tools.auto import _find_next_linear

        tasks = {
            "T001": {"status": "completed"},
            "T002": {"status": "in_progress", "depends_on": ["T001"]},
            "T003": {"status": "pending", "depends_on": ["T002"]},
        }
        # T002 is in_progress (not pending) → skipped
        # T003 depends on T002 which is NOT completed → deps unsatisfied → skipped
        result = _find_next_linear(tasks, "T001")
        assert result is None

    def test_returns_none_when_all_done(self):
        """All tasks after completed_idx are done → returns None."""
        from plan_follow.tools.auto import _find_next_linear

        tasks = {
            "T001": {"status": "completed"},
            "T002": {"status": "completed"},
            "T003": {"status": "completed"},
        }
        assert _find_next_linear(tasks, "T002") is None

    def test_skips_pending_with_unmet_deps(self):
        """Skips a pending task whose deps are not all completed."""
        from plan_follow.tools.auto import _find_next_linear

        tasks = {
            "T001": {"status": "completed"},
            "T002": {"status": "pending", "depends_on": ["T001"]},
            "T003": {"status": "pending", "depends_on": ["T999"]},
        }
        # T002 deps satisfied, T003 deps not satisfied
        result = _find_next_linear(tasks, "T001")
        assert result == "T002"

    def test_value_error_when_task_id_not_found(self):
        """Raises ValueError if completed_task_id is not in tasks."""
        from plan_follow.tools.auto import _find_next_linear

        tasks = {"T001": {"status": "completed"}}
        with pytest.raises(ValueError):
            _find_next_linear(tasks, "T999")


# ═══════════════════════════════════════════════════════════════════════════════
# _find_next_parallel
# ═══════════════════════════════════════════════════════════════════════════════


class TestFindNextParallel:
    """_find_next_parallel(tasks, groups, completed_task_id) — pure logic."""

    def test_returns_none_when_task_not_in_any_group(self):
        """completed_task_id not found in any group → None."""
        from plan_follow.tools.auto import _find_next_parallel

        tasks = {"T001": {"status": "pending"}}
        groups = {"G1": {"tasks": ["T002"]}}
        assert _find_next_parallel(tasks, groups, "T001") is None

    def test_returns_next_incomplete_in_same_group(self):
        """Still running tasks in the same group → return first incomplete."""
        from plan_follow.tools.auto import _find_next_parallel

        tasks = {
            "T001": {"status": "completed"},
            "T002": {"status": "in_progress"},
            "T003": {"status": "pending"},
        }
        groups = {"G1": {"tasks": ["T001", "T002", "T003"]}}
        # T001 completed, next incomplete is T002
        assert _find_next_parallel(tasks, groups, "T001") == "T002"

    def test_group_done_moves_to_next_pending_group(self):
        """Current group fully done → first task of next pending group."""
        from plan_follow.tools.auto import _find_next_parallel

        tasks = {
            "T001": {"status": "completed"},
            "T002": {"status": "completed"},
            "T003": {"status": "pending"},
        }
        groups = {
            "G1": {"tasks": ["T001", "T002"], "status": "completed"},
            "G2": {"tasks": ["T003"], "status": "pending"},
        }
        assert _find_next_parallel(tasks, groups, "T002") == "T003"

    def test_all_groups_done_returns_none(self):
        """All groups completed → None."""
        from plan_follow.tools.auto import _find_next_parallel

        tasks = {
            "T001": {"status": "completed"},
            "T002": {"status": "completed"},
        }
        groups = {
            "G1": {"tasks": ["T001"], "status": "completed"},
            "G2": {"tasks": ["T002"], "status": "completed"},
        }
        assert _find_next_parallel(tasks, groups, "T002") is None

    def test_group_done_but_next_group_not_pending(self):
        """Next group is not pending → stop (return None)."""
        from plan_follow.tools.auto import _find_next_parallel

        tasks = {
            "T001": {"status": "completed"},
            "T002": {"status": "in_progress"},
        }
        groups = {
            "G1": {"tasks": ["T001"], "status": "completed"},
            "G2": {"tasks": ["T002"], "status": "in_progress"},
        }
        # G1 done, but G2 is in_progress, not pending
        assert _find_next_parallel(tasks, groups, "T001") is None

    def test_no_incomplete_tasks_in_group_returns_none(self):
        """Group has tasks but none are non-completed."""
        from plan_follow.tools.auto import _find_next_parallel

        tasks = {"T001": {"status": "completed"}}
        groups = {"G1": {"tasks": ["T001"], "status": "completed"}}
        assert _find_next_parallel(tasks, groups, "T001") is None


# ═══════════════════════════════════════════════════════════════════════════════
# auto_advance
# ═══════════════════════════════════════════════════════════════════════════════


class TestAutoAdvance:
    """auto_advance(plan, completed_task_id)"""

    def test_error_no_plan(self):
        """No plan → error with message."""
        from plan_follow.tools.auto import auto_advance

        result = auto_advance(None, "T001")
        assert result["status"] == "error"
        assert "No plan" in result["message"]

    def test_error_no_task_id(self):
        """No completed_task_id → error."""
        from plan_follow.tools.auto import auto_advance

        result = auto_advance({"tasks": {}}, None)
        assert result["status"] == "error"
        assert "No completed task ID" in result["message"]

    def test_error_empty_task_id(self):
        """Empty string as task_id → error."""
        from plan_follow.tools.auto import auto_advance

        result = auto_advance({"tasks": {}}, "")
        assert result["status"] == "error"
        assert "No completed task ID" in result["message"]

    def test_error_no_tasks(self):
        """Plan with empty tasks → error."""
        from plan_follow.tools.auto import auto_advance

        result = auto_advance({"tasks": {}}, "T001")
        assert result["status"] == "error"
        assert "no tasks" in result["message"].lower()

    def test_error_task_not_found(self):
        """completed_task_id not in plan tasks → error."""
        from plan_follow.tools.auto import auto_advance

        plan = {"tasks": {"T001": _make_task(id="T001")}}
        result = auto_advance(plan, "T999")
        assert result["status"] == "error"
        assert "not found" in result["message"]

    def test_linear_advance(self):
        """Linear mode: advances to next task."""
        from plan_follow.tools.auto import auto_advance

        plan = _make_plan(tasks={
            "T001": _make_task(id="T001", status="completed"),
            "T002": _make_task(id="T002", status="pending"),
        })
        result = auto_advance(plan, "T001")
        assert result["status"] == "advanced"
        assert result["next_task"] == "T002"

    def test_parallel_advance(self):
        """Parallel mode: advances within group."""
        from plan_follow.tools.auto import auto_advance

        plan = _make_plan(
            tasks={
                "T001": _make_task(id="T001", status="completed"),
                "T002": _make_task(id="T002", status="pending"),
            },
            parallel_groups={
                "G1": {"tasks": ["T001", "T002"], "status": "in_progress"},
            },
        )
        result = auto_advance(plan, "T001")
        assert result["status"] == "advanced"
        assert result["next_task"] == "T002"

    def test_all_completed(self):
        """All tasks done → completed status."""
        from plan_follow.tools.auto import auto_advance

        plan = _make_plan(tasks={
            "T001": _make_task(id="T001", status="completed"),
        })
        result = auto_advance(plan, "T001")
        assert result["status"] == "completed"
        assert result["next_task"] is None
        assert "All tasks completed" in result["message"]


# ═══════════════════════════════════════════════════════════════════════════════
# auto_verify_task
# ═══════════════════════════════════════════════════════════════════════════════


class TestAutoVerifyTask:
    """auto_verify_task(verify_cmd, timeout)"""

    def test_skipped_empty_cmd(self):
        """Empty command → skipped."""
        from plan_follow.tools.auto import auto_verify_task

        result = auto_verify_task("")
        assert result["status"] == "skipped"

    def test_skipped_whitespace_cmd(self):
        """Whitespace-only command → skipped."""
        from plan_follow.tools.auto import auto_verify_task

        result = auto_verify_task("   ")
        assert result["status"] == "skipped"

    def test_passed(self):
        """Command exits with 0 → passed."""
        from plan_follow.tools.auto import auto_verify_task

        result = auto_verify_task("echo ok", timeout=5)
        assert result["status"] == "passed"
        assert result["exit_code"] == 0

    def test_failed(self):
        """Command exits with non-zero → failed."""
        from plan_follow.tools.auto import auto_verify_task

        result = auto_verify_task("false", timeout=5)
        assert result["status"] == "failed"
        assert result["exit_code"] != 0

    def test_stderr_captured(self):
        """Stderr output is captured in result."""
        from plan_follow.tools.auto import auto_verify_task

        result = auto_verify_task("echo 'hello' >&2 && false", timeout=5)
        assert result["status"] == "failed"
        assert "hello" in result["stderr"]

    @patch("subprocess.run", side_effect=subprocess.TimeoutExpired(
        cmd="bash -c verify", timeout=5,
    ))
    def test_timeout(self, mock_run):
        """Subprocess timeout → failed with message."""
        from plan_follow.tools.auto import auto_verify_task

        result = auto_verify_task("sleep 100", timeout=5)
        assert result["status"] == "failed"
        assert "timeout" in result.get("message", "").lower()


# ═══════════════════════════════════════════════════════════════════════════════
# _commit_in_repo
# ═══════════════════════════════════════════════════════════════════════════════


class TestCommitInRepo:
    """_commit_in_repo(repo, task_id, files)"""

    def test_skipped_no_git_dir(self, tmp_path):
        """No .git directory → skipped."""
        from plan_follow.tools.auto import _commit_in_repo

        result = _commit_in_repo(str(tmp_path / "nonexistent"), "T001", ["f.py"])
        assert result["status"] == "skipped"
        assert "No .git" in result["message"]

    def test_commits_successfully(self, git_repo_with_commit):
        """Creates a valid commit."""
        from plan_follow.tools.auto import _commit_in_repo

        repo = git_repo_with_commit
        test_file = repo / "test.py"
        test_file.write_text("x = 1\n")

        result = _commit_in_repo(str(repo), "T001", ["test.py"])
        assert result["status"] == "committed"
        assert result["repo"] == str(repo)

    def test_skipped_no_changes(self, git_repo_with_commit):
        """No changes to stage → skipped."""
        from plan_follow.tools.auto import _commit_in_repo

        repo = git_repo_with_commit
        result = _commit_in_repo(str(repo), "T001", ["nonexistent.py"])
        assert result["status"] == "skipped"
        assert "No changes" in result["message"]


# ═══════════════════════════════════════════════════════════════════════════════
# auto_commit
# ═══════════════════════════════════════════════════════════════════════════════


class TestAutoCommit:
    """auto_commit(task_id, files, repo, repos)"""

    def test_skipped_no_files(self):
        """No files → skipped."""
        from plan_follow.tools.auto import auto_commit

        result = auto_commit("T001", [])
        assert result["status"] == "skipped"
        assert "No files" in result["message"]

    def test_skipped_no_repo(self):
        """No repo or repos → skipped."""
        from plan_follow.tools.auto import auto_commit

        result = auto_commit("T001", ["f.py"])
        assert result["status"] == "skipped"
        assert "No git repo" in result["message"]

    def test_commits_single_repo(self, git_repo_with_commit):
        """Commits to a single repo given as string."""
        from plan_follow.tools.auto import auto_commit

        repo = git_repo_with_commit
        (repo / "f.py").write_text("code\n")

        result = auto_commit("T001", ["f.py"], repo=str(repo))
        assert result["status"] == "committed"
        assert result["committed"] == 1

    def test_commits_multiple_repos(self, git_repo_with_commit, tmp_path):
        """Commits across multiple repos."""
        from plan_follow.tools.auto import auto_commit

        repo1 = git_repo_with_commit
        repo2 = _init_git_repo(tmp_path, "repo2")
        _make_initial_commit(repo2)

        (repo1 / "a.py").write_text("a\n")
        (repo2 / "b.py").write_text("b\n")

        result = auto_commit(
            "T001", ["a.py", "b.py"], repos=[str(repo1), str(repo2)],
        )
        assert result["status"] == "committed"
        assert result["committed"] == 2

    def test_no_repos_list_empty_configured(self):
        """Empty repos list → skipped (no git repo)."""
        from plan_follow.tools.auto import auto_commit

        result = auto_commit("T001", ["f.py"], repos=[])
        assert result["status"] == "skipped"
        assert "No git repo" in result["message"]


# ═══════════════════════════════════════════════════════════════════════════════
# auto_push
# ═══════════════════════════════════════════════════════════════════════════════


class TestAutoPush:
    """auto_push(repos, remote, branch)"""

    def test_skipped_no_git(self, tmp_path):
        """Repo without .git → skipped."""
        from plan_follow.tools.auto import auto_push

        result = auto_push([str(tmp_path / "no_git")])
        assert result["results"][0]["status"] == "skipped"
        assert "No .git" in result["results"][0]["message"]

    def test_failed_push_no_remote(self, git_repo_with_commit):
        """Valid repo but no remote → push fails."""
        from plan_follow.tools.auto import auto_push

        repo = git_repo_with_commit
        (repo / "x.py").write_text("x\n")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=False)
        subprocess.run(
            ["git", "commit", "-m", "msg"],
            cwd=repo, capture_output=True, check=False,
        )

        result = auto_push([str(repo)], remote="origin")
        assert result["results"][0]["status"] == "failed"

    def test_push_with_explicit_branch(self, git_repo_with_commit):
        """Branch parameter passed to push."""
        from plan_follow.tools.auto import auto_push

        repo = git_repo_with_commit
        (repo / "y.py").write_text("y\n")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=False)
        subprocess.run(
            ["git", "commit", "-m", "msg"],
            cwd=repo, capture_output=True, check=False,
        )

        result = auto_push([str(repo)], remote="origin", branch="main")
        assert result["results"][0]["status"] == "failed"  # no remote


# ═══════════════════════════════════════════════════════════════════════════════
# get_git_status
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetGitStatus:
    """get_git_status(repo)"""

    def test_no_git_dir(self, tmp_path):
        """No .git → no_git status."""
        from plan_follow.tools.auto import get_git_status

        result = get_git_status(str(tmp_path / "empty"))
        assert result["status"] == "no_git"

    def test_ok_clean_repo(self, git_repo_with_commit):
        """Clean repo → ok with branch and zero dirty files."""
        from plan_follow.tools.auto import get_git_status

        repo = git_repo_with_commit
        result = get_git_status(str(repo))
        assert result["status"] == "ok"
        assert result["dirty"] is False
        assert result["dirty_files"] == 0
        assert result["branch"] in ("main", "master")

    def test_ok_dirty_repo(self, git_repo_with_commit):
        """Repo with uncommitted changes → dirty is True."""
        from plan_follow.tools.auto import get_git_status

        repo = git_repo_with_commit
        (repo / "new.py").write_text("new\n")

        result = get_git_status(str(repo))
        assert result["status"] == "ok"
        assert result["dirty"] is True
        assert result["dirty_files"] > 0


# ═══════════════════════════════════════════════════════════════════════════════
# git_sync
# ═══════════════════════════════════════════════════════════════════════════════


class TestGitSync:
    """git_sync(repo, task_id, files, remote, branch, push_flag)"""

    def test_skipped_no_git(self, tmp_path):
        """No .git → skipped."""
        from plan_follow.tools.auto import git_sync

        result = git_sync(str(tmp_path / "no_git"), "T001", ["f.py"])
        assert result["status"] == "skipped"
        assert "No .git" in result["message"]

    def test_sync_without_push(self, git_repo_with_commit):
        """Sync with push_flag=False: pull + add + commit, no push."""
        from plan_follow.tools.auto import git_sync

        repo = git_repo_with_commit
        (repo / "sync_test.py").write_text("sync\n")

        result = git_sync(str(repo), "T001", ["sync_test.py"], push_flag=False)
        # pull fails (no remote), add + commit succeed → overall 'failed'
        # but commit step should be 'ok'
        step_statuses = {s["step"]: s["status"] for s in result["steps"]}
        assert step_statuses["commit"] == "ok"

    def test_sync_with_push_no_remote(self, git_repo_with_commit):
        """Sync with push_flag=True but no remote → overall status is failed."""
        from plan_follow.tools.auto import git_sync

        repo = git_repo_with_commit
        (repo / "push_test.py").write_text("push\n")

        result = git_sync(str(repo), "T001", ["push_test.py"], push_flag=True)
        # pull fails (no remote), push fails — overall failed
        # but the add + commit steps may succeed
        assert result["status"] == "failed"

    def test_sync_no_changes_to_commit(self, git_repo_with_commit):
        """Sync with no staged changes → commit step is skipped."""
        from plan_follow.tools.auto import git_sync

        repo = git_repo_with_commit
        result = git_sync(str(repo), "T001", ["nonexistent.py"], push_flag=False)
        commit_step = [s for s in result["steps"] if s["step"] == "commit"]
        assert commit_step
        assert commit_step[0]["status"] == "skipped"


# ═══════════════════════════════════════════════════════════════════════════════
# git_stash
# ═══════════════════════════════════════════════════════════════════════════════


class TestGitStash:
    """git_stash(repo, action, message)"""

    def test_skipped_no_git(self, tmp_path):
        """No .git → skipped."""
        from plan_follow.tools.auto import git_stash

        result = git_stash(str(tmp_path / "no_git"), "push")
        assert result["status"] == "skipped"

    def test_push_pop(self, git_repo_with_commit):
        """Push dirty changes, then pop them back."""
        from plan_follow.tools.auto import git_stash

        repo = git_repo_with_commit
        (repo / "dirty.py").write_text("dirty\n")

        push_result = git_stash(str(repo), "push", message="test stash")
        assert push_result["status"] == "ok"
        assert push_result["stashed"] is True

        pop_result = git_stash(str(repo), "pop")
        assert pop_result["status"] == "ok"

    def test_push_no_changes(self, git_repo_with_commit):
        """Push with no dirty files → status ok."""
        from plan_follow.tools.auto import git_stash

        repo = git_repo_with_commit
        result = git_stash(str(repo), "push")
        assert result["status"] == "ok"

    def test_list(self, git_repo_with_commit):
        """List stashes on a clean repo."""
        from plan_follow.tools.auto import git_stash

        repo = git_repo_with_commit
        result = git_stash(str(repo), "list")
        assert result["status"] == "ok"
        # stashes string could be empty or contain entries

    def test_unknown_action(self, git_repo_with_commit):
        """Unknown action → error with message."""
        from plan_follow.tools.auto import git_stash

        repo = git_repo_with_commit
        result = git_stash(str(repo), "unknown_action_xyz")
        assert result["status"] == "error"
        assert "Unknown action" in result["message"]


# ═══════════════════════════════════════════════════════════════════════════════
# git_branch
# ═══════════════════════════════════════════════════════════════════════════════


class TestGitBranch:
    """git_branch(repo, action, name, start_point)"""

    def test_skipped_no_git(self, tmp_path):
        """No .git → skipped."""
        from plan_follow.tools.auto import git_branch

        result = git_branch(str(tmp_path / "no_git"), "current")
        assert result["status"] == "skipped"

    def test_current(self, git_repo_with_commit):
        """Current branch on a fresh repo is main."""
        from plan_follow.tools.auto import git_branch

        repo = git_repo_with_commit
        result = git_branch(str(repo), "current")
        assert result["status"] == "ok"
        # could be 'main' or 'master'
        assert result["branch"]

    def test_list(self, git_repo_with_commit):
        """List branches."""
        from plan_follow.tools.auto import git_branch

        repo = git_repo_with_commit
        result = git_branch(str(repo), "list")
        assert result["status"] == "ok"
        assert result["branches"] is not None

    def test_create_and_delete(self, git_repo_with_commit):
        """Create a branch, then delete it."""
        from plan_follow.tools.auto import git_branch

        repo = git_repo_with_commit
        create_result = git_branch(str(repo), "create", name="feature/test")
        assert create_result["status"] == "ok"

        delete_result = git_branch(str(repo), "delete", name="feature/test")
        assert delete_result["status"] == "ok"

    def test_switch(self, git_repo_with_commit):
        """Create a branch, switch to it, verify."""
        from plan_follow.tools.auto import git_branch

        repo = git_repo_with_commit
        git_branch(str(repo), "create", name="feature/switch")
        switch_result = git_branch(str(repo), "switch", name="feature/switch")
        assert switch_result["status"] == "ok"

        current = git_branch(str(repo), "current")
        assert current["branch"] == "feature/switch"

    def test_create_with_start_point(self, git_repo_with_commit):
        """Create branch with explicit start_point."""
        from plan_follow.tools.auto import git_branch

        repo = git_repo_with_commit
        result = git_branch(
            str(repo), "create", name="feature/from-start",
            start_point="HEAD",
        )
        assert result["status"] == "ok"

    def test_unknown_action(self, git_repo_with_commit):
        """Unknown action → error."""
        from plan_follow.tools.auto import git_branch

        repo = git_repo_with_commit
        result = git_branch(str(repo), "bogus_action")
        assert result["status"] == "error"
        assert "Unknown action" in result["message"]


# ═══════════════════════════════════════════════════════════════════════════════
# git_tag
# ═══════════════════════════════════════════════════════════════════════════════


class TestGitTag:
    """git_tag(repo, tag_name, message, action)"""

    def test_skipped_no_git(self, tmp_path):
        """No .git → skipped."""
        from plan_follow.tools.auto import git_tag

        result = git_tag(str(tmp_path / "no_git"), "v1.0", action="create")
        assert result["status"] == "skipped"

    def test_create_annotated_tag(self, git_repo_with_commit):
        """Create an annotated tag with message."""
        from plan_follow.tools.auto import git_tag

        repo = git_repo_with_commit
        result = git_tag(str(repo), "v1.0", message="Version 1.0", action="create")
        assert result["status"] == "ok"

    def test_create_lightweight_tag(self, git_repo_with_commit):
        """Create lightweight tag (no message)."""
        from plan_follow.tools.auto import git_tag

        repo = git_repo_with_commit
        result = git_tag(str(repo), "v2.0", action="create")
        assert result["status"] == "ok"

    def test_list_tags(self, git_repo_with_commit):
        """List tags after creating one."""
        from plan_follow.tools.auto import git_tag

        repo = git_repo_with_commit
        git_tag(str(repo), "v3.0", action="create")
        result = git_tag(str(repo), "", action="list")
        assert result["status"] == "ok"
        assert "v3.0" in result["tags"]

    def test_delete_tag(self, git_repo_with_commit):
        """Delete a tag."""
        from plan_follow.tools.auto import git_tag

        repo = git_repo_with_commit
        git_tag(str(repo), "v4.0", action="create")
        result = git_tag(str(repo), "v4.0", action="delete")
        assert result["status"] == "ok"

    def test_unknown_action(self, git_repo_with_commit):
        """Unknown action → error."""
        from plan_follow.tools.auto import git_tag

        repo = git_repo_with_commit
        result = git_tag(str(repo), "v1.0", action="fly")
        assert result["status"] == "error"
        assert "Unknown action" in result["message"]


# ═══════════════════════════════════════════════════════════════════════════════
# check_drift
# ═══════════════════════════════════════════════════════════════════════════════


class TestCheckDrift:
    """check_drift()"""

    def test_no_active_plan(self):
        """No active plan → empty list."""
        from plan_follow.tools.auto import check_drift

        with patch("plan_follow.tools.auto._get_active_plan", return_value=None):
            result = check_drift()
        assert result == []

    def test_no_current_task(self):
        """Plan without current_task → empty list."""
        from plan_follow.tools.auto import check_drift

        plan = {"plan_id": "p1", "tasks": {}}
        with patch("plan_follow.tools.auto._get_active_plan", return_value=plan):
            result = check_drift()
        assert result == []

    def test_task_not_found(self):
        """current_task references a non-existent task → empty list."""
        from plan_follow.tools.auto import check_drift

        plan = {"plan_id": "p1", "current_task": "T999", "tasks": {}}
        with patch("plan_follow.tools.auto._get_active_plan", return_value=plan):
            result = check_drift()
        assert result == []

    def test_no_repos(self):
        """No repos in plan → empty list."""
        from plan_follow.tools.auto import check_drift

        plan = {
            "plan_id": "p1",
            "current_task": "T001",
            "tasks": {"T001": {"files": ["allowed.py"]}},
        }
        with patch("plan_follow.tools.auto._get_active_plan", return_value=plan):
            result = check_drift()
        assert result == []


# ═══════════════════════════════════════════════════════════════════════════════
# _get_repos
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetRepos:
    """_get_repos(plan) — helper for check_drift."""

    def test_returns_repos_list(self):
        """Returns the repos list when present."""
        from plan_follow.tools.auto import _get_repos

        plan = {"repos": ["/a", "/b"]}
        assert _get_repos(plan) == ["/a", "/b"]

    def test_returns_single_repo(self):
        """Returns single repo as a list."""
        from plan_follow.tools.auto import _get_repos

        plan = {"repo": "/single"}
        assert _get_repos(plan) == ["/single"]

    def test_repos_overrides_repo(self):
        """repos list takes precedence over single repo."""
        from plan_follow.tools.auto import _get_repos

        plan = {"repos": ["/a", "/b"], "repo": "/single"}
        result = _get_repos(plan)
        assert result == ["/a", "/b"]

    def test_returns_empty_when_none(self):
        """No repos or repo → empty list."""
        from plan_follow.tools.auto import _get_repos

        plan = {}
        assert _get_repos(plan) == []

    def test_returns_empty_when_empty_list(self):
        """Empty repos list → empty list."""
        from plan_follow.tools.auto import _get_repos

        plan = {"repos": []}
        assert _get_repos(plan) == []


# ═══════════════════════════════════════════════════════════════════════════════
# auto_commit_task (alias)
# ═══════════════════════════════════════════════════════════════════════════════


class TestAutoCommitTaskAlias:
    """auto_commit_task = auto_commit"""

    def test_alias_exists(self):
        """auto_commit_task is the same function as auto_commit."""
        from plan_follow.tools.auto import auto_commit, auto_commit_task

        assert auto_commit_task is auto_commit


# ═══════════════════════════════════════════════════════════════════════════════
# Exception-handler edge cases (subprocess.run raises)
# ═══════════════════════════════════════════════════════════════════════════════


class TestExceptionHandlers:
    """Cover the `except Exception` branches in every function."""

    def test_auto_verify_task_exception(self):
        """auto_verify_task: subprocess.run raises → failed with error message."""
        from plan_follow.tools.auto import auto_verify_task

        with patch("subprocess.run", side_effect=OSError("mock error")):
            result = auto_verify_task("echo hi", timeout=5)
        assert result["status"] == "failed"
        assert "mock error" in result["message"]

    def test_commit_in_repo_exception(self, tmp_path):
        """_commit_in_repo: subprocess.run raises → error with message."""
        from plan_follow.tools.auto import _commit_in_repo

        repo = _init_git_repo(tmp_path)
        _make_initial_commit(repo)

        with patch("subprocess.run", side_effect=OSError("add failed")):
            result = _commit_in_repo(str(repo), "T001", ["x.py"])
        assert result["status"] == "error"
        assert "add failed" in result["message"]

    def test_auto_commit_failed_branch(self, tmp_path):
        """auto_commit: when all repos fail → failed status."""
        from plan_follow.tools.auto import auto_commit

        repo = _init_git_repo(tmp_path)
        _make_initial_commit(repo)
        (repo / "x.py").write_text("x\n")

        with patch(
            "plan_follow.tools.auto._commit_in_repo",
            return_value={"status": "failed", "repo": str(repo), "message": "nope"},
        ):
            result = auto_commit("T001", ["x.py"], repo=str(repo))
        assert result["status"] == "failed"
        assert "repo(s) failed" in result["message"]

    def test_auto_push_exception(self, tmp_path):
        """auto_push: subprocess.run raises → error with message."""
        from plan_follow.tools.auto import auto_push

        repo = _init_git_repo(tmp_path)
        _make_initial_commit(repo)

        with patch("subprocess.run", side_effect=OSError("push error")):
            result = auto_push([str(repo)])
        assert result["results"][0]["status"] == "error"
        assert "push error" in result["results"][0]["message"]

    def test_get_git_status_exception(self, tmp_path):
        """get_git_status: subprocess.run raises → error status."""
        from plan_follow.tools.auto import get_git_status

        repo = _init_git_repo(tmp_path)
        _make_initial_commit(repo)

        with patch("subprocess.run", side_effect=OSError("status error")):
            result = get_git_status(str(repo))
        assert result["status"] == "error"
        assert "status error" in result["error"]

    def test_git_sync_exception(self, tmp_path):
        """git_sync: subprocess.run raises → error status."""
        from plan_follow.tools.auto import git_sync

        repo = _init_git_repo(tmp_path)
        _make_initial_commit(repo)

        with patch("subprocess.run", side_effect=OSError("sync error")):
            result = git_sync(str(repo), "T001", ["x.py"])
        assert result["status"] == "error"
        assert "sync error" in result["error"]

    def test_git_stash_exception(self, tmp_path):
        """git_stash: subprocess.run raises → error status."""
        from plan_follow.tools.auto import git_stash

        repo = _init_git_repo(tmp_path)
        _make_initial_commit(repo)

        with patch("subprocess.run", side_effect=OSError("stash error")):
            result = git_stash(str(repo), "push")
        assert result["status"] == "error"
        assert "stash error" in result["error"]

    def test_git_branch_exception(self, tmp_path):
        """git_branch: subprocess.run raises → error status."""
        from plan_follow.tools.auto import git_branch

        repo = _init_git_repo(tmp_path)
        _make_initial_commit(repo)

        with patch("subprocess.run", side_effect=OSError("branch error")):
            result = git_branch(str(repo), "current")
        assert result["status"] == "error"
        assert "branch error" in result["error"]

    def test_git_tag_exception(self, tmp_path):
        """git_tag: subprocess.run raises → error status."""
        from plan_follow.tools.auto import git_tag

        repo = _init_git_repo(tmp_path)
        _make_initial_commit(repo)

        with patch("subprocess.run", side_effect=OSError("tag error")):
            result = git_tag(str(repo), "v1", action="create")
        assert result["status"] == "error"
        assert "tag error" in result["error"]

    def test_check_drift_with_real_repo(self, git_repo_with_commit):
        """check_drift: real repo with unplanned tracked file modification → detected as drift."""
        from plan_follow.tools.auto import check_drift

        repo = git_repo_with_commit
        # Create & commit a file, then modify it — git diff HEAD will show the change
        planned = repo / "planned.py"
        planned.write_text("original\n")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=False)
        subprocess.run(
            ["git", "commit", "-m", "add planned"],
            cwd=repo, capture_output=True, check=False,
        )

        # Create & commit a file that becomes un-tracked-by-plan after modification
        unplanned = repo / "drift.txt"
        unplanned.write_text("original\n")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=False)
        subprocess.run(
            ["git", "commit", "-m", "add drift"],
            cwd=repo, capture_output=True, check=False,
        )

        # Now modify the unplanned file — git diff HEAD shows it
        unplanned.write_text("modified\n")

        plan = {
            "plan_id": "p1",
            "current_task": "T001",
            "tasks": {
                "T001": {
                    "files": ["planned.py"],
                },
            },
            "repos": [str(repo)],
        }
        with patch("plan_follow.tools.auto._get_active_plan", return_value=plan):
            result = check_drift()
        # drift.txt is modified and not in allowed_files
        assert "drift.txt" in result
