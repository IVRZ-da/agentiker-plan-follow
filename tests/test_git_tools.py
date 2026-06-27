"""Tests for tools/git.py — git tool handlers (42% → 90%+ coverage)."""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add plugins root to path so plan_follow is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from plan_follow.tools.git import (
    plan_git_branch_tool,
    plan_git_init_tool,
    plan_git_push_tool,
    plan_git_stash_tool,
    plan_git_status_tool,
    plan_git_sync_tool,
    plan_git_tag_tool,
    plan_history_tool,
    plan_pr_create_tool,
)

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _fmt_ok(d, **kw):
    """Replicate conftest's fmt_ok mock for assertion helpers."""
    return json.dumps(d, ensure_ascii=False)


def _fmt_err(m, **kw):
    return json.dumps({"error": m})


def _fmt_info(m, **kw):
    return json.dumps({"info": m, "status": "no_active_plan", "message": m})


def _parse(resp: str) -> dict:
    """Parse the JSON string returned by the (mocked) fmt_* functions."""
    return json.loads(resp)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def mock_plan_core():
    """Replace plan_core reference in tools.git with a MagicMock.

    This intercepts all attribute access (PLANS_DIR, get_current_task,
    _get_active_plan, _get_repos, auto_push, get_git_status, git_sync,
    git_stash, git_branch, git_tag) so tests can control return values.
    """
    with patch("plan_follow.tools.git.plan_core") as m:
        m.PLANS_DIR = Path("/tmp/test_hermes_plans")
        m.get_current_task.return_value = {"plan_id": "test-plan-001"}
        m._get_active_plan.return_value = {
            "id": "plan-001",
            "current_task": "T001",
            "tasks": {
                "T001": {"files": ["src/main.py", "src/utils.py"]},
            },
        }
        m._get_repos.return_value = ["/tmp/repo1"]
        m.auto_push.return_value = {"pushed": True, "repo": "/tmp/repo1"}
        m.get_git_status.return_value = {
            "repo": "/tmp/repo1", "branch": "main", "dirty": False,
        }
        m.git_sync.return_value = {
            "repo": "/tmp/repo1", "pulled": True, "committed": True, "pushed": True,
        }
        m.git_stash.return_value = {"stashed": True}
        m.git_branch.return_value = {"branch": "feature-x", "action": "create"}
        m.git_tag.return_value = {"tag": "v1.0", "action": "create"}
        yield m


@pytest.fixture
def mock_subprocess():
    """Mock subprocess.run globally (used inside function bodies)."""
    with patch("subprocess.run") as m:
        m.return_value = MagicMock(
            stdout="abc1234 feat: add widget\n",
            stderr="",
            returncode=0,
        )
        yield m


@pytest.fixture
def mock_subprocess_ok(mock_subprocess):
    """subprocess.run returns success by default."""
    return mock_subprocess


@pytest.fixture
def mock_urlopen():
    """Mock urllib.request.urlopen (used inside plan_pr_create_tool)."""
    with patch("urllib.request.urlopen") as m:
        fake_resp = MagicMock()
        fake_resp.read.return_value = json.dumps({
            "html_url": "https://git.example.com/pr/1",
            "number": 1,
        }).encode()
        m.return_value = fake_resp
        yield m


# ═════════════════════════════════════════════════════════════════════════════
#  plan_history_tool
# ═════════════════════════════════════════════════════════════════════════════

class TestPlanHistoryTool:
    def test_no_plan_id_and_no_current_task(self, mock_plan_core):
        """No plan_id provided and no current task → fmt_err."""
        mock_plan_core.get_current_task.return_value = None
        result = _parse(plan_history_tool({}))
        assert "error" in result

    def test_plan_id_from_current_task(self, mock_plan_core, mock_subprocess):
        """No plan_id but current task exists → uses current task's plan_id."""
        mock_plan_core.get_current_task.return_value = {"plan_id": "auto-plan"}
        # Pretend .git exists
        with patch.object(Path, "exists", return_value=True):
            result = _parse(plan_history_tool({}))
        assert result.get("status") == "active"

    def test_plan_id_provided_directly(self, mock_plan_core, mock_subprocess):
        """plan_id provided → skips get_current_task entirely."""
        with patch.object(Path, "exists", return_value=True):
            result = _parse(plan_history_tool({"plan_id": "explicit-plan"}))
        assert result.get("plan_id") == "explicit-plan"

    def test_git_dir_not_exists(self, mock_plan_core):
        """.git dir missing → fmt_info (hint to init git)."""
        with patch.object(Path, "exists", return_value=False):
            result = _parse(plan_history_tool({"plan_id": "p1"}))
        assert "info" in result

    def test_git_log_empty_stdout(self, mock_plan_core, mock_subprocess):
        """Git log succeeds but stdout is empty → fmt_info."""
        mock_subprocess.return_value = MagicMock(stdout="", stderr="", returncode=0)
        with patch.object(Path, "exists", return_value=True):
            result = _parse(plan_history_tool({"plan_id": "p1"}))
        assert "info" in result

    def test_git_log_success(self, mock_plan_core, mock_subprocess):
        """Git log succeeds with output → fmt_ok with history."""
        mock_subprocess.return_value = MagicMock(
            stdout="abc1234 feat: add widget\n",
            stderr="", returncode=0,
        )
        with patch.object(Path, "exists", return_value=True):
            result = _parse(plan_history_tool({"plan_id": "p1"}))
        assert result.get("status") == "active"
        assert "history" in result

    def test_exception_during_git(self, mock_plan_core):
        """Exception during subprocess.run → fmt_err."""
        with patch.object(Path, "exists", return_value=True):
            with patch("subprocess.run", side_effect=FileNotFoundError("git not found")):
                result = _parse(plan_history_tool({"plan_id": "p1"}))
        assert "error" in result

    def test_subprocess_timeout(self, mock_plan_core):
        """subprocess timeout → fmt_err."""
        with patch.object(Path, "exists", return_value=True):
            with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(
                cmd=["git", "log"], timeout=10, output=""
            )):
                result = _parse(plan_history_tool({"plan_id": "p1"}))
        assert "error" in result
        assert "timed out" in result.get("error", "").lower() or "timeout" in result.get("error", "").lower()


# ═════════════════════════════════════════════════════════════════════════════
#  plan_git_init_tool
# ═════════════════════════════════════════════════════════════════════════════

class TestPlanGitInitTool:
    def test_git_dir_already_exists(self, mock_plan_core):
        """.git dir already exists → fmt_info."""
        with patch.object(Path, "exists", return_value=True):
            result = _parse(plan_git_init_tool({}))
        assert "info" in result

    def test_git_init_success(self, mock_plan_core):
        """git init succeeds → fmt_ok with initialized status."""
        mock_run = MagicMock()
        mock_run.returncode = 0
        mock_run.stdout = "Initialized empty Git repo"
        mock_run.stderr = ""
        # gitignore does not exist -> will be created
        exists_marker = {"called": 0}

        def fake_exists():
            exists_marker["called"] += 1
            return False  # .gitignore doesn't exist, .git doesn't exist

        with patch.object(Path, "exists", side_effect=fake_exists):
            with patch.object(Path, "write_text") as mock_write:
                with patch("subprocess.run", return_value=mock_run):
                    result = _parse(plan_git_init_tool({}))
        assert result.get("status") == "initialized"
        mock_write.assert_called_once()

    def test_git_init_success_gitignore_exists(self, mock_plan_core, tmp_path):
        """git init succeeds and .gitignore already exists → does not write it."""
        plans_dir = tmp_path / "test_plans"
        plans_dir.mkdir()
        # .gitignore exists, .git does not
        (plans_dir / ".gitignore").write_text("old content\n")
        mock_plan_core.PLANS_DIR = plans_dir

        mock_run = MagicMock()
        mock_run.returncode = 0
        mock_run.stdout = "Initialized empty Git repo"
        mock_run.stderr = ""

        with patch("subprocess.run", return_value=mock_run):
            with patch.object(Path, "write_text") as mock_write:
                result = _parse(plan_git_init_tool({}))
        assert result.get("status") == "initialized"
        mock_write.assert_not_called()

    def test_git_init_custom_commit_message(self, mock_plan_core, tmp_path):
        """Custom commit message is passed to subprocess."""
        plans_dir = tmp_path / "test_plans"
        plans_dir.mkdir()
        # .gitignore exists, .git does not
        (plans_dir / ".gitignore").write_text("content\n")
        mock_plan_core.PLANS_DIR = plans_dir

        mock_run = MagicMock()
        mock_run.returncode = 0
        calls = []

        def fake_run(*args, **kwargs):
            calls.append(args)  # args[0] is the command list
            return mock_run

        with patch("subprocess.run", side_effect=fake_run):
            result = _parse(plan_git_init_tool({"commit_message": "my init"}))
        assert result.get("status") == "initialized"
        # The commit call should contain our custom message
        cmd_strings = [" ".join(c[0]) if c else "" for c in calls]
        assert any("my init" in s for s in cmd_strings)

    def test_git_init_fails(self, mock_plan_core):
        """git init returns non-zero → fmt_err."""
        mock_run = MagicMock()
        mock_run.returncode = 1
        mock_run.stderr = "error: could not init"
        with patch.object(Path, "exists", return_value=False):  # .git doesn't exist
            with patch("subprocess.run", return_value=mock_run):
                result = _parse(plan_git_init_tool({}))
        assert "error" in result

    def test_git_init_exception(self, mock_plan_core):
        """Exception during git init → fmt_err."""
        with patch.object(Path, "exists", return_value=False):
            with patch("subprocess.run", side_effect=PermissionError("permission denied")):
                result = _parse(plan_git_init_tool({}))
        assert "error" in result


# ═════════════════════════════════════════════════════════════════════════════
#  plan_git_push_tool
# ═════════════════════════════════════════════════════════════════════════════

class TestPlanGitPushTool:
    def test_no_active_plan(self, mock_plan_core):
        """No active plan → fmt_err."""
        mock_plan_core._get_active_plan.return_value = None
        result = _parse(plan_git_push_tool({}))
        assert "error" in result

    def test_no_repos(self, mock_plan_core):
        """No repos configured → fmt_err."""
        mock_plan_core._get_repos.return_value = []
        result = _parse(plan_git_push_tool({}))
        assert "error" in result

    def test_push_success(self, mock_plan_core):
        """Push succeeds → fmt_ok."""
        result = _parse(plan_git_push_tool({}))
        assert result.get("pushed") is True
        mock_plan_core.auto_push.assert_called_once()

    def test_push_with_custom_remote_branch(self, mock_plan_core):
        """Custom remote and branch passed to auto_push."""
        result = _parse(plan_git_push_tool({"remote": "upstream", "branch": "develop"}))  # noqa: F841
        mock_plan_core.auto_push.assert_called_with(
            mock_plan_core._get_repos.return_value, "upstream", "develop"
        )


# ═════════════════════════════════════════════════════════════════════════════
#  plan_git_status_tool
# ═════════════════════════════════════════════════════════════════════════════

class TestPlanGitStatusTool:
    def test_no_active_plan(self, mock_plan_core):
        """No active plan → fmt_err."""
        mock_plan_core._get_active_plan.return_value = None
        result = _parse(plan_git_status_tool({}))
        assert "error" in result

    def test_no_repos(self, mock_plan_core):
        """No repos configured → fmt_err."""
        mock_plan_core._get_repos.return_value = []
        result = _parse(plan_git_status_tool({}))
        assert "error" in result

    def test_status_success(self, mock_plan_core):
        """Status succeeds → fmt_ok."""
        result = _parse(plan_git_status_tool({}))
        assert result.get("status") == "ok"
        assert len(result.get("repos", [])) == 1

    def test_multiple_repos(self, mock_plan_core):
        """Multiple repos each get status checked."""
        mock_plan_core._get_repos.return_value = ["/tmp/repo1", "/tmp/repo2"]
        result = _parse(plan_git_status_tool({}))
        assert len(result.get("repos", [])) == 2
        assert mock_plan_core.get_git_status.call_count == 2


# ═════════════════════════════════════════════════════════════════════════════
#  plan_git_sync_tool
# ═════════════════════════════════════════════════════════════════════════════

class TestPlanGitSyncTool:
    def test_no_active_plan(self, mock_plan_core):
        """No active plan → fmt_err."""
        mock_plan_core._get_active_plan.return_value = None
        result = _parse(plan_git_sync_tool({}))
        assert "error" in result

    def test_no_repos(self, mock_plan_core):
        """No repos configured → fmt_err."""
        mock_plan_core._get_repos.return_value = []
        result = _parse(plan_git_sync_tool({}))
        assert "error" in result

    def test_sync_success(self, mock_plan_core):
        """Sync with defaults → fmt_ok."""
        result = _parse(plan_git_sync_tool({}))
        assert result.get("status") == "ok"
        mock_plan_core.git_sync.assert_called_once()

    def test_sync_no_push(self, mock_plan_core):
        """Sync with push=False."""
        result = _parse(plan_git_sync_tool({"push": False}))  # noqa: F841
        args, _ = mock_plan_core.git_sync.call_args
        assert args[-1] is False

    def test_sync_custom_remote_branch(self, mock_plan_core):
        """Sync with custom remote and branch."""
        result = _parse(plan_git_sync_tool({"remote": "upstream", "branch": "hotfix"}))  # noqa: F841
        args, _ = mock_plan_core.git_sync.call_args
        assert "upstream" in args
        assert "hotfix" in args

    def test_sync_task_without_files(self, mock_plan_core):
        """Plan with current_task but no files list."""
        mock_plan_core._get_active_plan.return_value = {
            "id": "plan-002",
            "current_task": "T002",
            "tasks": {"T002": {}},  # no "files" key
        }
        result = _parse(plan_git_sync_tool({}))
        assert result.get("status") == "ok"

    def test_sync_no_task_in_plan(self, mock_plan_core):
        """Plan with current_task that doesn't exist in tasks dict."""
        mock_plan_core._get_active_plan.return_value = {
            "id": "plan-003",
            "current_task": "MISSING",
            "tasks": {"T001": {"files": ["x.py"]}},
        }
        result = _parse(plan_git_sync_tool({}))
        assert result.get("status") == "ok"


# ═════════════════════════════════════════════════════════════════════════════
#  plan_git_stash_tool
# ═════════════════════════════════════════════════════════════════════════════

class TestPlanGitStashTool:
    def test_no_active_plan(self, mock_plan_core):
        """No active plan → fmt_err."""
        mock_plan_core._get_active_plan.return_value = None
        result = _parse(plan_git_stash_tool({}))
        assert "error" in result

    def test_no_repos(self, mock_plan_core):
        """No repos configured → fmt_err."""
        mock_plan_core._get_repos.return_value = []
        result = _parse(plan_git_stash_tool({}))
        assert "error" in result

    def test_stash_push(self, mock_plan_core):
        """Stash push → fmt_ok."""
        result = _parse(plan_git_stash_tool({"action": "push", "message": "wip"}))
        assert "results" in result
        mock_plan_core.git_stash.assert_called_with("/tmp/repo1", "push", "wip")

    def test_stash_pop(self, mock_plan_core):
        """Stash pop → fmt_ok."""
        result = _parse(plan_git_stash_tool({"action": "pop"}))  # noqa: F841
        mock_plan_core.git_stash.assert_called_with("/tmp/repo1", "pop", "")

    def test_stash_list(self, mock_plan_core):
        """Stash list → fmt_ok."""
        result = _parse(plan_git_stash_tool({"action": "list"}))  # noqa: F841
        mock_plan_core.git_stash.assert_called_with("/tmp/repo1", "list", "")


# ═════════════════════════════════════════════════════════════════════════════
#  plan_git_branch_tool
# ═════════════════════════════════════════════════════════════════════════════

class TestPlanGitBranchTool:
    def test_no_active_plan(self, mock_plan_core):
        """No active plan → fmt_err."""
        mock_plan_core._get_active_plan.return_value = None
        result = _parse(plan_git_branch_tool({}))
        assert "error" in result

    def test_no_repos(self, mock_plan_core):
        """No repos configured → fmt_err."""
        mock_plan_core._get_repos.return_value = []
        result = _parse(plan_git_branch_tool({}))
        assert "error" in result

    def test_branch_current(self, mock_plan_core):
        """Show current branch."""
        result = _parse(plan_git_branch_tool({"action": "current"}))
        assert "results" in result
        mock_plan_core.git_branch.assert_called_with("/tmp/repo1", "current", "", "")

    def test_branch_create(self, mock_plan_core):
        """Create a new branch."""
        result = _parse(plan_git_branch_tool({"action": "create", "name": "feature-y", "start_point": "main"}))  # noqa: F841
        mock_plan_core.git_branch.assert_called_with("/tmp/repo1", "create", "feature-y", "main")

    def test_branch_delete(self, mock_plan_core):
        """Delete a branch."""
        result = _parse(plan_git_branch_tool({"action": "delete", "name": "old-feature"}))  # noqa: F841
        mock_plan_core.git_branch.assert_called_with("/tmp/repo1", "delete", "old-feature", "")

    def test_branch_switch(self, mock_plan_core):
        """Switch to a branch."""
        result = _parse(plan_git_branch_tool({"action": "switch", "name": "main"}))  # noqa: F841
        mock_plan_core.git_branch.assert_called_with("/tmp/repo1", "switch", "main", "")


# ═════════════════════════════════════════════════════════════════════════════
#  plan_git_tag_tool
# ═════════════════════════════════════════════════════════════════════════════

class TestPlanGitTagTool:
    def test_no_active_plan(self, mock_plan_core):
        """No active plan → fmt_err."""
        mock_plan_core._get_active_plan.return_value = None
        result = _parse(plan_git_tag_tool({}))
        assert "error" in result

    def test_no_repos(self, mock_plan_core):
        """No repos configured → fmt_err."""
        mock_plan_core._get_repos.return_value = []
        result = _parse(plan_git_tag_tool({}))
        assert "error" in result

    def test_tag_create(self, mock_plan_core):
        """Create an annotated tag."""
        result = _parse(plan_git_tag_tool({"action": "create", "tag_name": "v2.0", "message": "Release v2.0"}))
        assert "results" in result
        mock_plan_core.git_tag.assert_called_with("/tmp/repo1", "v2.0", "Release v2.0", "create")

    def test_tag_list(self, mock_plan_core):
        """List tags."""
        result = _parse(plan_git_tag_tool({"action": "list"}))  # noqa: F841
        mock_plan_core.git_tag.assert_called_with("/tmp/repo1", "", "", "list")

    def test_tag_delete(self, mock_plan_core):
        """Delete a tag."""
        result = _parse(plan_git_tag_tool({"action": "delete", "tag_name": "v1.0"}))  # noqa: F841
        mock_plan_core.git_tag.assert_called_with("/tmp/repo1", "v1.0", "", "delete")


# ═════════════════════════════════════════════════════════════════════════════
#  plan_pr_create_tool
# ═════════════════════════════════════════════════════════════════════════════

class TestPlanPrCreateTool:
    def test_no_active_plan(self, mock_plan_core):
        """No active plan → fmt_err."""
        mock_plan_core._get_active_plan.return_value = None
        result = _parse(plan_pr_create_tool({"title": "My PR"}))
        assert "error" in result

    def test_no_repos(self, mock_plan_core):
        """No repos configured → fmt_err."""
        mock_plan_core._get_repos.return_value = []
        result = _parse(plan_pr_create_tool({"title": "My PR"}))
        assert "error" in result

    def test_no_title(self, mock_plan_core):
        """No title → fmt_err."""
        result = _parse(plan_pr_create_tool({}))
        assert "error" in result

    def test_no_token(self, mock_plan_core):
        """No Forgejo token → fmt_err."""
        with patch.dict(os.environ, {}, clear=True):
            result = _parse(plan_pr_create_tool({"title": "My PR"}))
        assert "error" in result

    def test_no_dotgit_skipped(self, mock_plan_core):
        """Repo without .git dir → skipped result."""
        token = "test-token-123"
        with patch.dict(os.environ, {"BOT_FORGEJO_TOKEN": token}, clear=True):
            with patch("os.path.isdir", return_value=False):
                result = _parse(plan_pr_create_tool({"title": "My PR"}))
        assert "results" in result
        assert result["results"][0]["status"] == "skipped"

    def test_pr_created_successfully(self, mock_plan_core):
        """PR created successfully via Forgejo API."""
        token = "test-token-123"
        mock_subprocess = MagicMock()
        # First subprocess call: git remote get-url origin
        mock_subprocess.return_value = MagicMock(
            stdout="git@git.agentiker.de:owner/my-repo.git\n",
            stderr="", returncode=0,
        )

        with patch.dict(os.environ, {"BOT_FORGEJO_TOKEN": token}, clear=True):
            with patch("os.path.isdir", return_value=True):
                with patch("subprocess.run", mock_subprocess):
                    with patch("urllib.request.urlopen") as mock_urlopen:
                        fake_resp = MagicMock()
                        fake_resp.read.return_value = json.dumps({
                            "html_url": "https://git.agentiker.de/pr/42",
                            "number": 42,
                        }).encode()
                        mock_urlopen.return_value = fake_resp
                        result = _parse(plan_pr_create_tool({  # noqa: F841
                            "title": "My PR",
                            "body": "Description",
                            "base": "main",
                        }))


        assert "results" in result
        assert result["results"][0]["status"] == "created"
        assert result["results"][0]["pr_number"] == 42

    def test_pr_with_explicit_owner_repo(self, mock_plan_core):
        """Owner and repo_name provided explicitly."""
        token = "test-token-123"

        with patch.dict(os.environ, {"FORGEJO_TOKEN": token}, clear=True):
            with patch("os.path.isdir", return_value=True):
                with patch("subprocess.run") as mock_subprocess:
                    # Remote URL won't be needed since owner/repo explicit
                    mock_subprocess.return_value = MagicMock(
                        stdout="git@git.agentiker.de:ignored/repo.git\n",
                        stderr="", returncode=0,
                    )
                    with patch("urllib.request.urlopen") as mock_urlopen:
                        fake_resp = MagicMock()
                        fake_resp.read.return_value = json.dumps({
                            "html_url": "https://git.agentiker.de/pr/1",
                            "number": 1,
                        }).encode()
                        mock_urlopen.return_value = fake_resp
                        result = _parse(plan_pr_create_tool({  # noqa: F841
                            "title": "Explicit PR",
                            "owner": "my-team",
                            "repo_name": "explicit-repo",
                        }))

        assert result["results"][0]["status"] == "created"

    def test_pr_git_ivory_green_remote(self, mock_plan_core):
        """Remote URL contains git.ivory.green → uses different API URL."""
        token = "test-token-123"

        with patch.dict(os.environ, {"GITEA_TOKEN": token}, clear=True):
            with patch("os.path.isdir", return_value=True):
                with patch("subprocess.run") as mock_subprocess:
                    mock_subprocess.return_value = MagicMock(
                        stdout="git@git.ivory.green:team/project.git\n",
                        stderr="", returncode=0,
                    )
                    with patch("urllib.request.urlopen") as mock_urlopen:
                        fake_resp = MagicMock()
                        fake_resp.read.return_value = json.dumps({
                            "html_url": "https://git.ivory.green/pr/5",
                            "number": 5,
                        }).encode()
                        mock_urlopen.return_value = fake_resp
                        result = _parse(plan_pr_create_tool({  # noqa: F841
                            "title": "Ivory PR",
                        }))

        assert result["results"][0]["status"] == "created"

    def test_pr_auto_detect_branch(self, mock_plan_core):
        """Head not provided → auto-detect via rev-parse."""

        def subprocess_side_effect(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args", [])
            # First call: git remote -> remote URL
            # Second call: git rev-parse -> branch name
            if "remote" in cmd:
                return MagicMock(stdout="git@git.agentiker.de:owner/repo.git\n", stderr="", returncode=0)
            else:
                return MagicMock(stdout="feature-branch\n", stderr="", returncode=0)

        token = "test-token-123"
        with patch.dict(os.environ, {"BOT_FORGEJO_TOKEN": token}, clear=True):
            with patch("os.path.isdir", return_value=True):
                with patch("subprocess.run", side_effect=subprocess_side_effect):
                    with patch("urllib.request.urlopen") as mock_urlopen:
                        fake_resp = MagicMock()
                        fake_resp.read.return_value = json.dumps({
                            "html_url": "https://git.agentiker.de/pr/99",
                            "number": 99,
                        }).encode()
                        mock_urlopen.return_value = fake_resp
                        result = _parse(plan_pr_create_tool({  # noqa: F841
                            "title": "Auto branch PR",
                        }))

        assert result["results"][0]["status"] == "created"

    def test_pr_cannot_detect_owner_repo(self, mock_plan_core):
        """Remote URL can't be parsed → failed result."""
        token = "test-token-123"
        with patch.dict(os.environ, {"BOT_FORGEJO_TOKEN": token}, clear=True):
            with patch("os.path.isdir", return_value=True):
                with patch("subprocess.run") as mock_subprocess:
                    # Unparseable remote URL
                    mock_subprocess.return_value = MagicMock(
                        stdout="invalid-url\n",
                        stderr="", returncode=0,
                    )
                    result = _parse(plan_pr_create_tool({  # noqa: F841
                        "title": "Bad remote PR",
                    }))
        assert result["results"][0]["status"] == "failed"

    def test_pr_http_error(self, mock_plan_core):
        """HTTP error from Forgejo API → error result."""
        token = "test-token-123"
        with patch.dict(os.environ, {"BOT_FORGEJO_TOKEN": token}, clear=True):
            with patch("os.path.isdir", return_value=True):
                with patch("subprocess.run") as mock_subprocess:
                    mock_subprocess.return_value = MagicMock(
                        stdout="git@git.agentiker.de:owner/my-repo.git\n",
                        stderr="", returncode=0,
                    )
                    with patch("urllib.request.urlopen") as mock_urlopen:
                        # Simulate HTTPError; "reason" is auto-populated from msg arg
                        import urllib.error
                        http_err = urllib.error.HTTPError(
                            "https://example.com", 422, "Unprocessable Entity", {}, None,
                        )
                        mock_urlopen.side_effect = http_err
                        result = _parse(plan_pr_create_tool({  # noqa: F841
                            "title": "Failing PR",
                        }))
        assert result["results"][0]["status"] == "error"

    def test_pr_status_exception(self, mock_plan_core):
        """Exception with .status but no .code attribute → error with HTTP status."""
        class _StatusErr(Exception):
            def __init__(self, status, msg):
                self.status = status
                super().__init__(msg)

        token = "test-token-123"
        with patch.dict(os.environ, {"BOT_FORGEJO_TOKEN": token}, clear=True):
            with patch("os.path.isdir", return_value=True):
                with patch("subprocess.run") as mock_subprocess:
                    mock_subprocess.return_value = MagicMock(
                        stdout="git@git.agentiker.de:owner/my-repo.git\n",
                        stderr="", returncode=0,
                    )
                    with patch("urllib.request.urlopen", side_effect=_StatusErr(500, "Internal Server Error")):
                        result = _parse(plan_pr_create_tool({  # noqa: F841
                            "title": "Status error PR",
                        }))
        assert result["results"][0]["status"] == "error"

    def test_pr_generic_exception(self, mock_plan_core):
        """Generic exception during PR creation → error result."""
        token = "test-token-123"
        with patch.dict(os.environ, {"BOT_FORGEJO_TOKEN": token}, clear=True):
            with patch("os.path.isdir", return_value=True):
                with patch("subprocess.run") as mock_subprocess:
                    mock_subprocess.return_value = MagicMock(
                        stdout="git@git.agentiker.de:owner/my-repo.git\n",
                        stderr="", returncode=0,
                    )
                    with patch("urllib.request.urlopen", side_effect=ConnectionError("connection refused")):
                        result = _parse(plan_pr_create_tool({  # noqa: F841
                            "title": "Connection error PR",
                        }))
        assert result["results"][0]["status"] == "error"

    def test_pr_github_https_remote(self, mock_plan_core):
        """HTTPS remote URL format is parsed correctly."""
        token = "test-token-123"
        with patch.dict(os.environ, {"BOT_FORGEJO_TOKEN": token}, clear=True):
            with patch("os.path.isdir", return_value=True):
                with patch("subprocess.run") as mock_subprocess:
                    mock_subprocess.return_value = MagicMock(
                        stdout="https://github.com/myorg/myrepo.git\n",
                        stderr="", returncode=0,
                    )
                    with patch("urllib.request.urlopen") as mock_urlopen:
                        fake_resp = MagicMock()
                        fake_resp.read.return_value = json.dumps({
                            "html_url": "https://git.agentiker.de/pr/7",
                            "number": 7,
                        }).encode()
                        mock_urlopen.return_value = fake_resp
                        result = _parse(plan_pr_create_tool({  # noqa: F841
                            "title": "HTTPS remote PR",
                        }))
        # Owner/repo should be detected from URL
        assert result["results"][0]["status"] == "created"

    def test_pr_multiple_repos(self, mock_plan_core):
        """Multiple repos each get a PR created."""
        mock_plan_core._get_repos.return_value = ["/tmp/repo1", "/tmp/repo2"]
        token = "test-token-123"
        with patch.dict(os.environ, {"BOT_FORGEJO_TOKEN": token}, clear=True):
            with patch("os.path.isdir", return_value=True):
                with patch("subprocess.run") as mock_subprocess:
                    mock_subprocess.return_value = MagicMock(
                        stdout="git@git.agentiker.de:owner/my-repo.git\n",
                        stderr="", returncode=0,
                    )
                    with patch("urllib.request.urlopen") as mock_urlopen:
                        fake_resp = MagicMock()
                        fake_resp.read.return_value = json.dumps({
                            "html_url": "https://git.agentiker.de/pr/1",
                            "number": 1,
                        }).encode()
                        mock_urlopen.return_value = fake_resp
                        result = _parse(plan_pr_create_tool({  # noqa: F841
                            "title": "Multi repo PR",
                        }))
        assert len(result["results"]) == 2
        assert all(r["status"] == "created" for r in result["results"])
